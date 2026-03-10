from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html

from .forms import NewsletterBlockTemplateAdminForm, NewsletterCampaignAdminForm
from .models import NewsletterBlockTemplate, NewsletterCampaign, NewsletterImageAsset, NewsletterSendLog, NewsletterSubscriber
from .services import send_campaign


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
	list_display = ("email", "is_active", "subscribed_at", "unsubscribed_at")
	list_filter = ("is_active", "subscribed_at")
	search_fields = ("email",)


@admin.register(NewsletterImageAsset)
class NewsletterImageAssetAdmin(admin.ModelAdmin):
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
class NewsletterBlockTemplateAdmin(admin.ModelAdmin):
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
class NewsletterCampaignAdmin(admin.ModelAdmin):
	form = NewsletterCampaignAdminForm
	list_display = (
		"name",
		"mode",
		"is_active",
		"frequency",
		"next_send_at",
		"last_sent_at",
		"send_now_link",
	)
	list_filter = ("mode", "is_active", "frequency")
	search_fields = ("name", "subject")
	actions = ["send_selected_campaigns_now"]
	readonly_fields = (
		"last_sent_at",
		"next_send_at",
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
					"next_send_at",
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

	def send_now_view(self, request, object_id):
		campaign = self.get_object(request, object_id)
		if campaign is None:
			self.message_user(request, "Campaign not found.", level=messages.ERROR)
			return HttpResponseRedirect(reverse("admin:news_newslettercampaign_changelist"))

		sent, failed = send_campaign(campaign)
		self.message_user(
			request,
			f"Campaign send complete. Sent: {sent}, Failed: {failed}",
		)
		return HttpResponseRedirect(
			reverse("admin:news_newslettercampaign_change", args=[campaign.pk])
		)

	@admin.action(description="Send selected campaigns now")
	def send_selected_campaigns_now(self, request, queryset):
		total_sent = 0
		total_failed = 0
		for campaign in queryset:
			sent, failed = send_campaign(campaign)
			total_sent += sent
			total_failed += failed
		self.message_user(
			request,
			f"Campaign send complete. Sent: {total_sent}, Failed: {total_failed}",
		)

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
