from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import AccountDeletionRequest, AccountProfile
from .services import delete_account_for_user


User = get_user_model()


try:
	admin.site.unregister(User)
except admin.sites.NotRegistered:
	pass


@admin.register(User)
class StaffUserAdmin(UserAdmin):
	def get_queryset(self, request):
		return super().get_queryset(request).filter(is_staff=True)


@admin.register(AccountProfile)
class AccountProfileAdmin(admin.ModelAdmin):
	list_display = ("user", "industry_type", "phone_number", "two_factor_enabled", "account_deletion_status", "account_deletion_scheduled_for", "created_at")
	search_fields = ("user__username", "user__email", "phone_number")

	def delete_model(self, request, obj):
		delete_account_for_user(obj.user, send_confirmation_email=True)

	def delete_queryset(self, request, queryset):
		users = [profile.user for profile in queryset.select_related("user")]
		for user in users:
			delete_account_for_user(user, send_confirmation_email=True)

	@admin.display(description="Deletion status")
	def account_deletion_status(self, obj):
		return "Scheduled" if getattr(obj.user, "account_deletion_request", None) else "Active"

	@admin.display(description="Deletion scheduled for")
	def account_deletion_scheduled_for(self, obj):
		deletion_request = getattr(obj.user, "account_deletion_request", None)
		return deletion_request.scheduled_for if deletion_request else "-"


@admin.register(AccountDeletionRequest)
class AccountDeletionRequestAdmin(admin.ModelAdmin):
	list_display = ("user", "requested_at", "scheduled_for")
	search_fields = ("user__username", "user__email")
	readonly_fields = ("requested_at", "scheduled_for")
