from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from statistics import median, stdev

from django.core.exceptions import ValidationError
from django.db.models import Count, Max, Min, Prefetch
from django.utils import timezone
from django.utils.formats import date_format

from .models import Survey, SurveyAnswer, SurveyAnswerSelection, SurveyQuestion


TEXT_TYPES = {
    SurveyQuestion.Type.SHORT_TEXT,
    SurveyQuestion.Type.LONG_TEXT,
    SurveyQuestion.Type.EMAIL,
}
ORDINARY_CHOICE_TYPES = {
    SurveyQuestion.Type.SINGLE_CHOICE,
    SurveyQuestion.Type.DROPDOWN,
    SurveyQuestion.Type.YES_NO,
}
NUMERIC_TYPES = {
    SurveyQuestion.Type.NUMBER,
    SurveyQuestion.Type.RATING,
    SurveyQuestion.Type.LINEAR_SCALE,
}


def _number(value):
    if value is None:
        return None
    return float(value)


def _display_number(value):
    if value is None:
        return "—"
    decimal = Decimal(str(value))
    rendered = format(decimal, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def _percentage(count, denominator):
    return round((count / denominator) * 100, 1) if denominator else 0.0


def _display_datetime(value):
    return date_format(timezone.localtime(value), "M j, Y, P") if value else "—"


def _numeric_summary(values, *, include_deviation=False):
    ordered = sorted(Decimal(str(value)) for value in values if value is not None)
    if not ordered:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "minimum": None,
            "maximum": None,
            "standard_deviation": None,
        }
    result = {
        "count": len(ordered),
        "mean": _number(sum(ordered) / len(ordered)),
        "median": _number(median(ordered)),
        "minimum": _number(ordered[0]),
        "maximum": _number(ordered[-1]),
        "standard_deviation": None,
    }
    if include_deviation and len(ordered) > 1:
        result["standard_deviation"] = _number(stdev(ordered))
    return result


def _frequency_rows(values):
    counts = Counter(Decimal(str(value)) for value in values if value is not None)
    total = sum(counts.values())
    return [
        {
            "label": _display_number(value),
            "count": count,
            "percentage": _percentage(count, total),
        }
        for value, count in sorted(counts.items())
    ]


def _histogram_rows(values, bins=10):
    decimals = sorted(Decimal(str(value)) for value in values if value is not None)
    if not decimals:
        return []
    if len(set(decimals)) <= 12 or decimals[0] == decimals[-1]:
        return _frequency_rows(decimals)
    minimum, maximum = decimals[0], decimals[-1]
    width = (maximum - minimum) / bins
    counts = [0] * bins
    for value in decimals:
        index = min(int((value - minimum) / width), bins - 1)
        counts[index] += 1
    return [
        {
            "label": f"{_display_number(minimum + width * index)}–{_display_number(minimum + width * (index + 1))}",
            "count": count,
            "percentage": _percentage(count, len(decimals)),
        }
        for index, count in enumerate(counts)
    ]


def _chart(chart_type, rows, *, label="Responses", stacked=False, datasets=None):
    if datasets is None:
        datasets = [{"label": label, "data": [row["count"] for row in rows]}]
    return {
        "type": chart_type,
        "labels": [row["label"] for row in rows],
        "datasets": datasets,
        "stacked": stacked,
    }


def _choice_analysis(question, answers, total_responses, *, multiple=False, likert=False):
    choices = list(question.choices.all())
    response_ids = {answer.response_id for answer in answers}
    counts = Counter()
    weighted = []
    for answer in answers:
        for selection in answer.selections.all():
            counts[selection.choice_id] += 1
            if selection.choice.numeric_value is not None:
                weighted.append(selection.choice.numeric_value)
    denominator = len(response_ids)
    rows = [
        {
            "id": str(choice.pk),
            "key": choice.option_key,
            "label": choice.label,
            "count": counts[choice.pk],
            "percentage": _percentage(counts[choice.pk], denominator),
            "numeric_value": _number(choice.numeric_value),
        }
        for choice in choices
    ]
    numeric_complete = bool(choices) and all(choice.numeric_value is not None for choice in choices)
    stats = _numeric_summary(weighted) if likert and numeric_complete else {}
    if likert:
        datasets = [
            {"label": row["label"], "data": [row["count"]]}
            for row in rows
        ]
        chart = {"type": "bar", "labels": ["Distribution"], "datasets": datasets, "stacked": True}
    else:
        chart = _chart("bar", rows, label="Selections" if multiple else "Responses")
    return {
        "kind": "likert" if likert else "multiple_choice" if multiple else "choice",
        "response_count": denominator,
        "missing_count": total_responses - denominator,
        "rows": rows,
        "statistics": stats,
        "chart": chart,
        "note": (
            "Percentages use respondents who answered this question and may total more than 100%."
            if multiple
            else ""
        ),
    }


