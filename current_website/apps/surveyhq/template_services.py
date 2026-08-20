from __future__ import annotations

import copy

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .audit import record_survey_event, record_template_event
from .lifecycle import create_draft
from .models import Survey, SurveyChoice, SurveyMatrixRow, SurveyQuestion, SurveyTemplate, checksum_json
from .permissions import require_permission
from .publication import build_definition_snapshot, validate_survey_structure


TEMPLATE_SCHEMA_VERSION = 2
SUPPORTED_TEMPLATE_SCHEMA_VERSIONS = {1, TEMPLATE_SCHEMA_VERSION}


def _definition_without_runtime_ids(snapshot):
    questions = []
    for question in snapshot.get("questions", []):
        questions.append(
            {
                "export_key": question["export_key"],
                "position": question["position"],
                "type": question["type"],
                "prompt": question["prompt"],
                "help_text": question.get("help_text", ""),
                "required": bool(question.get("required")),
                "configuration": copy.deepcopy(question.get("configuration") or {}),
                "image": copy.deepcopy(question.get("image")),
                "choices": [
                    {
                        "option_key": choice["option_key"],
                        "position": choice["position"],
                        "label": choice["label"],
                        "numeric_value": choice.get("numeric_value"),
                    }
                    for choice in question.get("choices", [])
                ],
                "matrix_rows": [
                    {
                        "row_key": row["row_key"],
                        "position": row["position"],
                        "label": row["label"],
                    }
                    for row in question.get("matrix_rows", [])
                ],
            }
        )
    return {"schema_version": TEMPLATE_SCHEMA_VERSION, "questions": questions}


def build_template_definition(survey: Survey):
    if survey.published_at:
        snapshot = survey.definition_snapshot
        if not snapshot or checksum_json(snapshot) != survey.definition_checksum:
            raise ValidationError("The published survey definition checksum does not match.")
    else:
        validate_survey_structure(survey)
        snapshot = build_definition_snapshot(survey)
    return _definition_without_runtime_ids(snapshot)


@transaction.atomic
def create_template_from_survey(*, survey, actor, name, category="", description=""):
    require_permission(actor, "manage_survey_templates")
    source = Survey.objects.select_for_update().prefetch_related("questions__choices", "questions__matrix_rows").get(
        pk=survey.pk if isinstance(survey, Survey) else survey
    )
    template = SurveyTemplate.objects.create(
        name=name,
        description=description,
        category=category,
        schema_version=TEMPLATE_SCHEMA_VERSION,
        definition=build_template_definition(source),
        source_survey=source,
        created_by=actor,
        updated_by=actor,
    )
    record_template_event(
        template=template,
        actor=actor,
        event_type="template_created",
        summary=f"Created template {template.name} from {source.display_identity}.",
        metadata={"source_survey_id": str(source.pk)},
    )
    return template


@transaction.atomic
def duplicate_template(template, *, actor, name):
    require_permission(actor, "manage_survey_templates")
    source = SurveyTemplate.objects.select_for_update().get(
        pk=template.pk if isinstance(template, SurveyTemplate) else template
    )
    duplicate = SurveyTemplate.objects.create(
        name=name,
        description=source.description,
        category=source.category,
        schema_version=source.schema_version,
        definition=copy.deepcopy(source.definition),
        source_survey=source.source_survey,
        created_by=actor,
        updated_by=actor,
    )
    record_template_event(
        template=duplicate,
        actor=actor,
        event_type="template_duplicated",
        summary=f"Duplicated template {source.name} as {duplicate.name}.",
        metadata={"source_template_id": str(source.pk)},
    )
    return duplicate


@transaction.atomic
def update_template_metadata(template, *, actor, name, category="", description=""):
    require_permission(actor, "manage_survey_templates")
    instance = SurveyTemplate.objects.select_for_update().get(
        pk=template.pk if isinstance(template, SurveyTemplate) else template
    )
    instance.name = name
    instance.category = category
    instance.description = description
    instance.updated_by = actor
    instance.save()
    return instance


