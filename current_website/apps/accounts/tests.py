from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.core import mail
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from .admin import AccountProfileAdmin, StaffUserAdmin
from .models import AccountDeletionRequest, AccountProfile
from apps.clients.models import Client, Project, ProjectMessage, ProjectSubtask, get_or_create_client_for_user
from apps.news.models import NewsletterSubscriber


User = get_user_model()


class LoginViewTests(TestCase):
	def test_admin_login_uses_portal_style_template(self):
		response = self.client.get(reverse("admin:login"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Admin Portal")
		self.assertContains(response, "Miranda Insights management workspace")
		self.assertContains(response, "id=\"login-form\"", html=False)

	@override_settings(TURNSTILE_SITE_KEY="", TURNSTILE_SECRET_KEY="")
	def test_signup_creates_client_business_profile_fields(self):
		response = self.client.post(
			reverse("signup"),
			{
				"first_name": "Timmy",
				"last_name": "Timmons",
				"organization_name": "Timmons Advisory Group",
				"organization_description": "A consulting firm focused on analytics strategy for district leaders.",
				"industry_type": AccountProfile.INDUSTRY_INDIVIDUAL,
				"phone_number": "8058271393",
				"email": "emailtestappworks@gmail.com",
				"username": "emailtestappworks@gmail.com",
				"password1": "SecurePortal!8472",
				"password2": "SecurePortal!8472",
				"agree_to_terms": "on",
			},
		)

		self.assertEqual(response.status_code, 302)
		user = User.objects.get(username="emailtestappworks@gmail.com")
		client_record = user.client_record
		self.assertEqual(client_record.organization_name, "Timmons Advisory Group")
		self.assertEqual(client_record.organization_description, "A consulting firm focused on analytics strategy for district leaders.")

	def test_login_shows_incorrect_credentials_message(self):
		User.objects.create_user(username="isaiah", email="isaiah@example.com", password="correct-pass-123")

		response = self.client.post(
			reverse("login"),
			{"username": "isaiah", "password": "wrong-pass"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Incorrect username or password.")

	def test_login_recovers_account_scheduled_for_deletion(self):
		user = User.objects.create_user(username="recoverme", email="recover@example.com", password="correct-pass-123")
		AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-0200")
		AccountDeletionRequest.schedule_for_user(user, reference_time=timezone.now())

		response = self.client.post(
			reverse("login"),
			{"username": "recoverme", "password": "correct-pass-123"},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(AccountDeletionRequest.objects.filter(user=user).exists())
		self.assertContains(response, "Your scheduled account deletion has been canceled. All account data has been restored.")

	def test_pwa_login_redirects_staff_user_to_admin_index(self):
		staff_user = User.objects.create_user(
			username="pwaadmin",
			email="pwaadmin@example.com",
			password="correct-pass-123",
			is_staff=True,
		)

		response = self.client.post(
			reverse("login"),
			{"username": "pwaadmin", "password": "correct-pass-123", "pwa_mode": "1"},
		)

		self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)
		self.assertEqual(int(self.client.session.get("_auth_user_id")), staff_user.pk)

	def test_staff_login_redirects_to_admin_index_even_without_pwa_flag(self):
		User.objects.create_user(
			username="browseradmin",
			email="browseradmin@example.com",
			password="correct-pass-123",
			is_staff=True,
		)

		response = self.client.post(
			reverse("login"),
			{"username": "browseradmin", "password": "correct-pass-123", "pwa_mode": "0"},
		)

		self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)

	@patch("apps.accounts.views.verify_totp", return_value=True)
	def test_pwa_staff_login_with_2fa_redirects_to_admin_index(self, mocked_verify_totp):
		staff_user = User.objects.create_user(
			username="pwaadmin2fa",
			email="pwaadmin2fa@example.com",
			password="correct-pass-123",
			is_staff=True,
		)
		AccountProfile.objects.create(
			user=staff_user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-0203",
			two_factor_enabled=True,
			two_factor_secret="BASE32SECRET",
		)

		login_response = self.client.post(
			reverse("login"),
			{"username": "pwaadmin2fa", "password": "correct-pass-123", "pwa_mode": "1"},
		)

		self.assertRedirects(login_response, reverse("login_2fa"), fetch_redirect_response=False)

		two_factor_response = self.client.post(
			reverse("login_2fa"),
			{"otp_code": "123456"},
		)

		self.assertRedirects(two_factor_response, reverse("admin:index"), fetch_redirect_response=False)
		self.assertTrue(mocked_verify_totp.called)

	def test_dashboard_redirects_staff_users_to_admin_index(self):
		staff_user = User.objects.create_user(
			username="dashadmin",
			email="dashadmin@example.com",
			password="correct-pass-123",
			is_staff=True,
		)

		self.client.force_login(staff_user)
		response = self.client.get(reverse("dashboard"))

		self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)

	@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
	def test_password_reset_view_sends_branded_email(self):
		user = User.objects.create_user(username="browserreset", email="browserreset@example.com", password="correct-pass-123")
		AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-0204")

		response = self.client.post(reverse("password_reset"), {"email": "browserreset@example.com"}, follow=False)

		self.assertRedirects(response, reverse("password_reset_done"), fetch_redirect_response=False)
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ["browserreset@example.com"])
		self.assertTrue(mail.outbox[0].alternatives)
		html_body = mail.outbox[0].alternatives[0][0]
		self.assertIn("Reset Your Password", html_body)
		self.assertIn("Miranda Insights", html_body)

	@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
	def test_recover_username_view_sends_username_email(self):
		User.objects.create_user(username="browserrecover", email="browserrecover@example.com", password="correct-pass-123")

		response = self.client.post(reverse("recover_username"), {"email": "browserrecover@example.com"}, follow=False)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "If an account exists for browserrecover@example.com")
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ["browserrecover@example.com"])
		self.assertIn("browserrecover", mail.outbox[0].body)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MobileAuthApiTests(TestCase):
	def test_mobile_login_api_returns_session_bridge_url(self):
		user = User.objects.create_user(username="mobileuser", email="mobile@example.com", password="correct-pass-123")
		AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-1200")

		response = self.client.post(
			reverse("mobile_login_api"),
			data="{\"username\": \"mobileuser\", \"password\": \"correct-pass-123\"}",
			content_type="application/json",
		)

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertTrue(payload["ok"])
		self.assertIn(reverse("mobile_session_login"), payload["sessionUrl"])

	def test_mobile_login_api_includes_remember_me_flag(self):
		user = User.objects.create_user(username="remembermobile", email="remember@example.com", password="correct-pass-123")
		AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-1209")

		response = self.client.post(
			reverse("mobile_login_api"),
			data='{"username": "remembermobile", "password": "correct-pass-123", "rememberMe": true}',
			content_type="application/json",
		)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.json()["rememberMe"])

	@override_settings(MOBILE_APP_REMEMBER_ME_SESSION_AGE=86400)
	def test_mobile_session_login_logs_user_in(self):
		user = User.objects.create_user(username="bridgeuser", email="bridge@example.com", password="correct-pass-123")
		AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-1201")

		api_response = self.client.post(
			reverse("mobile_login_api"),
			data="{\"username\": \"bridgeuser\", \"password\": \"correct-pass-123\", \"rememberMe\": true}",
			content_type="application/json",
		)
		payload = api_response.json()
		session_response = self.client.get(payload["sessionUrl"], follow=False)

		self.assertEqual(session_response.status_code, 302)
		self.assertEqual(int(self.client.session.get("_auth_user_id")), user.pk)
		self.assertFalse(self.client.session.get_expire_at_browser_close())
		self.assertGreaterEqual(self.client.session.get_expiry_age(), 86000)

	def test_mobile_session_login_without_remember_me_expires_at_browser_close(self):
		user = User.objects.create_user(username="sessionmobile", email="session@example.com", password="correct-pass-123")
		AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-1210")

		api_response = self.client.post(
			reverse("mobile_login_api"),
			data="{\"username\": \"sessionmobile\", \"password\": \"correct-pass-123\", \"rememberMe\": false}",
			content_type="application/json",
		)
		payload = api_response.json()
		session_response = self.client.get(payload["sessionUrl"], follow=False)

		self.assertEqual(session_response.status_code, 302)
		self.assertTrue(self.client.session.get_expire_at_browser_close())

	@patch("apps.accounts.views.verify_totp", return_value=False)
	def test_mobile_login_api_requires_valid_2fa_code(self, mocked_verify_totp):
		user = User.objects.create_user(username="mobile2fa", email="mobile2fa@example.com", password="correct-pass-123")
		AccountProfile.objects.create(
			user=user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-1202",
			two_factor_enabled=True,
			two_factor_secret="BASE32SECRET",
		)

		response = self.client.post(
			reverse("mobile_login_api"),
			data="{\"username\": \"mobile2fa\", \"password\": \"correct-pass-123\"}",
			content_type="application/json",
		)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.json()["requiresTwoFactor"])
		self.assertFalse(mocked_verify_totp.called)

	def test_mobile_recover_username_api_sends_matching_email(self):
		User.objects.create_user(username="recovermobile", email="recovermobile@example.com", password="correct-pass-123")

		response = self.client.post(
			reverse("mobile_recover_username_api"),
			data="{\"email\": \"recovermobile@example.com\"}",
			content_type="application/json",
		)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.json()["ok"])
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ["recovermobile@example.com"])

	def test_mobile_password_reset_api_sends_reset_email(self):
		user = User.objects.create_user(username="resetmobile", email="resetmobile@example.com", password="correct-pass-123")
		AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-1203")

		response = self.client.post(
			reverse("mobile_password_reset_api"),
			data="{\"email\": \"resetmobile@example.com\"}",
			content_type="application/json",
		)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.json()["ok"])
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ["resetmobile@example.com"])


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

	def test_account_profile_admin_shows_pending_deletion_state(self):
		user = User.objects.create_user(username="pendingadmin", email="pending@example.com", password="test-pass-123")
		profile = AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-0201")
		deletion_request = AccountDeletionRequest.schedule_for_user(user, reference_time=timezone.now())

		admin_instance = AccountProfileAdmin(AccountProfile, AdminSite())

		self.assertEqual(admin_instance.account_deletion_status(profile), "Scheduled")
		self.assertEqual(admin_instance.account_deletion_scheduled_for(profile), deletion_request.scheduled_for)

	@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
	def test_account_profile_admin_delete_removes_email_linked_data_and_preserves_subscriber(self):
		user = User.objects.create_user(username="admindelete", email="admindelete@example.com", password="test-pass-123")
		profile = AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-0202")
		linked_client = get_or_create_client_for_user(user)
		Project.objects.create(client=linked_client, name="Main Portal Project", status=Project.STATUS_IN_PROGRESS)
		email_only_client = Client.objects.create(
			contact_name="Same Email Client",
			contact_email="admindelete@example.com",
			organization_name="Miranda Insights Test",
		)
		NewsletterSubscriber.objects.create(email="admindelete@example.com", is_active=True)

		admin_instance = AccountProfileAdmin(AccountProfile, AdminSite())
		request = RequestFactory().post("/admin/accounts/accountprofile/")

		admin_instance.delete_model(request, profile)

		self.assertFalse(User.objects.filter(pk=user.pk).exists())
		self.assertFalse(AccountProfile.objects.filter(pk=profile.pk).exists())
		self.assertFalse(Client.objects.filter(pk=linked_client.pk).exists())
		self.assertFalse(Client.objects.filter(pk=email_only_client.pk).exists())
		self.assertTrue(NewsletterSubscriber.objects.filter(email="admindelete@example.com", is_active=True).exists())
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ["admindelete@example.com"])
		self.assertIn("successfully deleted", mail.outbox[0].body)


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	SITE_URL="https://mirandainsights.com",
)
class DashboardNewsletterPreferenceTests(TestCase):
	def test_dashboard_get_handles_missing_account_profile(self):
		user = User.objects.create_user(username="noprof", email="noprof@example.com", password="test-pass-123")

		self.client.login(username="noprof", password="test-pass-123")
		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Portal Settings")
		self.assertContains(response, "2FA not enabled")
		self.assertContains(response, "Review account deletion")

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

	def test_dashboard_can_update_client_business_profile(self):
		user = User.objects.create_user(username="bizowner", email="bizowner@example.com", password="test-pass-123")
		profile = AccountProfile.objects.create(
			user=user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-0108",
		)
		client_record = get_or_create_client_for_user(user)

		self.client.login(username="bizowner", password="test-pass-123")
		response = self.client.post(
			reverse("dashboard"),
			{
				"settings_action": "client_profile",
				"industry_type": AccountProfile.INDUSTRY_EDUCATION,
				"organization_name": "Miranda Insights Partner District",
				"organization_description": "A district leadership team coordinating reporting, deliverables, and ongoing analytics support.",
			},
			follow=True,
		)

		client_record.refresh_from_db()
		profile.refresh_from_db()
		self.assertEqual(response.status_code, 200)
		self.assertEqual(profile.industry_type, AccountProfile.INDUSTRY_EDUCATION)
		self.assertEqual(client_record.organization_name, "Miranda Insights Partner District")
		self.assertEqual(client_record.organization_description, "A district leadership team coordinating reporting, deliverables, and ongoing analytics support.")
		self.assertContains(response, "Your business profile has been updated.")
		self.assertContains(response, "Miranda Insights Partner District")
		self.assertContains(response, "Educational Institution")

	def test_delete_account_page_shows_project_and_message_log_data(self):
		user = User.objects.create_user(username="deletecheck", email="deletecheck@example.com", password="test-pass-123")
		AccountProfile.objects.create(
			user=user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-0101",
			two_factor_enabled=True,
			two_factor_secret="BASE32SECRET",
		)
		NewsletterSubscriber.objects.create(email="deletecheck@example.com", is_active=True)
		client_record = get_or_create_client_for_user(user)
		project = Project.objects.create(
			client=client_record,
			name="District Performance Dashboard",
			status=Project.STATUS_IN_PROGRESS,
		)
		for index in range(15):
			ProjectSubtask.objects.create(project=project, title=f"Task {index + 1}", is_completed=index < 10)
		ProjectMessage.objects.create(project=project, sender=user, body="Support follow-up")

		self.client.login(username="deletecheck", password="test-pass-123")
		response = self.client.get(reverse("delete_account"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "District Performance Dashboard")
		self.assertContains(response, "66%")
		self.assertContains(response, "Support follow-up")
		self.assertContains(response, "Your newsletter subscription will stay active unless you unsubscribe separately.")

	def test_dashboard_shows_subtask_details_for_client_projects(self):
		user = User.objects.create_user(username="dashsubtasks", email="dashsubtasks@example.com", password="test-pass-123")
		AccountProfile.objects.create(
			user=user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-0105",
		)
		client_record = get_or_create_client_for_user(user)
		project = Project.objects.create(
			client=client_record,
			name="District Performance Dashboard",
			status=Project.STATUS_IN_PROGRESS,
		)
		ProjectSubtask.objects.create(
			project=project,
			title="Finalize rollout checklist",
			details="Confirm milestone owners and update the export naming guide.",
		)

		self.client.login(username="dashsubtasks", password="test-pass-123")
		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Finalize rollout checklist")
		self.assertContains(response, "Confirm milestone owners and update the export naming guide.")

	def test_dashboard_progress_updates_include_completed_subtasks_and_notes(self):
		user = User.objects.create_user(username="dashupdates", email="dashupdates@example.com", password="test-pass-123")
		AccountProfile.objects.create(
			user=user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-0106",
		)
		client_record = get_or_create_client_for_user(user)
		project = Project.objects.create(
			client=client_record,
			name="District Performance Dashboard",
			status=Project.STATUS_IN_PROGRESS,
		)
		ProjectSubtask.objects.create(
			project=project,
			title="Finalize rollout checklist",
			details="Confirm milestone owners and update the export naming guide.",
			is_completed=True,
		)
		from apps.clients.models import ProjectNote
		ProjectNote.objects.create(project=project, content="Client approved the updated benchmark group labels.")

		self.client.login(username="dashupdates", password="test-pass-123")
		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Completed subtask")
		self.assertNotContains(response, "Project note")

	def test_dashboard_reports_show_latest_note_and_past_notes_per_project(self):
		user = User.objects.create_user(username="dashreports", email="dashreports@example.com", password="test-pass-123")
		AccountProfile.objects.create(
			user=user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-0107",
		)
		client_record = get_or_create_client_for_user(user)
		project = Project.objects.create(
			client=client_record,
			name="District Performance Dashboard",
			status=Project.STATUS_IN_PROGRESS,
		)
		from apps.clients.models import ProjectNote
		ProjectNote.objects.create(project=project, content="Original note for the dashboard rollout.")
		ProjectNote.objects.create(project=project, content="Most recent note for the dashboard rollout.")

		self.client.login(username="dashreports", password="test-pass-123")
		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Most recent note for the dashboard rollout.")
		self.assertContains(response, "Show past notes")
		self.assertContains(response, "Original note for the dashboard rollout.")

	def test_delete_account_requires_current_password(self):
		user = User.objects.create_user(username="deletebad", email="deletebad@example.com", password="test-pass-123")
		AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-0103")

		self.client.login(username="deletebad", password="test-pass-123")
		response = self.client.post(
			reverse("delete_account"),
			{"password": "wrong-pass"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(AccountDeletionRequest.objects.filter(user=user).exists())
		self.assertContains(response, "Enter your current password to confirm account deletion.")

	def test_delete_account_schedules_deletion_and_preserves_data(self):
		user = User.objects.create_user(username="deleteok", email="deleteok@example.com", password="test-pass-123")
		profile = AccountProfile.objects.create(
			user=user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-0102",
		)
		subscriber = NewsletterSubscriber.objects.create(email="deleteok@example.com", is_active=True)

		self.client.login(username="deleteok", password="test-pass-123")
		response = self.client.post(
			reverse("delete_account"),
			{"password": "test-pass-123"},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		deletion_request = AccountDeletionRequest.objects.get(user=user)
		self.assertTrue(User.objects.filter(pk=user.pk).exists())
		self.assertTrue(AccountProfile.objects.filter(pk=profile.pk).exists())
		self.assertTrue(NewsletterSubscriber.objects.filter(pk=subscriber.pk).exists())
		self.assertGreater(deletion_request.scheduled_for, deletion_request.requested_at)
		self.assertContains(response, "Your account is scheduled for deletion in 7 days.")
		self.assertEqual(len(mail.outbox), 1)
		message = mail.outbox[0]
		self.assertEqual(message.to, ["deleteok@example.com"])
		self.assertIn("You have 7 days to recover your account by logging back in.", message.body)
		self.assertIn("https://mirandainsights.com/login/", message.body)

	def test_purge_scheduled_account_deletions_removes_expired_accounts(self):
		user = User.objects.create_user(username="expireddelete", email="expired@example.com", password="test-pass-123")
		AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-0104")
		client_record = get_or_create_client_for_user(user)
		Project.objects.create(client=client_record, name="Cleanup Project", status=Project.STATUS_IN_PROGRESS)
		NewsletterSubscriber.objects.create(email="expired@example.com", is_active=True)
		AccountDeletionRequest.objects.create(
			user=user,
			requested_at=timezone.now() - timedelta(days=8),
			scheduled_for=timezone.now() - timedelta(days=1),
		)

		call_command("purge_scheduled_account_deletions")

		self.assertFalse(User.objects.filter(pk=user.pk).exists())
		self.assertFalse(Client.objects.filter(pk=client_record.pk).exists())
		self.assertFalse(AccountDeletionRequest.objects.filter(user_id=user.pk).exists())
		self.assertTrue(NewsletterSubscriber.objects.filter(email="expired@example.com", is_active=True).exists())
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ["expired@example.com"])
		self.assertIn("successfully deleted", mail.outbox[0].body)


@override_settings(LOGIN_RATE_LIMIT="1/1h")
class LoginThrottleTests(TestCase):
	def test_login_rate_limit_returns_429_after_limit(self):
		User.objects.create_user(username="ratelimited", email="ratelimited@example.com", password="correct-pass-123")

		first_response = self.client.post(
			reverse("login"),
			{"username": "ratelimited", "password": "wrong-pass"},
			secure=True,
		)
		second_response = self.client.post(
			reverse("login"),
			{"username": "ratelimited", "password": "wrong-pass"},
			secure=True,
		)

		self.assertEqual(first_response.status_code, 200)
		self.assertEqual(second_response.status_code, 429)
		self.assertContains(second_response, "Too many sign-in attempts. Please wait and try again.", status_code=429)
		self.assertGreater(int(second_response["Retry-After"]), 0)
		self.assertLessEqual(int(second_response["Retry-After"]), 3600)


@override_settings(LOGIN_RATE_LIMIT="1/1h")
class MobileLoginThrottleTests(TestCase):
	def test_mobile_login_api_rate_limit_returns_429_after_limit(self):
		user = User.objects.create_user(username="mobilelimit", email="mobilelimit@example.com", password="correct-pass-123")
		AccountProfile.objects.create(user=user, industry_type=AccountProfile.INDUSTRY_OTHER, phone_number="555-1300")

		first_response = self.client.post(
			reverse("mobile_login_api"),
			data='{"username": "mobilelimit", "password": "wrong-pass"}',
			content_type="application/json",
			secure=True,
		)
		second_response = self.client.post(
			reverse("mobile_login_api"),
			data='{"username": "mobilelimit", "password": "wrong-pass"}',
			content_type="application/json",
			secure=True,
		)

		self.assertEqual(first_response.status_code, 400)
		self.assertEqual(second_response.status_code, 429)
		self.assertEqual(second_response.json()["message"], "Too many sign-in attempts. Please wait and try again.")
		self.assertGreater(int(second_response["Retry-After"]), 0)
		self.assertLessEqual(int(second_response["Retry-After"]), 3600)
