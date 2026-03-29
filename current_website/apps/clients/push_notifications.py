from __future__ import annotations

from django.urls import reverse

from apps.accounts.push_notifications import send_mobile_push_notification_to_user


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

	return send_mobile_push_notification_to_user(
		client_user,
		title=title,
		body=truncate_push_body(body),
		data=data,
	)