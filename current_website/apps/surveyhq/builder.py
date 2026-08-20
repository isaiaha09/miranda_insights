from __future__ import annotations

import copy
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max

from .audit import record_survey_event
from .media import assign_question_image, clear_question_image
from .models import Survey, SurveyChoice, SurveyMatrixRow, SurveyQuestion
from .permissions import require_permission


LIKERT_PRESETS = {
    "five_agreement": [
        ("scale01", "Strongly Disagree", 1),
        ("scale02", "Disagree", 2),
        ("scale03", "Neutral", 3),
        ("scale04", "Agree", 4),
        ("scale05", "Strongly Agree", 5),
    ],
    "seven_agreement": [
        ("scale01", "Strongly Disagree", 1),
        ("scale02", "Disagree", 2),
        ("scale03", "Somewhat Disagree", 3),
        ("scale04", "Neither Agree nor Disagree", 4),
        ("scale05", "Somewhat Agree", 5),
        ("scale06", "Agree", 6),
        ("scale07", "Strongly Agree", 7),
    ],
}


def _create_likert_choices(question, preset):
    for option_key, label, numeric_value in LIKERT_PRESETS[preset]:
        SurveyChoice.objects.create(
            question=question,
            option_key=option_key,
            label=label,
            numeric_value=numeric_value,
            position=int(option_key[-2:]),
        )


def _require_draft(survey: Survey):
    if survey.status != Survey.Status.DRAFT or survey.published_at:
        raise ValidationError("Published survey structure is read-only; duplicate it into a new Draft.")


def _next_key(queryset, field_name: str, prefix: str) -> str:
    highest = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for value in queryset.values_list(field_name, flat=True):
        match = pattern.match(value)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:03d}"


def _normalize_positions(queryset, ordered_ids):
    objects = list(queryset.select_for_update().order_by("position", "pk"))
    current_ids = [obj.pk for obj in objects]
    if set(current_ids) != set(ordered_ids) or len(current_ids) != len(ordered_ids):
        raise ValidationError("The requested ordering does not match the current records.")
    by_id = {obj.pk: obj for obj in objects}
    offset = len(objects) + 1000
    queryset.update(position=models_f_position_plus(offset))
    for position, object_id in enumerate(ordered_ids, start=1):
        type(by_id[object_id]).objects.filter(pk=object_id).update(position=position)


def models_f_position_plus(offset):
    from django.db.models import F

    return F("position") + offset


def _move(queryset, object_id, direction):
    objects = list(queryset.select_for_update().order_by("position", "pk"))
    ids = [obj.pk for obj in objects]
    try:
        index = ids.index(object_id)
    except ValueError as exc:
        raise ValidationError("The requested record does not belong to this survey structure.") from exc
    target = index - 1 if direction == "up" else index + 1
    if direction not in {"up", "down"} or target < 0 or target >= len(ids):
        return False
    ids[index], ids[target] = ids[target], ids[index]
    _normalize_positions(queryset, ids)
    return True


@transaction.atomic
def create_question(
    *, survey, actor, question_type, prompt, help_text="", required=False, configuration=None,
    preset="", prepared_image=None, image_alt_text="", image_is_decorative=False
):
    require_permission(actor, "add_surveyquestion")
    instance = Survey.objects.select_for_update().get(pk=survey.pk if isinstance(survey, Survey) else survey)
    _require_draft(instance)
    if question_type in SurveyQuestion.STRUCTURAL_TYPES:
        required = False
    question = SurveyQuestion.objects.create(
        survey=instance,
        export_key=_next_key(instance.questions.all(), "export_key", "q"),
        position=(instance.questions.aggregate(value=Max("position"))["value"] or 0) + 1,
        question_type=question_type,
        prompt=prompt,
        help_text=help_text,
        required=required,
        configuration=configuration or {},
    )
    if question_type == SurveyQuestion.Type.YES_NO:
        SurveyChoice.objects.create(question=question, option_key="yes", label="Yes", position=1)
        SurveyChoice.objects.create(question=question, option_key="no", label="No", position=2)
    elif question_type == SurveyQuestion.Type.LIKERT and preset in LIKERT_PRESETS:
        _create_likert_choices(question, preset)
    if prepared_image:
        assign_question_image(
            question,
            prepared_image,
            alt_text=image_alt_text,
            decorative=image_is_decorative,
        )
        question.save()
    return question


