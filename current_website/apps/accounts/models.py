from django.conf import settings
from django.db import models


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
