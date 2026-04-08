import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import models
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from .services import delete_account_for_user


ACCOUNT_DELETION_GRACE_PERIOD = timedelta(days=7)
logger = logging.getLogger(__name__)


class AccountProfile(models.Model):
	INDUSTRY_LAW_FIRM = "law_firm"
	INDUSTRY_FINANCIAL = "financial_institution"
	INDUSTRY_GOVERNMENT = "government_agency"
	INDUSTRY_HEALTHCARE = "healthcare"
	INDUSTRY_EDUCATION = "educational_institution"
	INDUSTRY_COUNSELING = "counseling_services"
	INDUSTRY_INDIVIDUAL = "individual"
	INDUSTRY_OTHER = "other"

	INDUSTRY_CHOICES = (
		(INDUSTRY_LAW_FIRM, "Law Firm"),
		(INDUSTRY_FINANCIAL, "Financial Institution"),
		(INDUSTRY_GOVERNMENT, "Government Agency"),
		(INDUSTRY_HEALTHCARE, "Healthcare"),
		(INDUSTRY_EDUCATION, "Educational Institution"),
		(INDUSTRY_COUNSELING, "Counseling Services"),
		(INDUSTRY_INDIVIDUAL, "Individual"),
		(INDUSTRY_OTHER, "Other"),
	)

	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_profile")
	industry_type = models.CharField(max_length=64, choices=INDUSTRY_CHOICES)
	phone_number = models.CharField(max_length=40)
	two_factor_enabled = models.BooleanField(default=False)
	two_factor_secret = models.CharField(max_length=64, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = "Account Profile"
		verbose_name_plural = "Account Profiles"

	def __str__(self):
		return f"Profile for {self.user.username}"


class AccountDeletionRequest(models.Model):
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_deletion_request")
	requested_at = models.DateTimeField(default=timezone.now)
	scheduled_for = models.DateTimeField(db_index=True)

	class Meta:
		verbose_name = "Account Deletion Request"
		verbose_name_plural = "Account Deletion Requests"
		ordering = ["-requested_at"]

	def __str__(self):
		return f"Deletion request for {self.user.username}"

	@property
	def is_recoverable(self):
		return self.scheduled_for > timezone.now()

	@classmethod
	def schedule_for_user(cls, user, reference_time=None):
		now = reference_time or timezone.now()
		deletion_request, _ = cls.objects.get_or_create(
			user=user,
			defaults={
				"requested_at": now,
				"scheduled_for": now + ACCOUNT_DELETION_GRACE_PERIOD,
			},
		)
		deletion_request.requested_at = now
		deletion_request.scheduled_for = now + ACCOUNT_DELETION_GRACE_PERIOD
		deletion_request.save(update_fields=["requested_at", "scheduled_for"])
		return deletion_request


class MobilePushDevice(models.Model):
	PLATFORM_IOS = "ios"
	PLATFORM_ANDROID = "android"
	PLATFORM_UNKNOWN = "unknown"
	PLATFORM_CHOICES = (
		(PLATFORM_IOS, "iOS"),
		(PLATFORM_ANDROID, "Android"),
		(PLATFORM_UNKNOWN, "Unknown"),
	)

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mobile_push_devices")
	token = models.CharField(max_length=255, unique=True)
	platform = models.CharField(max_length=24, choices=PLATFORM_CHOICES, default=PLATFORM_UNKNOWN)
	device_name = models.CharField(max_length=120, blank=True)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	last_registered_at = models.DateTimeField(default=timezone.now)

	class Meta:
		verbose_name = "Mobile Push Device"
		verbose_name_plural = "Mobile Push Devices"
		ordering = ["-last_registered_at", "-updated_at"]

	def __str__(self):
		label = self.device_name or self.get_platform_display()
		return f"{label} for {self.user.username}"


def purge_expired_account_deletions(reference_time=None):
	now = reference_time or timezone.now()
	try:
		deletion_requests = list(AccountDeletionRequest.objects.filter(scheduled_for__lte=now).select_related("user"))
	except (OperationalError, ProgrammingError):
		logger.warning("Account deletion cleanup skipped because the account deletion table is not available yet.")
		return 0
	if not deletion_requests:
		return 0
	deleted_count = 0
	for deletion_request in deletion_requests:
		if delete_account_for_user(deletion_request.user, send_confirmation_email=True):
			deleted_count += 1
	return deleted_count
