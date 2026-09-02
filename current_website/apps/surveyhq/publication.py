from __future__ import annotations

from django.core.exceptions import ValidationError

from .media import read_verified_question_image
from .models import Survey, SurveyQuestion, checksum_json


CURRENT_DEFINITION_SCHEMA_VERSION = 2


def _serialize_numeric(value):
    return None if value is None else str(value)


def validate_survey_structure(survey: Survey, *, verify_image_files=True):
    questions = list(survey.questions.prefetch_related("choices", "matrix_rows").all())
    answerable = [question for question in questions if question.question_type not in SurveyQuestion.STRUCTURAL_TYPES]
    if not answerable:
        raise ValidationError("A survey must contain at least one answerable question before publication.")

    errors = []
    for question in questions:
        choices = list(question.choices.all())
        rows = list(question.matrix_rows.all())
        if (
            survey.collection_mode == Survey.CollectionMode.ANONYMOUS
            and question.question_type == SurveyQuestion.Type.EMAIL
        ):
            errors.append(
                f"{question.export_key} ({question.prompt}) uses the Email question type. "
                "Anonymous surveys cannot request email addresses; remove or replace this question before publication."
            )
        if question.question_type in SurveyQuestion.STRUCTURAL_TYPES:
            if question.required:
                errors.append(f"{question.export_key} is structural and cannot be required.")
            if choices or rows:
                errors.append(f"{question.export_key} is structural and cannot contain choices or matrix rows.")
            if verify_image_files and question.image:
                try:
                    read_verified_question_image(question)
                except ValidationError as exc:
                    errors.extend(f"{question.export_key}: {message}" for message in exc.messages)
            continue

        if question.question_type in SurveyQuestion.CHOICE_TYPES and len(choices) < 2:
            errors.append(f"{question.export_key} requires at least two choices.")
        if question.question_type not in SurveyQuestion.CHOICE_TYPES and choices:
            errors.append(f"{question.export_key} does not support choices.")
        if question.question_type == SurveyQuestion.Type.YES_NO and len(choices) != 2:
            errors.append(f"{question.export_key} must contain exactly two Yes/No choices.")
        if question.question_type == SurveyQuestion.Type.MATRIX:
            if not rows:
                errors.append(f"{question.export_key} requires at least one matrix row.")
        elif rows:
            errors.append(f"{question.export_key} is not a matrix question and cannot contain matrix rows.")
        if verify_image_files and question.image:
            try:
                read_verified_question_image(question)
            except ValidationError as exc:
                errors.extend(f"{question.export_key}: {message}" for message in exc.messages)

    if errors:
        raise ValidationError(errors)


def build_definition_snapshot(
    survey: Survey,
    *,
    schema_version=CURRENT_DEFINITION_SCHEMA_VERSION,
    verify_image_files=True,
) -> dict:
    if schema_version not in {1, CURRENT_DEFINITION_SCHEMA_VERSION}:
        raise ValidationError("This published SurveyHQ definition version is not supported.")
    validate_survey_structure(survey, verify_image_files=verify_image_files)
    questions = []
    queryset = survey.questions.prefetch_related("choices", "matrix_rows").order_by("position", "created_at")
    for question in queryset:
        question_data = {
            "id": str(question.pk),
            "export_key": question.export_key,
            "position": question.position,
            "type": question.question_type,
            "prompt": question.prompt,
            "help_text": question.help_text,
            "required": question.required,
            "configuration": question.configuration,
            "choices": [
                {
                    "id": str(choice.pk),
                    "option_key": choice.option_key,
                    "position": choice.position,
                    "label": choice.label,
                    "numeric_value": _serialize_numeric(choice.numeric_value),
                }
                for choice in question.choices.all()
            ],
            "matrix_rows": [
                {
                    "id": str(row.pk),
                    "row_key": row.row_key,
                    "position": row.position,
                    "label": row.label,
                }
                for row in question.matrix_rows.all()
            ],
        }
        if schema_version >= 2:
            question_data["image"] = (
                {
                    "file": question.image.name,
                    "original_name": question.image_original_name,
                    "content_type": question.image_content_type,
                    "checksum": question.image_checksum,
                    "byte_size": question.image_byte_size,
                    "width": question.image_width,
                    "height": question.image_height,
                    "alt_text": question.image_alt_text,
                    "decorative": question.image_is_decorative,
                }
                if question.image
                else None
            )
        questions.append(question_data)
    return {"schema_version": schema_version, "survey_id": str(survey.pk), "questions": questions}


def snapshot_with_checksum(survey: Survey):
    snapshot = build_definition_snapshot(survey)
    return snapshot, checksum_json(snapshot)


def definition_matches_snapshot(survey: Survey) -> bool:
    if not survey.definition_checksum:
        return False
    schema_version = survey.definition_snapshot.get("schema_version", 1)
    snapshot = build_definition_snapshot(
        survey,
        schema_version=schema_version,
        verify_image_files=False,
    )
    return checksum_json(snapshot) == survey.definition_checksum
