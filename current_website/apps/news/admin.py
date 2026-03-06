from django.contrib import admin

from .models import NewsletterCampaign, NewsletterSendLog, NewsletterSubscriber
from .services import send_campaign


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
	list_display = ("email", "is_active", "subscribed_at", "unsubscribed_at")
	list_filter = ("is_active", "subscribed_at")
	search_fields = ("email",)


@admin.register(NewsletterCampaign)
class NewsletterCampaignAdmin(admin.ModelAdmin):
	list_display = (
		"name",
		"mode",
		"is_active",
		"frequency",
		"next_send_at",
		"last_sent_at",
	)
	list_filter = ("mode", "is_active", "frequency")
	search_fields = ("name", "subject")
	actions = ["send_selected_campaigns_now"]
	readonly_fields = ("last_sent_at", "next_send_at", "created_at", "updated_at")

	fieldsets = (
		(
			"Content",
			{
				"fields": (
					"name",
					"subject",
					"body",
					"mode",
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
					"created_at",
					"updated_at",
				)
			},
		),
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
