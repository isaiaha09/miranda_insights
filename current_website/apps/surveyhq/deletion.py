from __future__ import annotations

import hashlib
import logging
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction

from .audit import record_survey_event
from .exceptions import SurveyRetentionProtected
from .models import (
    Survey,
    SurveyAnswer,
    SurveyAnswerSelection,
    SurveyChoice,
    SurveyMatrixRow,
    SurveyQuestion,
    SurveyReportArtifact,
    SurveyResponse,
    SurveyTemplate,
)
from .permissions import require_permission


logger = logging.getLogger(__name__)


def _template_references_image(file_name: str) -> bool:
    for definition in SurveyTemplate.objects.values_list("definition", flat=True).iterator():
        for question in (definition or {}).get("questions", []):
            image = question.get("image") or {}
            if image.get("file") == file_name:
                return True
    return False


def _cleanup_files(file_candidates):
    grouped = defaultdict(set)
    for kind, storage, file_name in file_candidates:
        if file_name:
            grouped[(kind, storage)].add(file_name)

    for (kind, storage), file_names in grouped.items():
        for file_name in file_names:
            if kind == "question_image":
                still_referenced = (
                    SurveyQuestion._base_manager.filter(image=file_name).exists()
                    or _template_references_image(file_name)
                )
            else:
                still_referenced = SurveyReportArtifact._base_manager.filter(file=file_name).exists()
            if still_referenced:
                continue
            try:
                storage.delete(file_name)
            except Exception:  # pragma: no cover - storage providers fail outside the DB transaction
                logger.exception(
                    "SurveyHQ media cleanup failed after permanent Survey deletion.",
                    extra={
                        "surveyhq_media_kind": kind,
                        "surveyhq_file_reference": hashlib.sha256(file_name.encode("utf-8")).hexdigest()[:16],
                    },
                )


def _delete_database_records(*, instance, response_ids, answer_ids, question_ids):
    SurveyAnswerSelection._base_manager.filter(answer_id__in=answer_ids).delete()
    SurveyAnswer._base_manager.filter(pk__in=answer_ids).delete()
    SurveyResponse._base_manager.filter(pk__in=response_ids).delete()
    SurveyReportArtifact._base_manager.filter(survey=instance).delete()
    SurveyChoice._base_manager.filter(question_id__in=question_ids).delete()
    SurveyMatrixRow._base_manager.filter(question_id__in=question_ids).delete()
    SurveyQuestion._base_manager.filter(pk__in=question_ids).delete()
    Survey._base_manager.filter(pk=instance.pk).delete()


@transaction.atomic
def permanently_delete_survey(survey, *, actor, confirmation, reason):
    require_permission(actor, "permanently_delete_survey")
    if confirmation != "DELETE":
        raise ValidationError('Type "DELETE" exactly to confirm permanent deletion.')
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A deletion reason is required.")

    survey_id = survey.pk if isinstance(survey, Survey) else survey
    instance = (
        Survey.objects.select_for_update(of=("self",))
        .select_related("client", "project")
        .get(pk=survey_id)
    )
    if instance.status == Survey.Status.DRAFT and not instance.published_at:
        raise SurveyRetentionProtected("Use the eligible Draft deletion workflow for unpublished Drafts.")

    response_ids = SurveyResponse._base_manager.filter(survey=instance).values_list("pk", flat=True)
    answer_ids = SurveyAnswer._base_manager.filter(response_id__in=response_ids).values_list("pk", flat=True)
    question_ids = SurveyQuestion._base_manager.filter(survey=instance).values_list("pk", flat=True)

    counts = {
        "responses": SurveyResponse._base_manager.filter(pk__in=response_ids).count(),
        "answers": SurveyAnswer._base_manager.filter(pk__in=answer_ids).count(),
        "selections": SurveyAnswerSelection._base_manager.filter(answer_id__in=answer_ids).count(),
        "reports": SurveyReportArtifact._base_manager.filter(survey=instance).count(),
        "questions": SurveyQuestion._base_manager.filter(pk__in=question_ids).count(),
        "choices": SurveyChoice._base_manager.filter(question_id__in=question_ids).count(),
        "matrix_rows": SurveyMatrixRow._base_manager.filter(question_id__in=question_ids).count(),
    }

    file_candidates = []
    for question in SurveyQuestion._base_manager.filter(pk__in=question_ids).only("image"):
        if question.image:
            file_candidates.append(("question_image", question.image.storage, question.image.name))
    for artifact in SurveyReportArtifact._base_manager.filter(survey=instance).only("file"):
        if artifact.file:
            file_candidates.append(("report", artifact.file.storage, artifact.file.name))

    entity_id = instance.pk
    identity = instance.display_identity
    record_survey_event(
        survey=instance,
        actor=actor,
        event_type="survey_permanently_deleted",
        summary=f"Permanently deleted {identity}.",
        metadata={
            "survey_id": str(instance.pk),
            "client_identity": instance.identity_client_name,
            "status": instance.status,
            "reason": reason,
            "retention_until": instance.retention_until.isoformat() if instance.retention_until else None,
            "deleted_counts": counts,
        },
    )

    _delete_database_records(
        instance=instance,
        response_ids=response_ids,
        answer_ids=answer_ids,
        question_ids=question_ids,
    )

    transaction.on_commit(lambda: _cleanup_files(file_candidates))
    return {"survey_id": entity_id, "display_identity": identity, "deleted_counts": counts}
