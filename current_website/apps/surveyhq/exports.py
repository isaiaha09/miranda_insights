from __future__ import annotations

import re
from collections import defaultdict

from django.db.models import Prefetch
from django.utils.text import slugify

from .models import SurveyAnswer, SurveyAnswerSelection, SurveyQuestion, SurveyResponse


BASE_HEADERS = [
    "survey_id",
    "survey_display_identity",
    "client",
    "reporting_month",
    "reporting_year",
    "response_id",
    "submitted_at",
    "source",
]
LONG_HEADERS = BASE_HEADERS + [
    "question_id",
    "export_key",
    "question_text",
    "question_type",
    "matrix_row_id",
    "matrix_row_key",
    "matrix_row_label",
    "choice_id",
    "choice_key",
    "choice_label",
    "text_value",
    "numeric_value",
    "date_value",
    "rank",
]
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_csv_text(value):
    if value is None:
        return ""
    text = str(value)
    if text.lstrip().startswith(FORMULA_PREFIXES):
        return f"'{text}"
    return text


def _slug(value, fallback):
    result = re.sub(r"[^a-z0-9_]+", "_", slugify(value).replace("-", "_"))[:40].strip("_")
    return result or fallback


def _base_values(survey, response):
    return [
        str(survey.pk),
        safe_csv_text(survey.display_identity),
        safe_csv_text(survey.identity_client_name),
        survey.reporting_month,
        survey.reporting_year,
        str(response.pk),
        response.submitted_at.isoformat(),
        response.source,
    ]


def _questions(survey):
    return list(
        survey.questions.exclude(question_type__in=SurveyQuestion.STRUCTURAL_TYPES)
        .prefetch_related("choices", "matrix_rows")
        .order_by("position", "created_at")
    )


def _responses(survey, cutoff):
    selection_queryset = SurveyAnswerSelection.objects.select_related("choice").order_by(
        "rank", "choice__position"
    )
    answer_queryset = (
        SurveyAnswer.objects.select_related("question", "matrix_row")
        .prefetch_related(Prefetch("selections", queryset=selection_queryset))
        .order_by("question__position", "matrix_row__position", "id")
    )
    return list(
        SurveyResponse.objects.filter(survey=survey, submitted_at__lte=cutoff)
        .prefetch_related(Prefetch("answers", queryset=answer_queryset))
        .order_by("submitted_at", "id")
    )


def _wide_columns(questions):
    columns = []
    for question in questions:
        prefix = f"{question.export_key}__{_slug(question.prompt, 'question')}"
        choices = list(question.choices.all())
        if question.question_type in {
            SurveyQuestion.Type.SHORT_TEXT,
            SurveyQuestion.Type.LONG_TEXT,
            SurveyQuestion.Type.EMAIL,
        }:
            columns.append((f"{prefix}__text", question, "text", None))
        elif question.question_type in {
            SurveyQuestion.Type.NUMBER,
            SurveyQuestion.Type.RATING,
            SurveyQuestion.Type.LINEAR_SCALE,
        }:
            columns.append((f"{prefix}__value", question, "numeric", None))
        elif question.question_type == SurveyQuestion.Type.DATE:
            columns.append((f"{prefix}__date", question, "date", None))
        elif question.question_type == SurveyQuestion.Type.MULTIPLE_CHOICE:
            for choice in choices:
                label = _slug(choice.label, choice.option_key)
                columns.append((f"{prefix}__{choice.option_key}__{label}", question, "multiple", choice))
        elif question.question_type == SurveyQuestion.Type.MATRIX:
            numeric = any(choice.numeric_value is not None for choice in choices)
            for row in question.matrix_rows.all():
                row_prefix = f"{prefix}__{row.row_key}__{_slug(row.label, 'row')}"
                columns.append((f"{row_prefix}__label", question, "matrix_label", row))
                if numeric:
                    columns.append((f"{row_prefix}__value", question, "matrix_value", row))
        elif question.question_type == SurveyQuestion.Type.RANKING:
            for choice in choices:
                label = _slug(choice.label, choice.option_key)
                columns.append((f"{prefix}__{choice.option_key}__{label}__rank", question, "rank", choice))
        else:
            columns.append((f"{prefix}__label", question, "choice_label", None))
            if any(choice.numeric_value is not None for choice in choices):
                columns.append((f"{prefix}__value", question, "choice_value", None))
    return columns


def wide_csv_rows(survey, cutoff):
    questions = _questions(survey)
    columns = _wide_columns(questions)
    yield BASE_HEADERS + [column[0] for column in columns]
    for response in _responses(survey, cutoff):
        by_question = defaultdict(list)
        for answer in response.answers.all():
            by_question[answer.question_id].append(answer)
        values = []
        for _header, question, kind, related in columns:
            answers = by_question[question.pk]
            answer = answers[0] if answers else None
            if kind == "text":
                values.append(safe_csv_text(answer.text_value) if answer else "")
            elif kind == "numeric":
                values.append(answer.numeric_value if answer and answer.numeric_value is not None else "")
            elif kind == "date":
                values.append(answer.date_value.isoformat() if answer and answer.date_value else "")
            elif kind == "multiple":
                if not answer:
                    values.append("")
                else:
                    selected = {selection.choice_id for selection in answer.selections.all()}
                    values.append(1 if related.pk in selected else 0)
            elif kind.startswith("matrix"):
                matrix_answer = next((item for item in answers if item.matrix_row_id == related.pk), None)
                if not matrix_answer:
                    values.append("")
                elif kind == "matrix_value":
                    values.append(matrix_answer.numeric_value if matrix_answer.numeric_value is not None else "")
                else:
                    selections = list(matrix_answer.selections.all())
                    values.append(safe_csv_text(selections[0].choice.label) if selections else "")
            elif kind == "rank":
                selection = next(
                    (item for item in (answer.selections.all() if answer else []) if item.choice_id == related.pk),
                    None,
                )
                values.append(selection.rank if selection else "")
            else:
                selections = list(answer.selections.all()) if answer else []
                choice = selections[0].choice if selections else None
                values.append(
                    safe_csv_text(choice.label) if kind == "choice_label" and choice else
                    choice.numeric_value if kind == "choice_value" and choice and choice.numeric_value is not None else ""
                )
        yield _base_values(survey, response) + values


def long_csv_rows(survey, cutoff):
    yield LONG_HEADERS
    for response in _responses(survey, cutoff):
        base = _base_values(survey, response)
        for answer in response.answers.all():
            selections = list(answer.selections.all())
            records = selections or [None]
            for selection in records:
                row = answer.matrix_row
                choice = selection.choice if selection else None
                yield base + [
                    str(answer.question_id),
                    answer.question.export_key,
                    safe_csv_text(answer.question.prompt),
                    answer.question.question_type,
                    str(row.pk) if row else "",
                    row.row_key if row else "",
                    safe_csv_text(row.label) if row else "",
                    str(choice.pk) if choice else "",
                    choice.option_key if choice else "",
                    safe_csv_text(choice.label) if choice else "",
                    safe_csv_text(answer.text_value),
                    answer.numeric_value if answer.numeric_value is not None else "",
                    answer.date_value.isoformat() if answer.date_value else "",
                    selection.rank if selection and selection.rank is not None else "",
                ]