def _matrix_analysis(question, answers, total_responses):
    choices = list(question.choices.all())
    rows = list(question.matrix_rows.all())
    by_row = defaultdict(list)
    for answer in answers:
        if answer.matrix_row_id:
            by_row[answer.matrix_row_id].append(answer)
    matrix_rows = []
    for row in rows:
        row_answers = by_row[row.pk]
        counts = Counter()
        numeric_values = []
        for answer in row_answers:
            for selection in answer.selections.all():
                counts[selection.choice_id] += 1
                if selection.choice.numeric_value is not None:
                    numeric_values.append(selection.choice.numeric_value)
        response_count = len({answer.response_id for answer in row_answers})
        distributions = [
            {
                "id": str(choice.pk),
                "key": choice.option_key,
                "label": choice.label,
                "count": counts[choice.pk],
                "percentage": _percentage(counts[choice.pk], response_count),
            }
            for choice in choices
        ]
        numeric_complete = bool(choices) and all(choice.numeric_value is not None for choice in choices)
        matrix_rows.append(
            {
                "id": str(row.pk),
                "key": row.row_key,
                "label": row.label,
                "response_count": response_count,
                "missing_count": total_responses - response_count,
                "distribution": distributions,
                "weighted_mean": (
                    _numeric_summary(numeric_values)["mean"] if numeric_complete else None
                ),
            }
        )
    datasets = [
        {
            "label": choice.label,
            "data": [
                next(item["count"] for item in row["distribution"] if item["id"] == str(choice.pk))
                for row in matrix_rows
            ],
        }
        for choice in choices
    ]
    answered = {answer.response_id for answer in answers}
    return {
        "kind": "matrix",
        "response_count": len(answered),
        "missing_count": total_responses - len(answered),
        "matrix_rows": matrix_rows,
        "chart": {
            "type": "bar",
            "labels": [row["label"] for row in matrix_rows],
            "datasets": datasets,
            "stacked": False,
        },
    }


def _numeric_analysis(question, answers, total_responses):
    values = [answer.numeric_value for answer in answers if answer.numeric_value is not None]
    response_count = len({answer.response_id for answer in answers if answer.numeric_value is not None})
    rows = _histogram_rows(values) if question.question_type == SurveyQuestion.Type.NUMBER else _frequency_rows(values)
    return {
        "kind": "numeric",
        "response_count": response_count,
        "missing_count": total_responses - response_count,
        "rows": rows,
        "statistics": _numeric_summary(
            values, include_deviation=question.question_type == SurveyQuestion.Type.NUMBER
        ),
        "chart": _chart("bar", rows, label="Responses"),
    }


def _ranking_analysis(question, answers, total_responses):
    choices = list(question.choices.all())
    response_ids = {answer.response_id for answer in answers}
    by_choice = defaultdict(list)
    for answer in answers:
        for selection in answer.selections.all():
            if selection.rank is not None:
                by_choice[selection.choice_id].append(selection.rank)
    rows = []
    for choice in choices:
        ranks = by_choice[choice.pk]
        distribution = [
            {"rank": rank, "count": ranks.count(rank)}
            for rank in range(1, len(choices) + 1)
        ]
        rows.append(
            {
                "id": str(choice.pk),
                "key": choice.option_key,
                "label": choice.label,
                "average_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
                "first_choice_count": ranks.count(1),
                "distribution": distribution,
            }
        )
    datasets = [
        {
            "label": f"Rank {rank}",
            "data": [next(item["count"] for item in row["distribution"] if item["rank"] == rank) for row in rows],
        }
        for rank in range(1, len(choices) + 1)
    ]
    return {
        "kind": "ranking",
        "response_count": len(response_ids),
        "missing_count": total_responses - len(response_ids),
        "rows": rows,
        "chart": {
            "type": "bar",
            "labels": [row["label"] for row in rows],
            "datasets": datasets,
            "stacked": True,
        },
        "note": "A lower average rank indicates higher preference when 1 is the first choice.",
    }


def _date_analysis(answers, total_responses):
    values = [answer.date_value for answer in answers if answer.date_value is not None]
    counts = Counter(values)
    rows = [
        {
            "label": value.isoformat(),
            "count": count,
            "percentage": _percentage(count, len(values)),
        }
        for value, count in sorted(counts.items())
    ]
    return {
        "kind": "date",
        "response_count": len(values),
        "missing_count": total_responses - len(values),
        "rows": rows,
        "statistics": {
            "earliest": min(values).isoformat() if values else None,
            "latest": max(values).isoformat() if values else None,
        },
        "chart": _chart("bar", rows, label="Responses"),
    }


def _text_analysis(answers, total_responses, *, include_values):
    answered = [answer for answer in answers if answer.text_value != ""]
    result = {
        "kind": "text",
        "response_count": len({answer.response_id for answer in answered}),
        "missing_count": total_responses - len({answer.response_id for answer in answered}),
        "text_response_total": len(answered),
    }
    if include_values:
        result["text_responses"] = [
            {
                "response_id": str(answer.response_id),
                "submitted_at": answer.response.submitted_at.isoformat(),
                "value": answer.text_value,
            }
            for answer in sorted(answered, key=lambda item: item.response.submitted_at, reverse=True)[:50]
        ]
        result["text_truncated"] = len(answered) > 50
    return result


