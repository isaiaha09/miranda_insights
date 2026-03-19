from datetime import timedelta

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import models
from django.utils import timezone


ACCOUNT_DELETION_GRACE_PERIOD = timedelta(days=7)


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


def purge_expired_account_deletions(reference_time=None):
	now = reference_time or timezone.now()
	user_ids = list(AccountDeletionRequest.objects.filter(scheduled_for__lte=now).values_list("user_id", flat=True))
	if not user_ids:
		return 0
	user_model = get_user_model()
	user_model.objects.filter(pk__in=user_ids).delete()
	return len(user_ids)
