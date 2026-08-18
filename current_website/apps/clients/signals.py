from __future__ import annotations

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Client, Project, ProjectMessage, ProjectNote, ProjectSubtask
from .push_notifications import email_project_client, notify_project_client, truncate_push_body


def _invalidate_portal_snapshot(client_id):
	if client_id:
		cache.delete(f"portal-snapshot:{client_id}")


@receiver(post_save, sender=Client)
def invalidate_client_snapshot_on_save(sender, instance, **kwargs):
	_invalidate_portal_snapshot(instance.pk)


@receiver(post_delete, sender=Client)
def invalidate_client_snapshot_on_delete(sender, instance, **kwargs):
	_invalidate_portal_snapshot(instance.pk)


@receiver(pre_save, sender=Project)
def capture_previous_project_state(sender, instance, **kwargs):
	if not instance.pk:
		instance._notification_previous_state = None
		return
	instance._notification_previous_state = sender.objects.filter(pk=instance.pk).values("status").first()


@receiver(post_save, sender=Project)
def notify_project_saved(sender, instance, created, **kwargs):
	_invalidate_portal_snapshot(instance.client_id)
	if created:
		notify_project_client(
			instance,
			title="New project available",
			body=f"{instance.name} has been added to your client portal.",
			kind="project_created",
		)
		return

	previous = getattr(instance, "_notification_previous_state", None) or {}
	if not previous:
		return
	update_fields = kwargs.get("update_fields")
	if update_fields is not None and "status" not in update_fields:
		return

	if previous.get("status") != instance.status:
		summary = f"{instance.name} is now marked as {instance.get_status_display()}."
		email_project_client(
			instance,
			subject=f"Project status updated: {instance.name}",
			heading="Project status updated",
			summary=summary,
			activity_label="Status update",
		)
		notify_project_client(
			instance,
			title="Project status updated",
			body=summary,
			kind="project_status_update",
		)


@receiver(pre_save, sender=ProjectSubtask)
def capture_previous_subtask_state(sender, instance, **kwargs):
	if not instance.pk:
		instance._notification_previous_state = None
		return
	instance._notification_previous_state = sender.objects.filter(pk=instance.pk).values("is_completed").first()


@receiver(post_save, sender=ProjectSubtask)
def notify_subtask_saved(sender, instance, created, **kwargs):
	project = instance.project
	_invalidate_portal_snapshot(project.client_id)
	if created:
		return

	previous = getattr(instance, "_notification_previous_state", None) or {}
	if not previous:
		return
	update_fields = kwargs.get("update_fields")
	if update_fields is not None and "is_completed" not in update_fields:
		return

	if not previous.get("is_completed") and instance.is_completed:
		notify_project_client(
			project,
			title="Project progress updated",
			body=f"{instance.title} was marked complete in {project.name}.",
			kind="project_progress_update",
			extra_data={"subtaskId": instance.pk},
		)


@receiver(post_delete, sender=ProjectSubtask)
def invalidate_subtask_snapshot_on_delete(sender, instance, **kwargs):
	_invalidate_portal_snapshot(instance.project.client_id)


@receiver(post_save, sender=ProjectNote)
def notify_project_note_saved(sender, instance, created, **kwargs):
	project = instance.project
	_invalidate_portal_snapshot(project.client_id)
	note_preview = truncate_push_body(instance.content, fallback=f"A new update is available for {project.name}.")
	if created:
		email_project_client(
			project,
			subject=f"New project update: {project.name}",
			heading="New project update posted",
			summary=note_preview,
			activity_label="Project note",
		)
		notify_project_client(
			project,
			title="New project update posted",
			body=note_preview,
			kind="project_note_created",
			extra_data={"noteId": instance.pk},
		)


@receiver(post_delete, sender=ProjectNote)
def invalidate_project_note_snapshot(sender, instance, **kwargs):
	_invalidate_portal_snapshot(instance.project.client_id)


@receiver(post_save, sender=ProjectMessage)
def invalidate_project_message_snapshot(sender, instance, **kwargs):
	_invalidate_portal_snapshot(instance.project.client_id)


@receiver(post_delete, sender=ProjectMessage)
def invalidate_project_message_snapshot_on_delete(sender, instance, **kwargs):
	_invalidate_portal_snapshot(instance.project.client_id)