@transaction.atomic
def apply_likert_preset(question, *, actor, preset):
    require_permission(actor, "add_surveychoice")
    instance = SurveyQuestion.objects.select_for_update().select_related("survey").get(
        pk=question.pk if isinstance(question, SurveyQuestion) else question
    )
    _require_draft(instance.survey)
    if instance.question_type != SurveyQuestion.Type.LIKERT:
        raise ValidationError("Likert presets apply only to Likert questions.")
    if preset not in LIKERT_PRESETS:
        raise ValidationError("Select a supported Likert preset.")
    if instance.choices.exists():
        raise ValidationError("A preset cannot overwrite existing Likert options.")
    _create_likert_choices(instance, preset)
    return instance


@transaction.atomic
def update_question(
    *, question, actor, prompt, help_text="", required=False, configuration=None,
    prepared_image=None, remove_image=False, image_alt_text="", image_is_decorative=False
):
    require_permission(actor, "change_surveyquestion")
    question_id = question.pk if isinstance(question, SurveyQuestion) else question
    instance = SurveyQuestion.objects.select_for_update().select_related("survey").get(pk=question_id)
    _require_draft(instance.survey)
    if instance.question_type in SurveyQuestion.STRUCTURAL_TYPES:
        required = False
    instance.prompt = prompt
    instance.help_text = help_text
    instance.required = required
    instance.configuration = configuration or {}
    if remove_image:
        clear_question_image(instance)
    elif prepared_image:
        assign_question_image(
            instance,
            prepared_image,
            alt_text=image_alt_text,
            decorative=image_is_decorative,
        )
    elif instance.image:
        instance.image_alt_text = "" if image_is_decorative else image_alt_text.strip()
        instance.image_is_decorative = image_is_decorative
    instance.save()
    return instance


@transaction.atomic
def duplicate_question(question, *, actor):
    require_permission(actor, "add_surveyquestion")
    question_id = question.pk if isinstance(question, SurveyQuestion) else question
    original = (
        SurveyQuestion.objects.select_for_update()
        .select_related("survey")
        .prefetch_related("choices", "matrix_rows")
        .get(pk=question_id)
    )
    _require_draft(original.survey)
    survey = Survey.objects.select_for_update().get(pk=original.survey_id)
    ordered_ids = list(survey.questions.order_by("position", "pk").values_list("pk", flat=True))
    duplicate = SurveyQuestion.objects.create(
        survey=survey,
        export_key=_next_key(survey.questions.all(), "export_key", "q"),
        position=(survey.questions.aggregate(value=Max("position"))["value"] or 0) + 1,
        question_type=original.question_type,
        prompt=original.prompt,
        help_text=original.help_text,
        required=original.required,
        configuration=copy.deepcopy(original.configuration),
        image=original.image.name,
        image_original_name=original.image_original_name,
        image_content_type=original.image_content_type,
        image_checksum=original.image_checksum,
        image_byte_size=original.image_byte_size,
        image_width=original.image_width,
        image_height=original.image_height,
        image_alt_text=original.image_alt_text,
        image_is_decorative=original.image_is_decorative,
    )
    for choice in original.choices.all():
        SurveyChoice.objects.create(
            question=duplicate,
            option_key=choice.option_key,
            label=choice.label,
            numeric_value=choice.numeric_value,
            position=choice.position,
        )
    for row in original.matrix_rows.all():
        SurveyMatrixRow.objects.create(
            question=duplicate,
            row_key=row.row_key,
            label=row.label,
            position=row.position,
        )
    source_index = ordered_ids.index(original.pk)
    ordered_ids.insert(source_index + 1, duplicate.pk)
    _normalize_positions(survey.questions.all(), ordered_ids)
    record_survey_event(
        survey=survey,
        actor=actor,
        event_type="question_duplicated",
        summary=f"Duplicated {original.export_key} as {duplicate.export_key} in {survey.display_identity}.",
        metadata={"source_question_id": str(original.pk), "question_id": str(duplicate.pk)},
    )
    duplicate.refresh_from_db()
    return duplicate


@transaction.atomic
def delete_question(question, *, actor):
    require_permission(actor, "delete_surveyquestion")
    question_id = question.pk if isinstance(question, SurveyQuestion) else question
    instance = SurveyQuestion.objects.select_for_update().select_related("survey").get(pk=question_id)
    _require_draft(instance.survey)
    survey = instance.survey
    instance.choices.all().delete()
    instance.matrix_rows.all().delete()
    instance.delete()
    remaining_ids = list(survey.questions.order_by("position", "pk").values_list("pk", flat=True))
    if remaining_ids:
        _normalize_positions(survey.questions.all(), remaining_ids)


