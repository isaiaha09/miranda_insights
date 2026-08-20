from __future__ import annotations

from dateutil.relativedelta import relativedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .audit import record_survey_event
from .codes import generate_survey_code
from .exceptions import InvalidLifecycleTransition, SurveyRetentionProtected
from .models import Survey
from .permissions import require_permission
from .publication import snapshot_with_checksum


CODE_GENERATION_ATTEMPTS = 32


def _create_with_unique_code(**values) -> Survey:
    last_error = None
    for _attempt in range(CODE_GENERATION_ATTEMPTS):
        try:
            with transaction.atomic():
                return Survey.objects.create(access_code=generate_survey_code(), **values)
        except IntegrityError as exc:
            last_error = exc
    raise RuntimeError("Unable to allocate a unique SurveyHQ code.") from last_error


def create_draft(
    *,
    client,
    title,
    reporting_month,
    reporting_year,
    actor,
    project=None,
    description="",
    category="",
    show_client_name_to_participants=False,
    starts_at=None,
    close_mode=Survey.CloseMode.MANUAL,
    ends_at=None,
    source_survey=None,
    source_template=None,
) -> Survey:
    require_permission(actor, "add_survey")
    if client is None:
        raise ValidationError({"client": "A client is required when creating a survey."})
    survey = Survey(
        client=client,
        project=project,
        title=title,
        description=description,
        category=category,
        show_client_name_to_participants=show_client_name_to_participants,
        reporting_month=reporting_month,
        reporting_year=reporting_year,
        starts_at=starts_at,
        close_mode=close_mode,
        ends_at=ends_at,
        source_survey=source_survey,
        source_template=source_template,
        created_by=actor,
        updated_by=actor,
    )
    survey.access_code = generate_survey_code()
    survey.full_clean(validate_unique=False)
    survey = _create_with_unique_code(
        client=client,
        project=project,
        title=title,
        description=description,
        category=category,
        show_client_name_to_participants=show_client_name_to_participants,
        reporting_month=reporting_month,
        reporting_year=reporting_year,
        starts_at=starts_at,
        close_mode=close_mode,
        ends_at=ends_at,
        source_survey=source_survey,
        source_template=source_template,
        created_by=actor,
        updated_by=actor,
    )
    record_survey_event(
        survey=survey,
        actor=actor,
        event_type="survey_created",
        summary=f"Created draft {survey.display_identity}.",
    )
    return survey


def _locked_survey(survey) -> Survey:
    survey_id = survey.pk if isinstance(survey, Survey) else survey
    return Survey.objects.select_for_update().select_related("client", "project").get(pk=survey_id)


@transaction.atomic
def update_draft_metadata(
    survey,
    *,
    actor,
    client,
    title,
    reporting_month,
    reporting_year,
    project=None,
    description="",
    category="",
    show_client_name_to_participants=False,
    starts_at=None,
    close_mode=Survey.CloseMode.MANUAL,
    ends_at=None,
) -> Survey:
    require_permission(actor, "change_survey")
    instance = _locked_survey(survey)
    if instance.status != Survey.Status.DRAFT or instance.published_at:
        raise InvalidLifecycleTransition("Published survey metadata is read-only; duplicate it into a new Draft.")
    instance.client = client
    instance.project = project
    instance.title = title
    instance.description = description
    instance.category = category
    instance.show_client_name_to_participants = show_client_name_to_participants
    instance.reporting_month = reporting_month
    instance.reporting_year = reporting_year
    instance.starts_at = starts_at
    instance.close_mode = close_mode
    instance.ends_at = ends_at
    instance.updated_by = actor
    instance.full_clean()
    instance.save(
        update_fields=[
            "client",
            "project",
            "title",
            "description",
            "category",
            "show_client_name_to_participants",
            "reporting_month",
            "reporting_year",
            "starts_at",
            "close_mode",
            "ends_at",
            "updated_by",
            "updated_at",
        ],
    )
    return instance