@transaction.atomic
def archive_template(template, *, actor):
    require_permission(actor, "manage_survey_templates")
    instance = SurveyTemplate.objects.select_for_update().get(
        pk=template.pk if isinstance(template, SurveyTemplate) else template
    )
    if instance.status == SurveyTemplate.Status.ARCHIVED:
        return instance
    instance.status = SurveyTemplate.Status.ARCHIVED
    instance.archived_at = timezone.now()
    instance.updated_by = actor
    instance.save()
    record_template_event(
        template=instance,
        actor=actor,
        event_type="template_archived",
        summary=f"Archived template {instance.name}.",
    )
    return instance


@transaction.atomic
def delete_eligible_template(template, *, actor):
    require_permission(actor, "manage_survey_templates")
    instance = SurveyTemplate.objects.select_for_update().get(
        pk=template.pk if isinstance(template, SurveyTemplate) else template
    )
    if instance.surveys.exists():
        raise ValidationError("A template used to create surveys must be archived instead of deleted.")
    entity_id = instance.pk
    event = record_template_event(
        template=instance,
        actor=actor,
        event_type="template_deleted",
        summary=f"Deleted eligible template {instance.name}.",
    )
    instance.delete()
    event.refresh_from_db()
    return entity_id


def _validate_template(template: SurveyTemplate):
    if template.status != SurveyTemplate.Status.ACTIVE:
        raise ValidationError("Only active templates can create surveys.")
    if template.schema_version not in SUPPORTED_TEMPLATE_SCHEMA_VERSIONS:
        raise ValidationError("This template schema version is not supported.")
    if checksum_json(template.definition) != template.definition_checksum:
        raise ValidationError("The template definition checksum does not match.")


@transaction.atomic
def create_survey_from_template(
    *,
    template,
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
):
    require_permission(actor, "view_surveytemplate")
    instance = SurveyTemplate.objects.select_for_update().get(
        pk=template.pk if isinstance(template, SurveyTemplate) else template
    )
    _validate_template(instance)
    survey = create_draft(
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
        source_template=instance,
        actor=actor,
    )
    for question_data in sorted(instance.definition["questions"], key=lambda item: item["position"]):
        question = SurveyQuestion.objects.create(
            survey=survey,
            export_key=question_data["export_key"],
            position=question_data["position"],
            question_type=question_data["type"],
            prompt=question_data["prompt"],
            help_text=question_data.get("help_text", ""),
            required=question_data.get("required", False),
            configuration=copy.deepcopy(question_data.get("configuration") or {}),
            image=(question_data.get("image") or {}).get("file", ""),
            image_original_name=(question_data.get("image") or {}).get("original_name", ""),
            image_content_type=(question_data.get("image") or {}).get("content_type", ""),
            image_checksum=(question_data.get("image") or {}).get("checksum", ""),
            image_byte_size=(question_data.get("image") or {}).get("byte_size", 0),
            image_width=(question_data.get("image") or {}).get("width", 0),
            image_height=(question_data.get("image") or {}).get("height", 0),
            image_alt_text=(question_data.get("image") or {}).get("alt_text", ""),
            image_is_decorative=(question_data.get("image") or {}).get("decorative", False),
        )
        for choice_data in sorted(question_data.get("choices", []), key=lambda item: item["position"]):
            SurveyChoice.objects.create(
                question=question,
                option_key=choice_data["option_key"],
                label=choice_data["label"],
                numeric_value=choice_data.get("numeric_value"),
                position=choice_data["position"],
            )
        for row_data in sorted(question_data.get("matrix_rows", []), key=lambda item: item["position"]):
            SurveyMatrixRow.objects.create(
                question=question,
                row_key=row_data["row_key"],
                label=row_data["label"],
                position=row_data["position"],
            )
    record_survey_event(
        survey=survey,
        actor=actor,
        event_type="survey_created_from_template",
        summary=f"Created {survey.display_identity} from template {instance.name}.",
        metadata={"template_id": str(instance.pk)},
    )
    return survey
