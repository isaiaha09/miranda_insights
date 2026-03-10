from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .newsletter_blocks import build_plain_text


class NewsletterSubscriber(models.Model):
	email = models.EmailField(unique=True)
	is_active = models.BooleanField(default=True)
	subscribed_at = models.DateTimeField(auto_now_add=True)
	unsubscribed_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ["-subscribed_at"]

	def __str__(self) -> str:
		return self.email


class NewsletterImageAsset(models.Model):
	name = models.CharField(max_length=140)
	image = models.ImageField(upload_to="newsletter/images/%Y/%m")
	alt_text = models.CharField(max_length=255, blank=True)
	default_caption = models.CharField(max_length=255, blank=True)
	is_active = models.BooleanField(default=True)
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		null=True,
		blank=True,
		on_delete=models.SET_NULL,
		related_name="newsletter_image_assets",
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["name", "-created_at"]

	def __str__(self) -> str:
		return self.name

	def to_editor_payload(self):
		return {
			"id": self.pk,
			"name": self.name,
			"url": self.image.url if self.image else "",
			"alt_text": self.alt_text,
			"caption": self.default_caption,
		}


class NewsletterBlockTemplate(models.Model):
	CATEGORY_GENERAL = "general"
	CATEGORY_HERO = "hero"
	CATEGORY_EVENT = "event"
	CATEGORY_ARTICLE = "article"
	CATEGORY_CHOICES = [
		(CATEGORY_GENERAL, "General"),
		(CATEGORY_HERO, "Hero"),
		(CATEGORY_EVENT, "Event"),
		(CATEGORY_ARTICLE, "Article digest"),
	]

	name = models.CharField(max_length=140)
	slug = models.SlugField(unique=True)
	description = models.CharField(max_length=255, blank=True)
	category = models.CharField(max_length=24, choices=CATEGORY_CHOICES, default=CATEGORY_GENERAL)
	content_blocks = models.JSONField(default=list)
	is_builtin = models.BooleanField(default=False)
	is_active = models.BooleanField(default=True)
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		null=True,
		blank=True,
		on_delete=models.SET_NULL,
		related_name="newsletter_block_templates",
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["category", "name"]

	def __str__(self) -> str:
		return self.name

	def to_editor_payload(self):
		return {
			"id": self.pk,
			"name": self.name,
			"slug": self.slug,
			"description": self.description,
			"category": self.category,
			"blocks": self.content_blocks,
			"is_builtin": self.is_builtin,
		}


