from django.contrib import admin
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.formats import date_format
from django.utils.html import format_html

from apps.operations.services import dispatch_newsletter_campaign, should_queue_outbound_delivery
from .forms import NewsletterBlockTemplateAdminForm, NewsletterCampaignAdminForm
from .models import NewsletterBlockTemplate, NewsletterCampaign, NewsletterImageAsset, NewsletterSendLog, NewsletterSubscriber, newsletter_localtime
from .services import send_campaign


User = get_user_model()


class StaffCreatedByAdminMixin:
	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "created_by":
			kwargs["queryset"] = User.objects.filter(is_staff=True).order_by("username")
		return super().formfield_for_foreignkey(db_field, request, **kwargs)


class HasAccountListFilter(admin.SimpleListFilter):
	title = "has account"
	parameter_name = "has_account"

	def lookups(self, request, model_admin):
		return (
			("yes", "Has account"),
			("no", "No account"),
		)

	def queryset(self, request, queryset):
		value = self.value()
		if value == "yes":
			return queryset.filter(has_account=True)
		if value == "no":
			return queryset.filter(has_account=False)
		return queryset


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
	list_display = ("email", "has_account", "is_active", "subscribed_at", "unsubscribed_at")
	list_filter = (HasAccountListFilter, "is_active", "subscribed_at")
	search_fields = ("email",)

	def get_queryset(self, request):
		queryset = super().get_queryset(request)
		matching_users = User.objects.filter(email__iexact=OuterRef("email"))
		return queryset.annotate(has_account=Exists(matching_users))

	@admin.display(boolean=True, ordering="has_account", description="Has account")
	def has_account(self, obj):
		return bool(getattr(obj, "has_account", False))


@admin.register(NewsletterImageAsset)
class NewsletterImageAssetAdmin(StaffCreatedByAdminMixin, admin.ModelAdmin):
	list_display = ("name", "image_preview", "is_active", "created_at")
	list_filter = ("is_active", "created_at")
	search_fields = ("name", "alt_text", "default_caption")
	readonly_fields = ("created_at", "updated_at", "image_preview")
	fields = ("name", "image", "image_preview", "alt_text", "default_caption", "is_active", "created_by", "created_at", "updated_at")

	def image_preview(self, obj):
		if not obj or not obj.image:
			return "No image"
		return format_html('<img src="{}" alt="{}" style="max-height:72px;border-radius:12px;" />', obj.image.url, obj.alt_text or obj.name)

	image_preview.short_description = "Preview"

	def save_model(self, request, obj, form, change):
		if not obj.created_by_id:
			obj.created_by = request.user
		super().save_model(request, obj, form, change)


@admin.register(NewsletterBlockTemplate)
class NewsletterBlockTemplateAdmin(StaffCreatedByAdminMixin, admin.ModelAdmin):
	form = NewsletterBlockTemplateAdminForm
	list_display = ("name", "category", "is_builtin", "is_active", "updated_at")
	list_filter = ("category", "is_builtin", "is_active")
	search_fields = ("name", "slug", "description")
	readonly_fields = ("created_at", "updated_at")
	fields = ("name", "slug", "description", "category", "content_blocks", "is_builtin", "is_active", "created_by", "created_at", "updated_at")

	def save_model(self, request, obj, form, change):
		if not obj.created_by_id:
			obj.created_by = request.user
		super().save_model(request, obj, form, change)


