from __future__ import annotations

from django.conf import settings
from django.urls import reverse

from apps.accounts.push_notifications import send_mobile_push_notification_to_user
from apps.operations.services import dispatch_push_notification_to_user
from landingpage.emailing import send_templated_email


def truncate_push_body(text: str, *, fallback: str = "Open the client portal to review the latest update.", limit: int = 140) -> str:
	value = " ".join(str(text or "").split())
	if not value:
		return fallback
	if len(value) <= limit:
		return value
	return value[: limit - 3].rstrip() + "..."


def notify_project_client(project, *, title: str, body: str, kind: str = "project_update", extra_data: dict | None = None) -> int:
	client_user = getattr(project.client, "user", None)
	if client_user is None:
		return 0

	data = {
		"kind": kind,
		"routePath": reverse("dashboard"),
		"projectId": project.pk,
	}
	if extra_data:
		data.update(extra_data)

	return dispatch_push_notification_to_user(
		client_user,
		title=title,
		body=truncate_push_body(body),
		data=data,
	)


def email_project_client(project, *, subject: str, heading: str, summary: str, activity_label: str) -> int:
	client_user = getattr(project.client, "user", None)
	recipient = (project.client.contact_email or getattr(client_user, "email", "") or "").strip()
	if not recipient:
		return 0

	portal_url = f"{getattr(settings, 'SITE_URL', 'http://localhost:8000').rstrip('/')}{reverse('dashboard')}"
	return send_templated_email(
		subject=subject,
		to=[recipient],
		template_prefix="project_activity_notification",
		context={
			"email_title": "Client Portal Update",
			"heading": heading,
			"subheading": f"Miranda Insights shared an update for {project.name}.",
			"activity_label": activity_label,
			"project_name": project.name,
			"client_name": project.client.contact_name,
			"summary": summary,
			"portal_url": portal_url,
		},
		from_email=settings.DEFAULT_FROM_EMAIL,
	)