@transaction.atomic
def move_question(question, *, actor, direction):
    require_permission(actor, "change_surveyquestion")
    question_id = question.pk if isinstance(question, SurveyQuestion) else question
    instance = SurveyQuestion.objects.select_related("survey").get(pk=question_id)
    _require_draft(instance.survey)
    return _move(instance.survey.questions.all(), instance.pk, direction)


def _assert_choice_editable(question, actor, permission):
    require_permission(actor, permission)
    _require_draft(question.survey)
    if question.question_type == SurveyQuestion.Type.YES_NO:
        raise PermissionDenied("Yes/No options are fixed; edit only the question wording.")
    if question.question_type not in SurveyQuestion.CHOICE_TYPES:
        raise ValidationError("This question type does not use relational choices.")


@transaction.atomic
def add_choice(*, question, actor, label, numeric_value=None):
    instance = SurveyQuestion.objects.select_for_update().select_related("survey").get(
        pk=question.pk if isinstance(question, SurveyQuestion) else question
    )
    _assert_choice_editable(instance, actor, "add_surveychoice")
    return SurveyChoice.objects.create(
        question=instance,
        option_key=_next_key(instance.choices.all(), "option_key", "opt"),
        label=label,
        numeric_value=numeric_value,
        position=(instance.choices.aggregate(value=Max("position"))["value"] or 0) + 1,
    )


@transaction.atomic
def update_choice(*, choice, actor, label, numeric_value=None):
    instance = SurveyChoice.objects.select_for_update().select_related("question__survey").get(
        pk=choice.pk if isinstance(choice, SurveyChoice) else choice
    )
    _assert_choice_editable(instance.question, actor, "change_surveychoice")
    instance.label = label
    instance.numeric_value = numeric_value
    instance.save()
    return instance


@transaction.atomic
def delete_choice(choice, *, actor):
    instance = SurveyChoice.objects.select_for_update().select_related("question__survey").get(
        pk=choice.pk if isinstance(choice, SurveyChoice) else choice
    )
    _assert_choice_editable(instance.question, actor, "delete_surveychoice")
    question = instance.question
    instance.delete()
    remaining_ids = list(question.choices.order_by("position", "pk").values_list("pk", flat=True))
    if remaining_ids:
        _normalize_positions(question.choices.all(), remaining_ids)


@transaction.atomic
def move_choice(choice, *, actor, direction):
    instance = SurveyChoice.objects.select_related("question__survey").get(
        pk=choice.pk if isinstance(choice, SurveyChoice) else choice
    )
    _assert_choice_editable(instance.question, actor, "change_surveychoice")
    return _move(instance.question.choices.all(), instance.pk, direction)


@transaction.atomic
def add_matrix_row(*, question, actor, label):
    require_permission(actor, "add_surveymatrixrow")
    instance = SurveyQuestion.objects.select_for_update().select_related("survey").get(
        pk=question.pk if isinstance(question, SurveyQuestion) else question
    )
    _require_draft(instance.survey)
    if instance.question_type != SurveyQuestion.Type.MATRIX:
        raise ValidationError("Rows can be added only to Matrix questions.")
    return SurveyMatrixRow.objects.create(
        question=instance,
        row_key=_next_key(instance.matrix_rows.all(), "row_key", "row"),
        label=label,
        position=(instance.matrix_rows.aggregate(value=Max("position"))["value"] or 0) + 1,
    )


@transaction.atomic
def update_matrix_row(*, row, actor, label):
    require_permission(actor, "change_surveymatrixrow")
    instance = SurveyMatrixRow.objects.select_for_update().select_related("question__survey").get(
        pk=row.pk if isinstance(row, SurveyMatrixRow) else row
    )
    _require_draft(instance.question.survey)
    instance.label = label
    instance.save()
    return instance


@transaction.atomic
def delete_matrix_row(row, *, actor):
    require_permission(actor, "delete_surveymatrixrow")
    instance = SurveyMatrixRow.objects.select_for_update().select_related("question__survey").get(
        pk=row.pk if isinstance(row, SurveyMatrixRow) else row
    )
    _require_draft(instance.question.survey)
    question = instance.question
    instance.delete()
    remaining_ids = list(question.matrix_rows.order_by("position", "pk").values_list("pk", flat=True))
    if remaining_ids:
        _normalize_positions(question.matrix_rows.all(), remaining_ids)


@transaction.atomic
def move_matrix_row(row, *, actor, direction):
    require_permission(actor, "change_surveymatrixrow")
    instance = SurveyMatrixRow.objects.select_related("question__survey").get(
        pk=row.pk if isinstance(row, SurveyMatrixRow) else row
    )
    _require_draft(instance.question.survey)
    return _move(instance.question.matrix_rows.all(), instance.pk, direction)