@transaction.atomic
def publish_survey(survey, *, actor, at=None) -> Survey:
    require_permission(actor, "publish_survey")
    instance = _locked_survey(survey)
    if instance.status != Survey.Status.DRAFT or instance.published_at:
        raise InvalidLifecycleTransition("Only an unpublished draft can be published.")
    if instance.client_id is None:
        raise ValidationError({"client": "A client is required before publication."})
    instance.full_clean()
    snapshot, checksum = snapshot_with_checksum(instance)
    now = at or timezone.now()
    scheduled = instance.starts_at is not None and instance.starts_at > now
    instance.status = Survey.Status.SCHEDULED if scheduled else Survey.Status.OPEN
    instance.published_at = now
    instance.opened_at = None if scheduled else now
    instance.definition_snapshot = snapshot
    instance.definition_checksum = checksum
    instance.client_name_snapshot = instance.client.organization_name or instance.client.contact_name
    instance.project_name_snapshot = instance.project.name if instance.project_id else ""
    instance.updated_by = actor
    instance.full_clean()
    instance.save(
        update_fields=[
            "status",
            "published_at",
            "opened_at",
            "definition_snapshot",
            "definition_checksum",
            "client_name_snapshot",
            "project_name_snapshot",
            "updated_by",
            "updated_at",
        ],
    )
    record_survey_event(
        survey=instance,
        actor=actor,
        event_type="survey_scheduled" if scheduled else "survey_published",
        summary=("Scheduled" if scheduled else "Published") + f" {instance.display_identity}.",
        metadata={"definition_checksum": checksum},
    )
    return instance


@transaction.atomic
def open_scheduled_survey(survey, *, actor=None, at=None) -> Survey:
    if actor is not None:
        require_permission(actor, "publish_survey")
    instance = _locked_survey(survey)
    now = at or timezone.now()
    if instance.status != Survey.Status.SCHEDULED:
        raise InvalidLifecycleTransition("Only a scheduled survey can be opened this way.")
    if not instance.starts_at or instance.starts_at > now:
        raise InvalidLifecycleTransition("The scheduled start time has not arrived.")
    instance.status = Survey.Status.OPEN
    instance.opened_at = now
    instance.updated_by = actor or instance.updated_by
    instance.save(update_fields=["status", "opened_at", "updated_by", "updated_at"])
    record_survey_event(
        survey=instance,
        actor=actor,
        event_type="survey_opened",
        summary=f"Opened {instance.display_identity}.",
        metadata={"automated": actor is None},
    )
    return instance


@transaction.atomic
def close_survey(survey, *, actor=None, at=None, reason="manual") -> Survey:
    if actor is not None:
        require_permission(actor, "close_survey")
    elif reason != "scheduled":
        raise PermissionDenied("System closure without an actor is limited to scheduled transitions.")
    instance = _locked_survey(survey)
    if instance.status not in {Survey.Status.OPEN, Survey.Status.SCHEDULED}:
        raise InvalidLifecycleTransition("Only an open or scheduled survey can be closed.")
    now = at or timezone.now()
    instance.status = Survey.Status.CLOSED
    instance.closed_at = now
    minimum_retention = now + relativedelta(years=5)
    if instance.retention_until is None or instance.retention_until < minimum_retention:
        instance.retention_until = minimum_retention
    instance.updated_by = actor or instance.updated_by
    instance.save(update_fields=["status", "closed_at", "retention_until", "updated_by", "updated_at"])
    record_survey_event(
        survey=instance,
        actor=actor,
        event_type="survey_closed",
        summary=f"Closed {instance.display_identity}.",
        metadata={"reason": reason, "retention_until": instance.retention_until.isoformat()},
    )
    return instance


