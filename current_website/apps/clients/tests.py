from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import AccountProfile
from .admin import ClientAdmin, ProjectAdmin, ProjectMessageAdmin, ProjectNoteInline, ProjectSubtaskInline
from .models import Client, Project, ProjectMessage, ProjectNote, ProjectSubtask, get_or_create_client_for_user


User = get_user_model()


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	SITE_URL="https://mirandainsights.com",
	COMPANY_NOTIFICATION_EMAIL="company@mirandainsights.com",
)
class ClientProjectTests(TestCase):
	def setUp(self):
		self.staff_user = User.objects.create_user(
			username="consultant",
			email="consultant@example.com",
			password="staff-pass-123",
			is_staff=True,
			first_name="Avery",
			last_name="Consultant",
		)
		self.client_user = User.objects.create_user(
			username="clientuser",
			email="client@example.com",
			password="client-pass-123",
			first_name="Jordan",
			last_name="Client",
		)
		AccountProfile.objects.create(
			user=self.client_user,
			industry_type=AccountProfile.INDUSTRY_OTHER,
			phone_number="555-0110",
		)
		self.client_record = get_or_create_client_for_user(self.client_user)
		self.client_record.organization_name = "North Valley School District"
		self.client_record.save(update_fields=["organization_name"])
		self.project = Project.objects.create(
			client=self.client_record,
			name="District Performance Dashboard",
			status=Project.STATUS_IN_PROGRESS,
			consultant=self.staff_user,
		)

	def test_project_progress_percentage_uses_completed_subtasks(self):
		for index in range(15):
			ProjectSubtask.objects.create(project=self.project, title=f"Task {index + 1}", is_completed=index < 10)

		self.assertEqual(self.project.progress_percentage, 66)

	def test_dashboard_project_message_sends_company_notification(self):
		self.client.login(username="clientuser", password="client-pass-123")

		response = self.client.post(
			reverse("project_chat_widget"),
			{
				"project": self.project.pk,
				"body": "Can we review the dashboard export tomorrow?",
			},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		message = ProjectMessage.objects.get(project=self.project)
		self.assertEqual(message.sender, self.client_user)
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ["company@mirandainsights.com"])
		self.assertIn("Can we review the dashboard export tomorrow?", mail.outbox[0].body)
		response = self.client.get(reverse("dashboard"))
		self.assertContains(response, "project-chat-widget__bubble-client")
		self.assertContains(response, "Can we review the dashboard export tomorrow?")

	def test_admin_project_message_sends_client_notification(self):
		admin = ProjectMessageAdmin(ProjectMessage, AdminSite())
		request = RequestFactory().post("/admin/clients/projectmessage/add/")
		request.user = self.staff_user
		message = ProjectMessage(project=self.project, sender=self.staff_user, body="The latest dashboard draft is ready for review.")

		admin.save_model(request, message, form=None, change=False)

		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ["client@example.com"])
		self.assertIn("The latest dashboard draft is ready for review.", mail.outbox[0].body)

	def test_project_admin_editor_excludes_chat_preview(self):
		ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Can we update the filters on the dashboard?")
		ProjectMessage.objects.create(project=self.project, sender=self.staff_user, body="Yes, I will send a revision this afternoon.")

		admin = ProjectAdmin(Project, AdminSite())

		self.assertNotIn("chat_thread_preview", admin.get_fields(request=None, obj=self.project))
		self.assertEqual([inline.model for inline in admin.get_inlines(request=None, obj=self.project)], [ProjectSubtask, ProjectNote])

	def test_project_subtask_inline_exposes_details_and_delete(self):
		inline = ProjectSubtaskInline(Project, AdminSite())

		self.assertIn("details", inline.fields)
		self.assertTrue(inline.can_delete)

	def test_project_note_inline_is_compact_and_deletable(self):
		inline = ProjectNoteInline(Project, AdminSite())

		self.assertIn("content", inline.fields)
		self.assertTrue(inline.can_delete)

	def test_admin_client_chat_widget_endpoint_returns_shared_thread(self):
		ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Please confirm the revised chart labels.")
		self.client.force_login(self.staff_user)

		response = self.client.get(
			reverse("admin:clients_client_chat_widget", args=[self.client_record.pk]),
			{"project": self.project.pk},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "project-chat-widget__bubble-client")
		self.assertContains(response, "Please confirm the revised chart labels.")

	def test_client_admin_workspace_and_chat_preview_render_without_error(self):
		ProjectSubtask.objects.create(project=self.project, title="Review export mappings", is_completed=False)
		ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Can we update the filters on the dashboard?")

		admin = ClientAdmin(Client, AdminSite())
		workspace = admin.projects_workspace(self.client_record)
		chat_preview = admin.client_chat_preview(self.client_record)

		self.assertIn("District Performance Dashboard", workspace)
		self.assertIn("Open full project editor", workspace)
		self.assertIn("Review export mappings", workspace)
		self.assertIn("Can we update the filters on the dashboard?", chat_preview)

	def test_hidden_client_admin_models_do_not_show_module_perms(self):
		request = RequestFactory().get("/admin/")
		request.user = self.staff_user

		self.assertEqual(ProjectAdmin(Project, AdminSite()).get_model_perms(request), {})
		self.assertEqual(ProjectMessageAdmin(ProjectMessage, AdminSite()).get_model_perms(request), {})

	def test_get_or_create_client_for_user_reuses_linked_record(self):
		client_record = get_or_create_client_for_user(self.client_user)

		self.assertEqual(client_record.pk, self.client_record.pk)
		self.assertEqual(Client.objects.filter(user=self.client_user).count(), 1)

	def test_client_admin_workspace_can_create_project(self):
		self.client.force_login(self.staff_user)

		response = self.client.post(
			reverse("admin:clients_client_workspace", args=[self.client_record.pk]),
			{
				"workspace_action": "create_project",
				"name": "Family Engagement Rollout",
				"status": Project.STATUS_PENDING,
				"start_date": "2025-04-01",
				"end_date": "2025-04-30",
				"consultant": self.staff_user.pk,
				"description": "Launch timeline and onboarding checkpoints.",
			},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		project = Project.objects.get(client=self.client_record, name="Family Engagement Rollout")
		self.assertEqual(project.consultant, self.staff_user)
		self.assertContains(response, "Created project &#x27;Family Engagement Rollout&#x27;.")

	def test_client_admin_workspace_can_add_subtask(self):
		self.client.force_login(self.staff_user)

		response = self.client.post(
			reverse("admin:clients_client_workspace", args=[self.client_record.pk]),
			{
				"workspace_action": "add_subtask",
				"subtask-project": self.project.pk,
				"subtask-title": "Finalize dashboard QA checklist",
				"subtask-details": "Verify chart labels and CSV export names.",
				"subtask-due_date": "2025-04-10",
				"subtask-is_completed": "on",
			},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		subtask = ProjectSubtask.objects.get(project=self.project, title="Finalize dashboard QA checklist")
		self.assertTrue(subtask.is_completed)
		self.assertEqual(subtask.completed_by, self.staff_user)
		self.assertContains(response, "Added a subtask to &#x27;District Performance Dashboard&#x27;.")

	def test_client_admin_workspace_can_add_note(self):
		self.client.force_login(self.staff_user)

		response = self.client.post(
			reverse("admin:clients_client_workspace", args=[self.client_record.pk]),
			{
				"workspace_action": "add_note",
				"note-project": self.project.pk,
				"note-content": "Client approved the revised scorecard summary copy.",
			},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		note = ProjectNote.objects.get(project=self.project)
		self.assertEqual(note.created_by, self.staff_user)
		self.assertEqual(note.content, "Client approved the revised scorecard summary copy.")
		self.assertContains(response, "Added a note to &#x27;District Performance Dashboard&#x27;.")
