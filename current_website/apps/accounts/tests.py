from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.core import mail
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .admin import AccountProfileAdmin, StaffUserAdmin
from .models import AccountDeletionRequest, AccountProfile
from apps.clients.models import Project, ProjectMessage, ProjectSubtask, get_or_create_client_for_user
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
		AccountDeletionRequest.objects.create(
			user=user,
			requested_at=timezone.now() - timedelta(days=8),
			scheduled_for=timezone.now() - timedelta(days=1),
		)

		call_command("purge_scheduled_account_deletions")

		self.assertFalse(User.objects.filter(pk=user.pk).exists())
