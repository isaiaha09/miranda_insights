from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import AccountProfile


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
	list_display = ("user", "industry_type", "phone_number", "two_factor_enabled", "created_at")
	search_fields = ("user__username", "user__email", "phone_number")