def build_survey_analytics(survey, *, include_text_values=True, at=None, response_cutoff_at=None):
    survey = Survey.objects.select_related("client", "project").get(
        pk=survey.pk if isinstance(survey, Survey) else survey
    )
    if not survey.published_at:
        raise ValidationError("Analytics are available only for published surveys.")

    now = at or timezone.now()
    local_date = timezone.localdate(now)
    current_timezone = timezone.get_current_timezone()
    day_start = timezone.make_aware(datetime.combine(local_date, time.min), current_timezone)
    day_end = day_start + timedelta(days=1)
    response_queryset = survey.responses.all()
    if response_cutoff_at is not None:
        response_queryset = response_queryset.filter(submitted_at__lte=response_cutoff_at)
    response_summary = response_queryset.aggregate(
        total=Count("id"), first=Min("submitted_at"), last=Max("submitted_at")
    )
    total_responses = response_summary["total"] or 0
    responses_today = response_queryset.filter(submitted_at__gte=day_start, submitted_at__lt=day_end).count()

    questions = list(
        survey.questions.exclude(question_type__in=SurveyQuestion.STRUCTURAL_TYPES)
        .prefetch_related("choices", "matrix_rows")
        .order_by("position", "created_at")
    )
    answer_queryset = (
        SurveyAnswer.objects.filter(response__survey=survey)
        .select_related("response", "question", "matrix_row")
        .prefetch_related(
            Prefetch(
                "selections",
                queryset=SurveyAnswerSelection.objects.select_related("choice").order_by(
                    "rank", "choice__position"
                ),
            )
        )
        .order_by("question__position", "matrix_row__position", "response__submitted_at")
    )
    if response_cutoff_at is not None:
        answer_queryset = answer_queryset.filter(response__submitted_at__lte=response_cutoff_at)
    answers_by_question = defaultdict(list)
    for answer in answer_queryset:
        answers_by_question[answer.question_id].append(answer)

    question_analytics = []
    for number, question in enumerate(questions, start=1):
        question_answers = answers_by_question[question.pk]
        if question.question_type in TEXT_TYPES:
            analysis = _text_analysis(question_answers, total_responses, include_values=include_text_values)
        elif question.question_type in ORDINARY_CHOICE_TYPES:
            analysis = _choice_analysis(question, question_answers, total_responses)
        elif question.question_type == SurveyQuestion.Type.MULTIPLE_CHOICE:
            analysis = _choice_analysis(question, question_answers, total_responses, multiple=True)
        elif question.question_type == SurveyQuestion.Type.LIKERT:
            analysis = _choice_analysis(question, question_answers, total_responses, likert=True)
        elif question.question_type == SurveyQuestion.Type.MATRIX:
            analysis = _matrix_analysis(question, question_answers, total_responses)
        elif question.question_type in NUMERIC_TYPES:
            analysis = _numeric_analysis(question, question_answers, total_responses)
        elif question.question_type == SurveyQuestion.Type.RANKING:
            analysis = _ranking_analysis(question, question_answers, total_responses)
        elif question.question_type == SurveyQuestion.Type.DATE:
            analysis = _date_analysis(question_answers, total_responses)
        else:  # pragma: no cover - protected by Version 1 type choices
            continue
        question_analytics.append(
            {
                "id": str(question.pk),
                "key": question.export_key,
                "number": number,
                "prompt": question.prompt,
                "question_type": question.question_type,
                "question_type_label": question.get_question_type_display(),
                "total_responses": total_responses,
                **analysis,
            }
        )

    return {
        "survey": {
            "id": str(survey.pk),
            "display_identity": survey.display_identity,
            "client": survey.identity_client_name,
            "title": survey.title,
            "reporting_month": survey.reporting_month,
            "reporting_year": survey.reporting_year,
            "status": survey.status,
            "status_label": survey.get_status_display(),
            "starts_at": survey.starts_at.isoformat() if survey.starts_at else None,
            "ends_at": survey.ends_at.isoformat() if survey.ends_at else None,
            "closed_at": survey.closed_at.isoformat() if survey.closed_at else None,
            "starts_at_display": _display_datetime(survey.starts_at),
            "ends_at_display": _display_datetime(survey.ends_at),
            "closed_at_display": _display_datetime(survey.closed_at),
        },
        "summary": {
            "total_responses": total_responses,
            "responses_today": responses_today,
            "first_submission": response_summary["first"].isoformat() if response_summary["first"] else None,
            "last_submission": response_summary["last"].isoformat() if response_summary["last"] else None,
            "first_submission_display": _display_datetime(response_summary["first"]),
            "last_submission_display": _display_datetime(response_summary["last"]),
        },
        "questions": question_analytics,
        "generated_at": now.isoformat(),
    }
