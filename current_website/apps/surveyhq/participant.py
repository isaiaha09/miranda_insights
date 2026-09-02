from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from landingpage.turnstile import is_mobile_app_request

from .audit import record_survey_event
from .exceptions import InvalidLifecycleTransition
from .lifecycle import close_survey, open_scheduled_survey
from .media import mark_question_image_availability
from .models import (
    Survey,
    SurveyAnswer,
    SurveyAnswerSelection,
    SurveyChoice,
    SurveyQuestion,
    SurveyResponse,
)
from .publication import definition_matches_snapshot


GRANT_SESSION_KEY = "surveyhq_participant_grant"
COMPLETION_SESSION_KEY = "surveyhq_completion"


class ParticipantAccessError(Exception):
    pass


class DuplicateParticipantSubmission(Exception):
    pass


@dataclass(frozen=True)
class ParticipantGrant:
    survey_id: str
    nonce: str
    issued_at: datetime
    expires_at: datetime
    definition_checksum: str


def _epoch(value: datetime) -> int:
    return int(value.timestamp())


def _from_epoch(value) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


@sensitive_variables()
def issue_participant_grant(request, survey: Survey, *, at=None) -> ParticipantGrant:
    now = at or timezone.now()
    grant = ParticipantGrant(
        survey_id=str(survey.pk),
        nonce=secrets.token_urlsafe(48),
        issued_at=now,
        expires_at=now + timedelta(seconds=settings.SURVEYHQ_GRANT_AGE_SECONDS),
        definition_checksum=survey.definition_checksum,
    )
    request.session.cycle_key()
    request.session[GRANT_SESSION_KEY] = {
        "survey_id": grant.survey_id,
        "nonce": grant.nonce,
        "issued_at": _epoch(grant.issued_at),
        "expires_at": _epoch(grant.expires_at),
        "definition_checksum": grant.definition_checksum,
    }
    request.session.pop(COMPLETION_SESSION_KEY, None)
    return grant


