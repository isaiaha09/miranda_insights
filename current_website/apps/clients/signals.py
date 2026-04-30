from __future__ import annotations

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Client, Project, ProjectMessage, ProjectNote, ProjectSubtask
from .push_notifications import notify_project_client, truncate_push_body


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
	instance._notification_previous_state = sender.objects.filter(pk=instance.pk).values(
		"name",
		"description",
		"status",
		"start_date",
		"end_date",
		"consultant_id",
		"consultant_name",
	).first()


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

	if previous.get("status") != instance.status:
		notify_project_client(
			instance,
			title="Project status updated",
			body=f"{instance.name} is now marked as {instance.get_status_display()}.",
			kind="project_status_update",
		)
		return

	tracked_fields = (
		"name",
		"description",
		"start_date",
		"end_date",
		"consultant_id",
		"consultant_name",
	)
	if any(previous.get(field_name) != getattr(instance, field_name) for field_name in tracked_fields):
		notify_project_client(
			instance,
			title="Project details updated",
			body=f"{instance.name} has new project details available in your dashboard.",
			kind="project_details_update",
		)


@receiver(pre_save, sender=ProjectSubtask)
def capture_previous_subtask_state(sender, instance, **kwargs):
	if not instance.pk:
		instance._notification_previous_state = None
		return
	instance._notification_previous_state = sender.objects.filter(pk=instance.pk).values(
		"title",
		"details",
		"is_completed",
		"due_date",
	).first()


@receiver(post_save, sender=ProjectSubtask)
def notify_subtask_saved(sender, instance, created, **kwargs):
	project = instance.project
	_invalidate_portal_snapshot(project.client_id)
	if created:
		notify_project_client(
			project,
			title="New project task added",
			body=f"{instance.title} was added to {project.name}.",
			kind="project_subtask_created",
			extra_data={"subtaskId": instance.pk},
		)
		return

	previous = getattr(instance, "_notification_previous_state", None) or {}
	if not previous:
		return

	if not previous.get("is_completed") and instance.is_completed:
		notify_project_client(
			project,
			title="Project progress updated",
			body=f"{instance.title} was marked complete in {project.name}.",
			kind="project_progress_update",
			extra_data={"subtaskId": instance.pk},
		)
		return

	if any(previous.get(field_name) != getattr(instance, field_name) for field_name in ("title", "details", "due_date", "is_completed")):
		notify_project_client(
			project,
			title="Project task updated",
			body=f"{instance.title} was updated in {project.name}.",
			kind="project_subtask_updated",
			extra_data={"subtaskId": instance.pk},
		)


@receiver(post_delete, sender=ProjectSubtask)
def notify_subtask_deleted(sender, instance, **kwargs):
	_invalidate_portal_snapshot(instance.project.client_id)
	notify_project_client(
		instance.project,
		title="Project task removed",
		body=f"{instance.title} was removed from {instance.project.name}.",
		kind="project_subtask_deleted",
	)


@receiver(pre_save, sender=ProjectNote)
def capture_previous_note_state(sender, instance, **kwargs):
	if not instance.pk:
		instance._notification_previous_state = None
		return
	instance._notification_previous_state = sender.objects.filter(pk=instance.pk).values("content").first()


@receiver(post_save, sender=ProjectNote)
def notify_project_note_saved(sender, instance, created, **kwargs):
	project = instance.project
	_invalidate_portal_snapshot(project.client_id)
	note_preview = truncate_push_body(instance.content, fallback=f"A new update is available for {project.name}.")
	if created:
		notify_project_client(
			project,
			title="New project update posted",
			body=note_preview,
			kind="project_note_created",
			extra_data={"noteId": instance.pk},
		)
		return

	previous = getattr(instance, "_notification_previous_state", None) or {}
	if previous.get("content") != instance.content:
		notify_project_client(
			project,
			title="Project update edited",
			body=note_preview,
			kind="project_note_updated",
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