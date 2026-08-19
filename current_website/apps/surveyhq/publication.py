from __future__ import annotations

from django.core.exceptions import ValidationError

from .models import Survey, SurveyQuestion, checksum_json


def _serialize_numeric(value):
    return None if value is None else str(value)


def validate_survey_structure(survey: Survey):
    questions = list(survey.questions.prefetch_related("choices", "matrix_rows").all())
    answerable = [question for question in questions if question.question_type not in SurveyQuestion.STRUCTURAL_TYPES]
    if not answerable:
        raise ValidationError("A survey must contain at least one answerable question before publication.")

    errors = []
    for question in questions:
        choices = list(question.choices.all())
        rows = list(question.matrix_rows.all())
        if question.question_type in SurveyQuestion.STRUCTURAL_TYPES:
            if question.required:
                errors.append(f"{question.export_key} is structural and cannot be required.")
            if choices or rows:
                errors.append(f"{question.export_key} is structural and cannot contain choices or matrix rows.")
            continue

        if question.question_type in SurveyQuestion.CHOICE_TYPES and len(choices) < 2:
            errors.append(f"{question.export_key} requires at least two choices.")
        if question.question_type not in SurveyQuestion.CHOICE_TYPES and choices:
            errors.append(f"{question.export_key} does not support choices.")
        if question.question_type == SurveyQuestion.Type.YES_NO and len(choices) != 2:
            errors.append(f"{question.export_key} must contain exactly two Yes/No choices.")
        if question.question_type == SurveyQuestion.Type.LIKERT and any(
            choice.numeric_value is None for choice in choices
        ):
            errors.append(f"{question.export_key} requires a numeric value for every Likert choice.")
        if question.question_type == SurveyQuestion.Type.MATRIX:
            if not rows:
                errors.append(f"{question.export_key} requires at least one matrix row.")
        elif rows:
            errors.append(f"{question.export_key} is not a matrix question and cannot contain matrix rows.")

    if errors:
        raise ValidationError(errors)


def build_definition_snapshot(survey: Survey) -> dict:
    validate_survey_structure(survey)
    questions = []
    queryset = survey.questions.prefetch_related("choices", "matrix_rows").order_by("position", "created_at")
    for question in queryset:
        questions.append(
            {
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
        )
    return {"schema_version": 1, "survey_id": str(survey.pk), "questions": questions}


def snapshot_with_checksum(survey: Survey):
    snapshot = build_definition_snapshot(survey)
    return snapshot, checksum_json(snapshot)


def definition_matches_snapshot(survey: Survey) -> bool:
    if not survey.definition_checksum:
        return False
    snapshot = build_definition_snapshot(survey)
    return checksum_json(snapshot) == survey.definition_checksum
