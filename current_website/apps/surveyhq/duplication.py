from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .audit import record_survey_event
from .lifecycle import _create_with_unique_code
from .models import Survey, SurveyChoice, SurveyMatrixRow, SurveyQuestion
from .permissions import require_permission


@transaction.atomic
def duplicate_survey(
    source,
    *,
    actor,
    title=None,
    copy_client=False,
    target_client=None,
    copy_project=False,
    target_project=None,
    copy_reporting_period=False,
    reporting_month=None,
    reporting_year=None,
    copy_schedule=False,
) -> Survey:
    require_permission(actor, "duplicate_survey")
    source_id = source.pk if isinstance(source, Survey) else source
    original = (
        Survey.objects.select_for_update()
        .select_related("client", "project", "source_template")
        .prefetch_related("questions__choices", "questions__matrix_rows")
        .get(pk=source_id)
    )

    client = original.client if copy_client else target_client
    if client is None:
        raise ValidationError({"client": "Select a target client or explicitly copy the source client."})

    project = original.project if copy_project else target_project
    if project is not None and project.client_id != client.pk:
        raise ValidationError({"project": "The target project must belong to the target client."})

    now = timezone.localtime()
    month = original.reporting_month if copy_reporting_period else (reporting_month or now.month)
    year = original.reporting_year if copy_reporting_period else (reporting_year or now.year)
    starts_at = original.starts_at if copy_schedule else None
    close_mode = original.close_mode if copy_schedule else Survey.CloseMode.MANUAL
    ends_at = original.ends_at if copy_schedule else None

    duplicate = _create_with_unique_code(
        client=client,
        project=project,
        title=title or original.title,
        description=original.description,
        category=original.category,
        reporting_month=month,
        reporting_year=year,
        starts_at=starts_at,
        close_mode=close_mode,
        ends_at=ends_at,
        source_survey=original,
        source_template=original.source_template,
        created_by=actor,
        updated_by=actor,
    )

    for question in original.questions.all():
        copied_question = SurveyQuestion.objects.create(
            survey=duplicate,
            export_key=question.export_key,
            position=question.position,
            question_type=question.question_type,
            prompt=question.prompt,
            help_text=question.help_text,
            required=question.required,
            configuration=question.configuration,
        )
        for choice in question.choices.all():
            SurveyChoice.objects.create(
                question=copied_question,
                option_key=choice.option_key,
                label=choice.label,
                numeric_value=choice.numeric_value,
                position=choice.position,
            )
        for row in question.matrix_rows.all():
            SurveyMatrixRow.objects.create(
                question=copied_question,
                row_key=row.row_key,
                label=row.label,
                position=row.position,
            )

    record_survey_event(
        survey=duplicate,
        actor=actor,
        event_type="survey_duplicated",
        summary=f"Created {duplicate.display_identity} by duplicating {original.display_identity}.",
        metadata={"source_survey_id": str(original.pk)},
    )
    return duplicate