@transaction.atomic
def reopen_survey(survey, *, actor, confirmation, clear_expired_end=False, at=None) -> Survey:
    require_permission(actor, "reopen_survey")
    if confirmation is not True:
        raise ValidationError(
            "Reopening continues collection in the existing dataset; explicit confirmation is required."
        )
    instance = _locked_survey(survey)
    if instance.status != Survey.Status.CLOSED:
        raise InvalidLifecycleTransition("Only a closed survey can be reopened.")
    now = at or timezone.now()
    if instance.ends_at and instance.ends_at <= now:
        if not clear_expired_end:
            raise ValidationError({"ends_at": "Clear or replace the expired end time before reopening."})
        instance.ends_at = None
        if instance.close_mode == Survey.CloseMode.SCHEDULED:
            instance.close_mode = Survey.CloseMode.MANUAL
    prior_closed_at = instance.closed_at
    instance.status = Survey.Status.OPEN
    instance.closed_at = None
    instance.archived_at = None
    instance.updated_by = actor
    instance.save(
        update_fields=[
            "status",
            "close_mode",
            "ends_at",
            "closed_at",
            "archived_at",
            "updated_by",
            "updated_at",
        ],
        allow_locked_metadata=True,
    )
    record_survey_event(
        survey=instance,
        actor=actor,
        event_type="survey_reopened",
        summary=f"Exceptionally reopened {instance.display_identity}; collection continues in the existing dataset.",
        metadata={
            "prior_closed_at": prior_closed_at.isoformat() if prior_closed_at else None,
            "retention_until": instance.retention_until.isoformat() if instance.retention_until else None,
        },
    )
    return instance


@transaction.atomic
def archive_survey(survey, *, actor, at=None) -> Survey:
    require_permission(actor, "archive_survey")
    instance = _locked_survey(survey)
    if instance.status != Survey.Status.CLOSED:
        raise InvalidLifecycleTransition("Only a closed survey can be archived.")
    instance.status = Survey.Status.ARCHIVED
    instance.archived_at = at or timezone.now()
    instance.updated_by = actor
    instance.save(update_fields=["status", "archived_at", "updated_by", "updated_at"])
    record_survey_event(
        survey=instance,
        actor=actor,
        event_type="survey_archived",
        summary=f"Archived {instance.display_identity}.",
    )
    return instance


@transaction.atomic
def rotate_access_code(survey, *, actor) -> Survey:
    require_permission(actor, "rotate_survey_code")
    instance = _locked_survey(survey)
    if instance.status in {Survey.Status.CLOSED, Survey.Status.ARCHIVED}:
        raise InvalidLifecycleTransition("Closed or archived survey codes cannot be rotated.")
    previous_code = instance.access_code
    for _attempt in range(CODE_GENERATION_ATTEMPTS):
        instance.access_code = generate_survey_code()
        if instance.access_code == previous_code:
            continue
        try:
            with transaction.atomic():
                instance.save(update_fields=["access_code", "updated_at"])
            break
        except IntegrityError:
            continue
    else:
        raise RuntimeError("Unable to allocate a unique SurveyHQ code.")
    record_survey_event(
        survey=instance,
        actor=actor,
        event_type="survey_code_rotated",
        summary=f"Rotated the participant code for {instance.display_identity}.",
    )
    return instance


@transaction.atomic
def delete_eligible_draft(survey, *, actor):
    require_permission(actor, "delete_eligible_survey")
    instance = _locked_survey(survey)
    if instance.status != Survey.Status.DRAFT or instance.published_at:
        raise SurveyRetentionProtected("Only an unpublished draft can be deleted.")
    if instance.responses.exists() or instance.report_artifacts.exists():
        raise SurveyRetentionProtected("A survey with responses or official reports cannot be deleted.")
    identity = instance.display_identity
    entity_id = instance.pk
    event = record_survey_event(
        survey=instance,
        actor=actor,
        event_type="survey_deleted",
        summary=f"Deleted eligible draft {identity}.",
    )
    for question in instance.questions.all():
        question.choices.all().delete()
        question.matrix_rows.all().delete()
    instance.questions.all().delete()
    instance.delete()
    event.refresh_from_db()
    return entity_id


def synchronize_due_surveys(*, at=None):
    now = at or timezone.now()
    opened = 0
    closed = 0
    scheduled_ids = Survey.objects.filter(status=Survey.Status.SCHEDULED, starts_at__lte=now).values_list(
        "pk", flat=True
    )
    for survey_id in list(scheduled_ids):
        open_scheduled_survey(survey_id, at=now)
        opened += 1
    ending_ids = Survey.objects.filter(
        status=Survey.Status.OPEN,
        close_mode=Survey.CloseMode.SCHEDULED,
        ends_at__lte=now,
    ).values_list("pk", flat=True)
    for survey_id in list(ending_ids):
        close_survey(survey_id, at=now, reason="scheduled")
        closed += 1
    return {"opened": opened, "closed": closed}