@sensitive_variables()
def get_participant_grant(request, *, at=None) -> ParticipantGrant:
    payload = request.session.get(GRANT_SESSION_KEY)
    if not isinstance(payload, dict):
        raise ParticipantAccessError("Participant access is unavailable.")
    try:
        grant = ParticipantGrant(
            survey_id=str(payload["survey_id"]),
            nonce=str(payload["nonce"]),
            issued_at=_from_epoch(payload["issued_at"]),
            expires_at=_from_epoch(payload["expires_at"]),
            definition_checksum=str(payload["definition_checksum"]),
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        request.session.pop(GRANT_SESSION_KEY, None)
        raise ParticipantAccessError("Participant access is unavailable.") from exc
    if not grant.nonce or grant.expires_at <= (at or timezone.now()):
        request.session.pop(GRANT_SESSION_KEY, None)
        raise ParticipantAccessError("Participant access has expired.")
    return grant


def consume_participant_grant(request, *, at=None):
    request.session.pop(GRANT_SESSION_KEY, None)
    now = at or timezone.now()
    request.session[COMPLETION_SESSION_KEY] = {
        "expires_at": _epoch(now + timedelta(seconds=settings.SURVEYHQ_COMPLETION_AGE_SECONDS))
    }


def has_completion_marker(request, *, at=None) -> bool:
    payload = request.session.get(COMPLETION_SESSION_KEY)
    if not isinstance(payload, dict) or set(payload) != {"expires_at"}:
        request.session.pop(COMPLETION_SESSION_KEY, None)
        return False
    try:
        valid = _from_epoch(payload["expires_at"]) > (at or timezone.now())
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        request.session.pop(COMPLETION_SESSION_KEY, None)
    return valid


def synchronize_target_survey(survey: Survey, *, at=None) -> Survey:
    now = at or timezone.now()
    if survey.status == Survey.Status.SCHEDULED and survey.starts_at and survey.starts_at <= now:
        try:
            survey = open_scheduled_survey(survey, at=now)
        except InvalidLifecycleTransition:
            survey.refresh_from_db()
    if (
        survey.status == Survey.Status.OPEN
        and survey.close_mode == Survey.CloseMode.SCHEDULED
        and survey.ends_at
        and survey.ends_at <= now
    ):
        try:
            survey = close_survey(survey, at=now, reason="scheduled")
        except InvalidLifecycleTransition:
            survey.refresh_from_db()
    return survey


def survey_accepts_new_grant(survey: Survey, *, at=None) -> bool:
    survey = synchronize_target_survey(survey, at=at)
    return survey.status == Survey.Status.OPEN and bool(survey.definition_checksum)


def _grant_submission_deadline(survey: Survey, grant: ParticipantGrant):
    deadline = grant.expires_at
    if survey.status in {Survey.Status.CLOSED, Survey.Status.ARCHIVED}:
        if not survey.closed_at or grant.issued_at > survey.closed_at:
            raise ParticipantAccessError("This survey is no longer accepting responses.")
        deadline = min(
            deadline,
            survey.closed_at + timedelta(seconds=settings.SURVEYHQ_CLOSE_GRACE_SECONDS),
        )
    elif survey.status != Survey.Status.OPEN:
        raise ParticipantAccessError("This survey is no longer accepting responses.")
    return deadline


@sensitive_variables()
def validate_granted_survey(grant: ParticipantGrant, *, for_submission=False, at=None) -> Survey:
    now = at or timezone.now()
    try:
        survey = Survey.objects.select_related("client", "project").prefetch_related(
            "questions__choices", "questions__matrix_rows"
        ).get(pk=grant.survey_id)
    except (Survey.DoesNotExist, ValidationError, ValueError) as exc:
        raise ParticipantAccessError("Participant access is unavailable.") from exc
    survey = synchronize_target_survey(survey, at=now)
    if grant.definition_checksum != survey.definition_checksum or not definition_matches_snapshot(survey):
        raise ParticipantAccessError("This survey is temporarily unavailable.")
    if survey.status not in {Survey.Status.OPEN, Survey.Status.CLOSED, Survey.Status.ARCHIVED}:
        raise ParticipantAccessError("Participant access is unavailable.")
    if now >= _grant_submission_deadline(survey, grant):
        raise ParticipantAccessError("This survey is no longer accepting responses.")
    return survey


def _decimal_step_validator(minimum, step):
    if step is None:
        return None

    def validate(value):
        origin = minimum or Decimal("0")
        if (value - origin) % step != 0:
            raise ValidationError(f"Enter a value in increments of {step}.")

    return validate


def _scale_values(configuration):
    minimum = Decimal(configuration["minimum"])
    maximum = Decimal(configuration["maximum"])
    step = Decimal(configuration["step"])
    count = int(((maximum - minimum) / step)) + 1
    if count <= 0 or count > 25:
        return []
    return [(format(minimum + step * index, "f"), format(minimum + step * index, "f")) for index in range(count)]


class ParticipantSurveyForm(forms.Form):
    def __init__(self, *args, survey: Survey, **kwargs):
        super().__init__(*args, **kwargs)
        self.survey = survey
        self.questions = mark_question_image_availability(
            list(survey.questions.prefetch_related("choices", "matrix_rows").order_by("position"))
        )
        self.specs = []
        self.pages = [[]]
        for question in self.questions:
            if question.question_type == SurveyQuestion.Type.PAGE_BREAK:
                if self.pages[-1]:
                    self.pages.append([])
                continue
            spec = {"question": question, "fields": [], "kind": question.question_type}
            if question.question_type in SurveyQuestion.STRUCTURAL_TYPES:
                self.specs.append(spec)
                self.pages[-1].append(spec)
                continue
            choices = list(question.choices.order_by("position"))
            config = question.configuration
            name = question.export_key
            common = {"label": question.prompt, "required": question.required, "help_text": question.help_text}
            if question.question_type == SurveyQuestion.Type.SHORT_TEXT:
                self.fields[name] = forms.CharField(
                    **common,
                    max_length=config.get("max_length"),
                    widget=forms.TextInput(attrs={"placeholder": config.get("placeholder", "")}),
                )
            elif question.question_type == SurveyQuestion.Type.LONG_TEXT:
                self.fields[name] = forms.CharField(
                    **common,
                    max_length=config.get("max_length"),
                    widget=forms.Textarea(attrs={"rows": 5, "placeholder": config.get("placeholder", "")}),
                )
            elif question.question_type == SurveyQuestion.Type.EMAIL:
                self.fields[name] = forms.EmailField(
                    **common, widget=forms.EmailInput(attrs={"placeholder": config.get("placeholder", "")})
                )
            elif question.question_type in {
                SurveyQuestion.Type.NUMBER,
                SurveyQuestion.Type.RATING,
                SurveyQuestion.Type.LINEAR_SCALE,
            }:
                minimum = Decimal(config["minimum"]) if config.get("minimum") is not None else None
                maximum = Decimal(config["maximum"]) if config.get("maximum") is not None else None
                step = Decimal(config["step"]) if config.get("step") is not None else None
                scale = _scale_values(config) if question.question_type == SurveyQuestion.Type.RATING else []
                validators = [validator for validator in [_decimal_step_validator(minimum, step)] if validator]
                if scale:
                    self.fields[name] = forms.TypedChoiceField(
                        **common, choices=scale, coerce=Decimal, widget=forms.RadioSelect
                    )
                    spec["scale"] = True
                else:
                    attrs = {"step": str(step) if step is not None else "any"}
                    if minimum is not None:
                        attrs["min"] = str(minimum)
                    if maximum is not None:
                        attrs["max"] = str(maximum)
                    widget = forms.HiddenInput() if question.question_type == SurveyQuestion.Type.LINEAR_SCALE else forms.NumberInput(attrs=attrs)
                    self.fields[name] = forms.DecimalField(
                        **common,
                        min_value=minimum,
                        max_value=maximum,
                        validators=validators,
                        max_digits=20,
                        decimal_places=6,
                        widget=widget,
                    )
                    if question.question_type == SurveyQuestion.Type.LINEAR_SCALE:
                        submitted = self.data.get(name) if self.is_bound else ""
                        midpoint = minimum + ((maximum - minimum) / 2)
                        spec["linear_scale"] = {
                            "minimum": format(minimum, "f"),
                            "maximum": format(maximum, "f"),
                            "step": format(step, "f"),
                            "initial": submitted or format(midpoint, "f"),
                            "answered": bool(submitted),
                        }
                spec["anchors"] = (config.get("low_anchor", ""), config.get("high_anchor", ""))
            elif question.question_type == SurveyQuestion.Type.DATE:
                self.fields[name] = forms.DateField(**common, widget=forms.DateInput(attrs={"type": "date"}))
            elif question.question_type == SurveyQuestion.Type.MULTIPLE_CHOICE:
                self.fields[name] = forms.MultipleChoiceField(
                    **common,
                    choices=[(choice.option_key, choice.label) for choice in choices],
                    widget=forms.CheckboxSelectMultiple,
                )
            elif question.question_type == SurveyQuestion.Type.DROPDOWN:
                self.fields[name] = forms.ChoiceField(
                    **common,
                    choices=[("", "Select an option")] + [(choice.option_key, choice.label) for choice in choices],
                )
            elif question.question_type in {
                SurveyQuestion.Type.SINGLE_CHOICE,
                SurveyQuestion.Type.YES_NO,
                SurveyQuestion.Type.LIKERT,
            }:
                self.fields[name] = forms.ChoiceField(
                    **common,
                    choices=[(choice.option_key, choice.label) for choice in choices],
                    widget=forms.RadioSelect,
                )
            elif question.question_type == SurveyQuestion.Type.MATRIX:
                for row in question.matrix_rows.order_by("position"):
                    field_name = f"{name}__{row.row_key}"
                    self.fields[field_name] = forms.ChoiceField(
                        label=row.label,
                        required=question.required,
                        choices=[(choice.option_key, choice.label) for choice in choices],
                        widget=forms.RadioSelect,
                    )
                    spec["fields"].append((row, field_name))
            elif question.question_type == SurveyQuestion.Type.RANKING:
                ranks = [("", "Not ranked")] + [(str(index), str(index)) for index in range(1, len(choices) + 1)]
                for choice in choices:
                    field_name = f"{name}__{choice.option_key}"
                    self.fields[field_name] = forms.TypedChoiceField(
                        label=choice.label,
                        required=False,
                        choices=ranks,
                        coerce=int,
                        empty_value=None,
                    )
                    spec["fields"].append((choice, field_name))
            if not spec["fields"]:
                spec["fields"].append((None, name))
            self.specs.append(spec)
            self.pages[-1].append(spec)
        self.pages = [page for page in self.pages if page]
        for spec in self.specs:
            spec["bound_fields"] = [(item, self[field_name]) for item, field_name in spec["fields"]]

    @sensitive_variables()
    def clean(self):
        cleaned = super().clean()
        for spec in self.specs:
            question = spec["question"]
            if question.question_type != SurveyQuestion.Type.RANKING:
                continue
            values = [cleaned.get(name) for _choice, name in spec["fields"]]
            provided = [value for value in values if value is not None]
            if not provided and not question.required:
                continue
            names = [name for _choice, name in spec["fields"]]
            if len(provided) != len(values):
                for name in names:
                    self.add_error(name, "Rank every option or leave the optional ranking blank.")
                continue
            if len(set(provided)) != len(provided) or set(provided) != set(range(1, len(values) + 1)):
                for name in names:
                    self.add_error(name, "Use each rank exactly once.")
        return cleaned


def _choice_map(question):
    return {choice.option_key: choice for choice in question.choices.order_by("position")}


@transaction.atomic
@sensitive_variables()
def submit_participant_response(*, grant: ParticipantGrant, form: ParticipantSurveyForm, request, at=None):
    now = at or timezone.now()
    if str(form.survey.pk) != grant.survey_id or not form.is_bound or not form.is_valid():
        raise ValidationError("A complete, valid answer set is required before submission.")
    survey = Survey.objects.select_for_update().get(pk=grant.survey_id)
    survey = synchronize_target_survey(survey, at=now)
    if grant.definition_checksum != survey.definition_checksum or not definition_matches_snapshot(survey):
        raise ParticipantAccessError("This survey is temporarily unavailable.")
    if now >= _grant_submission_deadline(survey, grant):
        raise ParticipantAccessError("This survey is no longer accepting responses.")
    nonce_hash = hashlib.sha256(grant.nonce.encode("utf-8")).hexdigest()
    try:
        response = SurveyResponse.objects.create(
            survey=survey,
            started_at=grant.issued_at,
            submitted_at=now,
            access_nonce_hash=nonce_hash,
            definition_checksum=survey.definition_checksum,
            source=SurveyResponse.Source.WEBVIEW if is_mobile_app_request(request) else SurveyResponse.Source.BROWSER,
        )
    except IntegrityError as exc:
        raise DuplicateParticipantSubmission from exc

    questions = {question.export_key: question for question in survey.questions.prefetch_related("choices", "matrix_rows")}
    for spec in form.specs:
        question = questions[spec["question"].export_key]
        question_type = question.question_type
        if question_type in SurveyQuestion.STRUCTURAL_TYPES:
            continue
        choices = _choice_map(question)
        if question_type == SurveyQuestion.Type.MATRIX:
            rows = {row.row_key: row for row in question.matrix_rows.order_by("position")}
            for _row, field_name in spec["fields"]:
                value = form.cleaned_data.get(field_name)
                if not value:
                    continue
                row_key = field_name.split("__", 1)[1]
                choice = choices[value]
                answer = SurveyAnswer.objects.create(
                    response=response,
                    question=question,
                    matrix_row=rows[row_key],
                    numeric_value=choice.numeric_value,
                )
                SurveyAnswerSelection.objects.create(answer=answer, choice=choice)
            continue
        if question_type == SurveyQuestion.Type.RANKING:
            ranked = [(choice, form.cleaned_data.get(field_name)) for choice, field_name in spec["fields"]]
            if not any(rank is not None for _choice, rank in ranked):
                continue
            answer = SurveyAnswer.objects.create(response=response, question=question)
            for source_choice, rank in ranked:
                SurveyAnswerSelection.objects.create(answer=answer, choice=choices[source_choice.option_key], rank=rank)
            continue
        field_name = spec["fields"][0][1]
        value = form.cleaned_data.get(field_name)
        if value in (None, "", []):
            continue
        if question_type in {SurveyQuestion.Type.SHORT_TEXT, SurveyQuestion.Type.LONG_TEXT, SurveyQuestion.Type.EMAIL}:
            SurveyAnswer.objects.create(response=response, question=question, text_value=value)
        elif question_type in {SurveyQuestion.Type.NUMBER, SurveyQuestion.Type.RATING, SurveyQuestion.Type.LINEAR_SCALE}:
            SurveyAnswer.objects.create(response=response, question=question, numeric_value=value)
        elif question_type == SurveyQuestion.Type.DATE:
            SurveyAnswer.objects.create(response=response, question=question, date_value=value)
        elif question_type == SurveyQuestion.Type.MULTIPLE_CHOICE:
            answer = SurveyAnswer.objects.create(response=response, question=question)
            for option_key in value:
                SurveyAnswerSelection.objects.create(answer=answer, choice=choices[option_key])
        else:
            choice = choices[value]
            answer = SurveyAnswer.objects.create(
                response=response,
                question=question,
                numeric_value=choice.numeric_value if question_type == SurveyQuestion.Type.LIKERT else None,
            )
            SurveyAnswerSelection.objects.create(answer=answer, choice=choice)
    record_survey_event(
        survey=survey,
        event_type="response_submitted",
        summary=f"A response was submitted for {survey.display_identity}.",
        metadata={"response_id": str(response.pk), "source": response.source},
    )
    return response