@admin.register(NewsletterCampaign)
class NewsletterCampaignAdmin(StaffCreatedByAdminMixin, admin.ModelAdmin):
	form = NewsletterCampaignAdminForm
	list_display = (
		"name",
		"mode",
		"is_active",
		"frequency",
		"next_send_at_display",
		"last_sent_at",
		"send_now_link",
	)
	list_filter = ("mode", "is_active", "frequency")
	search_fields = ("name", "subject")
	actions = ["send_selected_campaigns_now"]
	readonly_fields = (
		"last_sent_at",
		"next_send_at_display",
		"created_at",
		"updated_at",
		"send_now_button",
	)

	fieldsets = (
		(
			"Content",
			{
				"fields": (
					"name",
					"subject",
					"preheader",
					"content_blocks",
					"mode",
					"include_subscribers",
					"direct_recipients",
					"is_active",
				)
			},
		),
		(
			"Automation Controls",
			{
				"description": "Configure for automated campaigns (daily/weekly/monthly/interval).",
				"fields": (
					"frequency",
					"interval_days",
					"weekday",
					"day_of_month",
					"send_time",
					"next_send_at_display",
				),
			},
		),
		(
			"Audit",
			{
				"fields": (
					"created_by",
					"last_sent_at",
					"send_now_button",
					"created_at",
					"updated_at",
				)
			},
		),
	)

	def get_urls(self):
		urls = super().get_urls()
		custom_urls = [
			path(
				"<path:object_id>/send-now/",
				self.admin_site.admin_view(self.send_now_view),
				name="news_newslettercampaign_send_now",
			),
		]
		return custom_urls + urls

	def send_now_button(self, obj):
		if not obj or not obj.pk:
			return "Save campaign first, then use Send now."
		url = reverse("admin:news_newslettercampaign_send_now", args=[obj.pk])
		return format_html('<a class="button" href="{}">Send this campaign now</a>', url)

	send_now_button.short_description = "Run"

	def send_now_link(self, obj):
		url = reverse("admin:news_newslettercampaign_send_now", args=[obj.pk])
		return format_html('<a href="{}">Send now</a>', url)

	send_now_link.short_description = "Run"

	def next_send_at_display(self, obj):
		if not obj or not obj.next_send_at:
			return "-"
		return date_format(newsletter_localtime(obj.next_send_at), "DATETIME_FORMAT")

	next_send_at_display.short_description = "Next send at"

	def send_now_view(self, request, object_id):
		campaign = self.get_object(request, object_id)
		if campaign is None:
			self.message_user(request, "Campaign not found.", level=messages.ERROR)
			return HttpResponseRedirect(reverse("admin:news_newslettercampaign_changelist"))

		queued, sent, failed = dispatch_newsletter_campaign(campaign)
		message = (
			"Campaign queued for background delivery."
			if queued
			else f"Campaign send complete. Sent: {sent}, Failed: {failed}"
		)
		self.message_user(request, message)
		return HttpResponseRedirect(
			reverse("admin:news_newslettercampaign_change", args=[campaign.pk])
		)

	@admin.action(description="Send selected campaigns now")
	def send_selected_campaigns_now(self, request, queryset):
		queued_count = 0
		total_sent = 0
		total_failed = 0
		for campaign in queryset:
			queued, sent, failed = dispatch_newsletter_campaign(campaign)
			if queued:
				queued_count += 1
			total_sent += sent
			total_failed += failed
		if queued_count:
			self.message_user(request, f"Queued {queued_count} campaign(s) for background delivery.")
		else:
			self.message_user(request, f"Campaign send complete. Sent: {total_sent}, Failed: {total_failed}")

	def save_model(self, request, obj, form, change):
		if not obj.created_by_id:
			obj.created_by = request.user
		if obj.mode == NewsletterCampaign.MODE_AUTOMATED and obj.is_active and not obj.next_send_at:
			obj.next_send_at = obj.compute_next_send_at()
		super().save_model(request, obj, form, change)


@admin.register(NewsletterSendLog)
class NewsletterSendLogAdmin(admin.ModelAdmin):
	list_display = ("campaign", "recipient_email", "status", "sent_at")
	list_filter = ("status", "sent_at", "campaign")
	search_fields = ("recipient_email", "campaign__name", "error_message")
	readonly_fields = ("campaign", "recipient_email", "status", "error_message", "sent_at")
