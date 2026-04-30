from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from landingpage.emailing import send_templated_email

from .push_notifications import notify_project_client, truncate_push_body


User = get_user_model()


class Client(models.Model):
	user = models.OneToOneField(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="client_record",
	)
	organization_name = models.CharField(max_length=180, blank=True, verbose_name="business/organization name")
	organization_description = models.TextField(blank=True, verbose_name="business/organization description")
	contact_name = models.CharField(max_length=180)
	contact_email = models.EmailField()
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["contact_name", "organization_name"]

	def __str__(self):
		return self.display_name

	@property
	def display_name(self):
		if self.organization_name:
			return f"{self.organization_name} ({self.contact_name})"
		return self.contact_name

	@property
	def active_project_count(self):
		return self.projects.exclude(status=Project.STATUS_COMPLETED).exclude(status=Project.STATUS_CANCELLED).count()


class Project(models.Model):
	CONSULTANT_NAME_MIRANDA_INSIGHTS_TEAM = "Miranda Insights Team"

	STATUS_PENDING = "pending"
	STATUS_IN_PROGRESS = "in_progress"
	STATUS_CANCELLED = "cancelled"
	STATUS_COMPLETED = "completed"
	STATUS_CHOICES = [
		(STATUS_PENDING, "Pending"),
		(STATUS_IN_PROGRESS, "In Progress"),
		(STATUS_CANCELLED, "Cancelled"),
		(STATUS_COMPLETED, "Completed"),
	]

	client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="projects")
	name = models.CharField(max_length=180)
	description = models.TextField(blank=True)
	status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING)
	start_date = models.DateField(null=True, blank=True)
	end_date = models.DateField(null=True, blank=True)
	consultant = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="client_projects",
		limit_choices_to={"is_staff": True},
	)
	consultant_name = models.CharField(max_length=180, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["name"]

	def __str__(self):
		return self.name

	@property
	def completed_subtask_count(self):
		return self.subtasks.filter(is_completed=True).count()

	@property
	def total_subtask_count(self):
		return self.subtasks.count()

	@property
	def progress_percentage(self):
		total = self.total_subtask_count
		if total == 0:
			return 0
		return int((self.completed_subtask_count / total) * 100)

	@property
	def latest_note(self):
		return self.notes.order_by("-created_at").first()

	@property
	def consultant_display(self):
		if self.consultant_id:
			full_name = self.consultant.get_full_name().strip()
			return full_name or self.consultant.username
		if self.consultant_name:
			return self.consultant_name
		return "Unassigned consultant"


class ProjectSubtask(models.Model):
	project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="subtasks")
	title = models.CharField(max_length=180)
	details = models.TextField(blank=True)
	is_completed = models.BooleanField(default=False)
	completed_at = models.DateTimeField(null=True, blank=True)
	completed_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="completed_project_subtasks",
		limit_choices_to={"is_staff": True},
	)
	due_date = models.DateField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["is_completed", "created_at"]
		indexes = [
			models.Index(fields=["project", "is_completed", "due_date", "created_at"], name="clients_pro_project_2677f4_idx"),
		]

	def __str__(self):
		return self.title

	def save(self, *args, **kwargs):
		if self.is_completed and self.completed_at is None:
			self.completed_at = timezone.now()
		if not self.is_completed:
			self.completed_at = None
		super().save(*args, **kwargs)


class ProjectNote(models.Model):
	project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="notes")
	content = models.TextField()
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="project_notes",
		limit_choices_to={"is_staff": True},
	)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]
		indexes = [
			models.Index(fields=["project", "-created_at"], name="clients_pro_project_5d9f3e_idx"),
		]

	def __str__(self):
		return f"Note for {self.project.name}"


class ProjectMessage(models.Model):
	project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="messages")
	sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_messages")
	body = models.TextField(blank=True)
	attachment_file = models.FileField(upload_to="project-message-attachments/%Y/%m/%d/", blank=True)
	attachment_link = models.URLField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["created_at"]
		indexes = [
			models.Index(fields=["project", "-created_at"], name="clients_pro_project_957694_idx"),
		]

	def __str__(self):
		return f"Message on {self.project.name}"

	@property
	def is_staff_message(self):
		return bool(self.sender and self.sender.is_staff)

	@property
	def recipient_email(self):
		if self.is_staff_message:
			return self.project.client.contact_email
		return getattr(settings, "COMPANY_NOTIFICATION_EMAIL", "company@mirandainsights.com")

	@property
	def sender_label(self):
		if self.is_staff_message:
			return self.project.consultant_display
		return self.project.client.contact_name

	@property
	def has_attachment(self):
		return bool(self.attachment_file or self.attachment_link)

	@property
	def attachment_file_name(self):
		if not self.attachment_file:
			return ""
		return self.attachment_file.name.rsplit("/", 1)[-1]

	@property
	def attachment_file_url(self):
		if not self.attachment_file:
			return ""
		base_url = getattr(settings, "SITE_URL", "http://localhost:8000").rstrip("/")
		return f"{base_url}{reverse('project_message_attachment_download', args=[self.pk])}"

	def send_notification(self):
		recipient = (self.recipient_email or "").strip()
		portal_url = f"{getattr(settings, 'SITE_URL', 'http://localhost:8000').rstrip('/')}{reverse('dashboard')}"
		email_count = 0
		if recipient:
			email_count = send_templated_email(
				subject=f"New project message for {self.project.name}",
				to=[recipient],
				template_prefix="project_message_notification",
				context={
					"email_title": "Project Message Notification",
					"heading": f"New message for {self.project.name}",
					"subheading": f"{self.sender_label} sent a new project update.",
					"project_name": self.project.name,
					"client_name": self.project.client.contact_name,
					"sender_name": self.sender_label,
					"message_body": self.body,
					"attachment_file_name": self.attachment_file_name,
					"attachment_file_url": self.attachment_file_url,
					"attachment_link": self.attachment_link,
					"portal_url": portal_url,
				},
				from_email=settings.DEFAULT_FROM_EMAIL,
			)

		push_count = 0
		if self.is_staff_message:
			message_body = truncate_push_body(
				self.body,
				fallback=(
					f"{self.sender_label} shared a new file or update in {self.project.name}."
					if self.has_attachment
					else f"Open {self.project.name} to review the latest consultant reply."
				),
			)
			push_count = notify_project_client(
				self.project,
				title=f"New message from {self.sender_label}",
				body=message_body,
				kind="project_message",
				extra_data={"messageId": self.pk},
			)

		return email_count + push_count


@receiver(post_delete, sender=ProjectMessage)
def delete_project_message_attachment(sender, instance, **kwargs):
	if not instance.attachment_file:
		return
	storage = instance.attachment_file.storage
	name = instance.attachment_file.name
	if name and storage.exists(name):
		storage.delete(name)


def get_or_create_client_for_user(user):
	defaults = {
		"contact_name": user.get_full_name().strip() or user.username,
		"contact_email": user.email or "",
		"organization_name": "",
	}
	client, created = Client.objects.get_or_create(user=user, defaults=defaults)
	updated_fields = []
	contact_name = user.get_full_name().strip() or user.username
	if contact_name and client.contact_name != contact_name:
		client.contact_name = contact_name
		updated_fields.append("contact_name")
	if user.email and client.contact_email != user.email:
		client.contact_email = user.email
		updated_fields.append("contact_email")
	if updated_fields:
		client.save(update_fields=updated_fields + ["updated_at"])
	return client
