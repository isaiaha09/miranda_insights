from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import os
import re
import tempfile

from apps.accounts.models import AccountProfile
from .admin import ClientAdmin, ProjectAdmin, ProjectMessageAdmin, ProjectNoteInline, ProjectSubtaskInline
from .forms import AdminProjectCreateForm, ProjectMessageForm
from .models import Client, Project, ProjectMessage, ProjectNote, ProjectSubtask, get_or_create_client_for_user
from .workspace import render_client_workspace


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
		self.client_record.organization_description = "A public school district coordinating performance dashboards and reporting rollouts."
		self.client_record.save(update_fields=["organization_name", "organization_description"])
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

	def test_dashboard_project_message_supports_file_and_link_attachments(self):
		self.client.login(username="clientuser", password="client-pass-123")
		attachment = SimpleUploadedFile("project-brief.docx", b"docx attachment content", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

		response = self.client.post(
			reverse("project_chat_widget"),
			{
				"project": self.project.pk,
				"body": "",
				"attachment_link": "https://example.com/dashboard-spec",
				"attachment_file": attachment,
			},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		message = ProjectMessage.objects.get(project=self.project)
		self.assertIn("project-brief", message.attachment_file.name)
		self.assertTrue(message.attachment_file.name.endswith(".docx"))
		self.assertEqual(message.attachment_link, "https://example.com/dashboard-spec")
		self.assertContains(response, "project-brief")
		self.assertContains(response, "Open shared link")
		self.assertIn(message.attachment_file_name, mail.outbox[0].body)
		self.assertIn("https://example.com/dashboard-spec", mail.outbox[0].body)

	def test_project_message_form_accept_attribute_excludes_image_types(self):
		form = ProjectMessageForm(client=self.client_record)

		self.assertEqual(
			form.fields["attachment_file"].widget.attrs["accept"],
			".csv,.doc,.docx,.pdf,.ppt,.pptx,.rtf,.txt,.xls,.xlsx,.zip",
		)

	def test_dashboard_project_message_rejects_photo_uploads(self):
		form = ProjectMessageForm(
			data={
				"project": self.project.pk,
				"body": "",
				"attachment_link": "",
			},
			files={
				"attachment_file": SimpleUploadedFile("phone-photo.jpg", b"jpeg content", content_type="image/jpeg"),
			},
			client=self.client_record,
		)

		self.assertFalse(form.is_valid())
		self.assertIn("Upload a PDF, Office document, text file, ZIP archive, or CSV file.", form.non_field_errors())

	def test_dashboard_chat_widget_filters_messages_to_selected_project(self):
		second_project = Project.objects.create(
			client=self.client_record,
			name="Enrollment Forecast Review",
			status=Project.STATUS_PENDING,
			consultant_name=Project.CONSULTANT_NAME_MIRANDA_INSIGHTS_TEAM,
		)
		ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Message for project one")
		ProjectMessage.objects.create(project=second_project, sender=self.client_user, body="Message for project two")
		self.client.login(username="clientuser", password="client-pass-123")

		response = self.client.get(
			reverse("project_chat_widget"),
			{"project": second_project.pk},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Message for project two")
		self.assertNotContains(response, "Message for project one")

	def test_dashboard_chat_widget_prunes_messages_older_than_seven_days(self):
		expired_message = ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Expired project update")
		recent_message = ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Recent project update")
		ProjectMessage.objects.filter(pk=expired_message.pk).update(created_at=timezone.now() - timedelta(days=8))
		ProjectMessage.objects.filter(pk=recent_message.pk).update(created_at=timezone.now() - timedelta(days=2))
		self.client.login(username="clientuser", password="client-pass-123")

		response = self.client.get(
			reverse("project_chat_widget"),
			{"project": self.project.pk},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(ProjectMessage.objects.filter(pk=expired_message.pk).exists())
		self.assertTrue(ProjectMessage.objects.filter(pk=recent_message.pk).exists())
		self.assertNotContains(response, "Expired project update")
		self.assertContains(response, "Recent project update")

	def test_dashboard_chat_widget_renders_retention_disclaimer_and_mobile_expand_control(self):
		self.client.login(username="clientuser", password="client-pass-123")

		response = self.client.get(
			reverse("project_chat_widget"),
			{"project": self.project.pk},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Messages in this chat automatically delete after 7 days.")
		self.assertContains(response, "data-chat-expand-toggle")

	def test_admin_chat_widget_filters_messages_to_selected_project(self):
		second_project = Project.objects.create(
			client=self.client_record,
			name="Enrollment Forecast Review",
			status=Project.STATUS_PENDING,
			consultant_name=Project.CONSULTANT_NAME_MIRANDA_INSIGHTS_TEAM,
		)
		ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Admin view project one")
		ProjectMessage.objects.create(project=second_project, sender=self.client_user, body="Admin view project two")
		self.client.force_login(self.staff_user)

		response = self.client.get(
			reverse("admin:clients_client_chat_widget", args=[self.client_record.pk]),
			{"project": second_project.pk},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Admin view project two")
		self.assertNotContains(response, "Admin view project one")

	def test_admin_project_message_sends_client_notification(self):
		admin = ProjectMessageAdmin(ProjectMessage, AdminSite())
		request = RequestFactory().post("/admin/clients/projectmessage/add/")
		request.user = self.staff_user
		message = ProjectMessage(project=self.project, sender=self.staff_user, body="The latest dashboard draft is ready for review.", attachment_link="https://example.com/review-draft")

		admin.save_model(request, message, form=None, change=False)

		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ["client@example.com"])
		self.assertIn("The latest dashboard draft is ready for review.", mail.outbox[0].body)
		self.assertIn("https://example.com/review-draft", mail.outbox[0].body)
		self.assertIn("Avery Consultant", mail.outbox[0].body)

	def test_staff_message_uses_project_consultant_display_for_sender_label(self):
		project = Project.objects.create(
			client=self.client_record,
			name="Team-Managed Rollout",
			status=Project.STATUS_IN_PROGRESS,
			consultant_name=Project.CONSULTANT_NAME_MIRANDA_INSIGHTS_TEAM,
		)
		message = ProjectMessage.objects.create(project=project, sender=self.staff_user, body="Team update")

		self.assertEqual(message.sender_label, "Miranda Insights Team")

	def test_custom_consultant_name_is_used_in_staff_message_email_and_widget(self):
		project = Project.objects.create(
			client=self.client_record,
			name="Custom Managed Rollout",
			status=Project.STATUS_IN_PROGRESS,
			consultant_name="KMIR Success Lead",
		)
		message = ProjectMessage.objects.create(project=project, sender=self.staff_user, body="Custom consultant update")
		message.send_notification()
		self.client.login(username="clientuser", password="client-pass-123")

		response = self.client.get(
			reverse("project_chat_widget"),
			{"project": project.pk},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(len(mail.outbox), 1)
		self.assertIn("KMIR Success Lead", mail.outbox[0].body)
		self.assertContains(response, "KMIR Success Lead")

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
		ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Please confirm the revised chart labels.", attachment_link="https://example.com/chart-labels")
		self.client.force_login(self.staff_user)

		response = self.client.get(
			reverse("admin:clients_client_chat_widget", args=[self.client_record.pk]),
			{"project": self.project.pk},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "project-chat-widget__bubble-client")
		self.assertContains(response, "Please confirm the revised chart labels.")
		self.assertContains(response, "Open shared link")

	def test_admin_can_clear_message_log_for_selected_project_only(self):
		second_project = Project.objects.create(
			client=self.client_record,
			name="Enrollment Forecast Review",
			status=Project.STATUS_PENDING,
		)
		ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Primary project message")
		ProjectMessage.objects.create(project=second_project, sender=self.client_user, body="Second project message")
		self.client.force_login(self.staff_user)

		response = self.client.post(
			reverse("admin:clients_client_chat_widget", args=[self.client_record.pk]),
			{
				"project": self.project.pk,
				"chat_action": "clear_project_log",
			},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(ProjectMessage.objects.filter(project=self.project).exists())
		self.assertTrue(ProjectMessage.objects.filter(project=second_project).exists())
		self.assertContains(response, "Cleared 1 message(s) for &#x27;District Performance Dashboard&#x27;.")
		self.assertNotContains(response, "Primary project message")

	def test_clearing_project_message_log_deletes_attachment_files(self):
		self.client.force_login(self.staff_user)
		with tempfile.TemporaryDirectory() as temp_dir:
			with override_settings(MEDIA_ROOT=temp_dir):
				attachment = SimpleUploadedFile("project-brief.docx", b"docx attachment content", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
				message = ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Attached file", attachment_file=attachment)
				file_path = message.attachment_file.path
				self.assertTrue(os.path.exists(file_path))

				response = self.client.post(
					reverse("admin:clients_client_chat_widget", args=[self.client_record.pk]),
					{
						"project": self.project.pk,
						"chat_action": "clear_project_log",
					},
					HTTP_X_REQUESTED_WITH="XMLHttpRequest",
				)

				self.assertEqual(response.status_code, 200)
				self.assertFalse(ProjectMessage.objects.filter(project=self.project).exists())
				self.assertFalse(os.path.exists(file_path))

	def test_client_admin_workspace_and_chat_preview_render_without_error(self):
		ProjectSubtask.objects.create(project=self.project, title="Review export mappings", is_completed=False)
		ProjectMessage.objects.create(project=self.project, sender=self.client_user, body="Can we update the filters on the dashboard?")

		admin = ClientAdmin(Client, AdminSite())
		workspace = admin.projects_workspace(self.client_record)
		chat_preview = admin.client_chat_preview(self.client_record)

		self.assertIn("District Performance Dashboard", workspace)
		self.assertIn("Other", workspace)
		self.assertIn("North Valley School District", workspace)
		self.assertIn("A public school district coordinating performance dashboards and reporting rollouts.", workspace)
		self.assertIn("Open full project editor", workspace)
		self.assertIn("Review export mappings", workspace)
		self.assertIn("Can we update the filters on the dashboard?", chat_preview)

	def test_client_admin_keeps_organization_details_on_change_form_not_list_row(self):
		admin = ClientAdmin(Client, AdminSite())

		self.assertNotIn("organization_name", admin.list_display)
		self.assertIn("organization_name", admin.fields)
		self.assertIn("organization_description", admin.fields)
		self.assertIn("industry_type_display", admin.fields)
		self.assertIn("industry_type_display", admin.readonly_fields)

	def test_hidden_client_admin_models_do_not_show_module_perms(self):
		request = RequestFactory().get("/admin/")
		request.user = self.staff_user

		self.assertEqual(ProjectAdmin(Project, AdminSite()).get_model_perms(request), {})
		self.assertEqual(ProjectMessageAdmin(ProjectMessage, AdminSite()).get_model_perms(request), {})

	def test_get_or_create_client_for_user_reuses_linked_record(self):
		client_record = get_or_create_client_for_user(self.client_user)

		self.assertEqual(client_record.pk, self.client_record.pk)
		self.assertEqual(Client.objects.filter(user=self.client_user).count(), 1)

	def test_client_admin_change_form_renders_valid_workspace_csrf_token(self):
		request = RequestFactory().get(reverse("admin:clients_client_workspace", args=[self.client_record.pk]))
		request.user = self.staff_user

		workspace = render_client_workspace(request, self.client_record)

		match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', workspace)
		self.assertIsNotNone(match)
		token = match.group(1)
		self.assertNotEqual(token, "NOTPROVIDED")
		self.assertIn(len(token), (32, 64))

	def test_client_admin_workspace_create_project_accepts_form_csrf_token_without_header(self):
		csrf_client = self.client_class(enforce_csrf_checks=True)
		csrf_client.force_login(self.staff_user)

		workspace_url = reverse("admin:clients_client_workspace", args=[self.client_record.pk])
		get_response = csrf_client.get(workspace_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

		self.assertEqual(get_response.status_code, 200)
		match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', get_response.content.decode())
		self.assertIsNotNone(match)

		post_response = csrf_client.post(
			workspace_url,
			{
				"csrfmiddlewaretoken": match.group(1),
				"workspace_action": "create_project",
				"name": "CSRF Form Project",
				"status": Project.STATUS_PENDING,
				"start_date": "2025-04-01",
				"end_date": "2025-04-30",
				"consultant_choice": self.staff_user.pk,
				"consultant_custom_name": "",
				"description": "Created through an AJAX form CSRF test.",
			},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(post_response.status_code, 200)
		self.assertTrue(Project.objects.filter(client=self.client_record, name="CSRF Form Project").exists())

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
				"consultant_choice": self.staff_user.pk,
				"consultant_custom_name": "",
				"description": "Launch timeline and onboarding checkpoints.",
			},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		project = Project.objects.get(client=self.client_record, name="Family Engagement Rollout")
		self.assertEqual(project.consultant, self.staff_user)
		self.assertEqual(project.consultant_display, "Avery Consultant")
		self.assertContains(response, "Created project &#x27;Family Engagement Rollout&#x27;.")
		self.assertContains(response, "Family Engagement Rollout")
		self.assertContains(response, "Open full project editor")

	def test_client_admin_workspace_can_create_project_with_miranda_insights_team_consultant(self):
		self.client.force_login(self.staff_user)

		response = self.client.post(
			reverse("admin:clients_client_workspace", args=[self.client_record.pk]),
			{
				"workspace_action": "create_project",
				"name": "Insights Team Rollout",
				"status": Project.STATUS_PENDING,
				"start_date": "2025-05-01",
				"end_date": "2025-05-31",
				"consultant_choice": AdminProjectCreateForm.CONSULTANT_OPTION_MIRANDA_TEAM,
				"consultant_custom_name": "",
				"description": "Team-led implementation plan.",
			},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		project = Project.objects.get(client=self.client_record, name="Insights Team Rollout")
		self.assertIsNone(project.consultant)
		self.assertEqual(project.consultant_name, Project.CONSULTANT_NAME_MIRANDA_INSIGHTS_TEAM)
		self.assertContains(response, "Insights Team Rollout")
		self.assertContains(response, "Open full project editor")
		self.assertContains(response, "Miranda Insights Team")

	def test_client_admin_workspace_can_create_project_with_custom_consultant_name(self):
		self.client.force_login(self.staff_user)

		response = self.client.post(
			reverse("admin:clients_client_workspace", args=[self.client_record.pk]),
			{
				"workspace_action": "create_project",
				"name": "Custom Consultant Rollout",
				"status": Project.STATUS_PENDING,
				"start_date": "2025-06-01",
				"end_date": "2025-06-30",
				"consultant_choice": AdminProjectCreateForm.CONSULTANT_OPTION_CUSTOM_NAME,
				"consultant_custom_name": "KMIR Success Lead",
				"description": "Custom consultant assignment.",
			},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		project = Project.objects.get(client=self.client_record, name="Custom Consultant Rollout")
		self.assertIsNone(project.consultant)
		self.assertEqual(project.consultant_name, "KMIR Success Lead")
		self.assertContains(response, "Custom Consultant Rollout")
		self.assertContains(response, "Open full project editor")
		self.assertContains(response, "KMIR Success Lead")

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
		self.assertContains(response, "Finalize dashboard QA checklist")
		self.assertContains(response, "Open full project editor")

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
		self.assertContains(response, "Client approved the revised scorecard summary copy.")
		self.assertContains(response, "Open full project editor")