class NewsletterCampaign(models.Model):
	MODE_CUSTOM = "custom"
	MODE_AUTOMATED = "automated"
	MODE_CHOICES = [
		(MODE_CUSTOM, "Custom"),
		(MODE_AUTOMATED, "Automated"),
	]

	FREQ_DAILY = "daily"
	FREQ_WEEKLY = "weekly"
	FREQ_MONTHLY = "monthly"
	FREQ_INTERVAL = "interval"
	FREQUENCY_CHOICES = [
		(FREQ_DAILY, "Daily"),
		(FREQ_WEEKLY, "Weekly"),
		(FREQ_MONTHLY, "Monthly"),
		(FREQ_INTERVAL, "Every N days"),
	]

	name = models.CharField(max_length=120)
	subject = models.CharField(max_length=200)
	preheader = models.CharField(
		max_length=255,
		blank=True,
		help_text="Optional preview text shown in supporting email clients.",
	)
	content_blocks = models.JSONField(
		default=list,
		blank=True,
		help_text="Structured content blocks used to compose the newsletter email.",
	)
	body = models.TextField(
		blank=True,
		help_text="Legacy plain text fallback. Optional placeholder: {date}",
	)
	mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_CUSTOM)
	include_subscribers = models.BooleanField(
		default=True,
		help_text="If enabled, send to all active newsletter subscribers.",
	)
	direct_recipients = models.TextField(
		blank=True,
		help_text="Optional extra recipients (comma/newline separated emails).",
	)

	is_active = models.BooleanField(default=True)
	frequency = models.CharField(
		max_length=20, choices=FREQUENCY_CHOICES, default=FREQ_WEEKLY
	)
	interval_days = models.PositiveIntegerField(default=7)
	weekday = models.PositiveSmallIntegerField(
		null=True,
		blank=True,
		help_text="0=Monday ... 6=Sunday (for weekly automation)",
	)
	day_of_month = models.PositiveSmallIntegerField(
		null=True,
		blank=True,
		help_text="1-28 (for monthly automation)",
	)
	send_time = models.TimeField(default=datetime.strptime("09:00", "%H:%M").time())

	last_sent_at = models.DateTimeField(null=True, blank=True)
	next_send_at = models.DateTimeField(null=True, blank=True)

	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		null=True,
		blank=True,
		on_delete=models.SET_NULL,
		related_name="newsletter_campaigns",
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self) -> str:
		return self.name

	def has_block_content(self) -> bool:
		return bool(self.content_blocks)

	def rendered_body(self) -> str:
		"""Render the plain text newsletter body for delivery."""
		now = timezone.localtime()
		date_value = now.strftime("%Y-%m-%d")

		if self.content_blocks:
			return build_plain_text(self.content_blocks, formatter=lambda value: self._render_placeholder_text(value, date_value))

		return self._render_placeholder_text(self.body, date_value)

	def rendered_preheader(self) -> str:
		now = timezone.localtime()
		return self._render_placeholder_text(self.preheader, now.strftime("%Y-%m-%d"))

	def _render_placeholder_text(self, value: str, date_value: str) -> str:
		value = value or ""
		try:
			return value.format(date=date_value)
		except Exception:
			return value

	def compute_next_send_at(self, from_dt=None):
		"""Compute the next scheduled send datetime based on frequency controls."""
		base = timezone.localtime(from_dt or timezone.now())
		target_time = self.send_time

		if self.frequency == self.FREQ_DAILY:
			candidate = base.replace(
				hour=target_time.hour,
				minute=target_time.minute,
				second=0,
				microsecond=0,
			)
			if candidate <= base:
				candidate += timedelta(days=1)
			return candidate

		if self.frequency == self.FREQ_WEEKLY:
			desired_weekday = self.weekday if self.weekday is not None else 0
			days_ahead = (desired_weekday - base.weekday()) % 7
			candidate = base + timedelta(days=days_ahead)
			candidate = candidate.replace(
				hour=target_time.hour,
				minute=target_time.minute,
				second=0,
				microsecond=0,
			)
			if candidate <= base:
				candidate += timedelta(days=7)
			return candidate

		if self.frequency == self.FREQ_MONTHLY:
			desired_day = self.day_of_month or 1
			desired_day = max(1, min(28, desired_day))
			year = base.year
			month = base.month

			candidate = base.replace(
				day=desired_day,
				hour=target_time.hour,
				minute=target_time.minute,
				second=0,
				microsecond=0,
			)
			if candidate <= base:
				month += 1
				if month > 12:
					month = 1
					year += 1
				candidate = candidate.replace(year=year, month=month, day=desired_day)
			return candidate

		# interval mode
		interval = max(1, self.interval_days)
		candidate = base + timedelta(days=interval)
		candidate = candidate.replace(
			hour=target_time.hour,
			minute=target_time.minute,
			second=0,
			microsecond=0,
		)
		return candidate


class NewsletterSendLog(models.Model):
	STATUS_SENT = "sent"
	STATUS_FAILED = "failed"
	STATUS_CHOICES = [
		(STATUS_SENT, "Sent"),
		(STATUS_FAILED, "Failed"),
	]

	campaign = models.ForeignKey(
		NewsletterCampaign,
		on_delete=models.CASCADE,
		related_name="send_logs",
	)
	recipient_email = models.EmailField()
	status = models.CharField(max_length=12, choices=STATUS_CHOICES)
	error_message = models.TextField(blank=True)
	sent_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-sent_at"]

	def __str__(self) -> str:
		return f"{self.campaign.name} -> {self.recipient_email} ({self.status})"
