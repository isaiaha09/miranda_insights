from django.contrib.auth import get_user_model
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from .admin import StaffUserAdmin
from .models import AccountProfile
from apps.news.models import NewsletterSubscriber


User = get_user_model()


class LoginViewTests(TestCase):
	def test_login_shows_incorrect_credentials_message(self):
		User.objects.create_user(username="isaiah", email="isaiah@example.com", password="correct-pass-123")

		response = self.client.post(
			reverse("login"),
			{"username": "isaiah", "password": "wrong-pass"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Incorrect username or password.")


class StaffUserAdminTests(TestCase):
	def test_users_admin_only_lists_staff_accounts(self):
		staff_user = User.objects.create_user(
			username="staffuser",
			email="staff@example.com",
			password="test-pass-123",
			is_staff=True,
		)
		client_user = User.objects.create_user(
			username="clientuser",
			email="client@example.com",
			password="test-pass-123",
			is_staff=False,
		)

		admin_instance = StaffUserAdmin(User, AdminSite())
		request = RequestFactory().get("/admin/auth/user/")
		queryset = admin_instance.get_queryset(request)

		self.assertIn(staff_user, queryset)
		self.assertNotIn(client_user, queryset)


class DashboardNewsletterPreferenceTests(TestCase):
	def test_dashboard_get_handles_missing_account_profile(self):
		user = User.objects.create_user(username="noprof", email="noprof@example.com", password="test-pass-123")

		self.client.login(username="noprof", password="test-pass-123")
		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Portal Settings")
		self.assertContains(response, "2FA not enabled")

	def test_dashboard_2fa_action_handles_missing_account_profile(self):
		user = User.objects.create_user(username="noprof2", email="noprof2@example.com", password="test-pass-123")

		self.client.login(username="noprof2", password="test-pass-123")
		response = self.client.post(
			reverse("dashboard"),
			{"settings_action": "start_2fa_setup"},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Your account profile is incomplete. Please contact support for assistance.")

	def test_dashboard_unsubscribe_deletes_subscriber(self):
		user = User.objects.create_user(username="isaiah", email="isaiah@example.com", password="test-pass-123")
		AccountProfile.objects.create(
			user=user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-0100",
		)
		subscriber = NewsletterSubscriber.objects.create(email="isaiah@example.com", is_active=True)

		self.client.login(username="isaiah", password="test-pass-123")
		response = self.client.post(
			reverse("dashboard"),
			{"settings_action": "newsletter", "subscribe_to_newsletter": ""},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(NewsletterSubscriber.objects.filter(pk=subscriber.pk).exists())
		self.assertContains(response, "You have been unsubscribed from newsletter updates.")
