from __future__ import annotations

from calendar import month_name
from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import RelatedFieldWidgetWrapper
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.clients.models import Client, Project

from .builder import LIKERT_PRESETS
from .configuration import normalize_question_configuration
from .media import prepare_question_image
from .models import Survey, SurveyQuestion


INPUT_CLASS = "svhq-input"
SELECT_CLASS = "svhq-select"
TEXTAREA_CLASS = "svhq-textarea"


class SurveyMetadataForm(forms.Form):
    START_IMMEDIATE = "immediate"
    START_SCHEDULED = "scheduled"

    client = forms.ModelChoiceField(queryset=Client.objects.order_by("organization_name", "contact_name"))
    project = forms.ModelChoiceField(queryset=Project.objects.none(), required=False)
    reporting_month = forms.TypedChoiceField(
        choices=[(number, month_name[number]) for number in range(1, 13)], coerce=int
    )
    reporting_year = forms.IntegerField(min_value=1000, max_value=9999)
    title = forms.CharField(max_length=240)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    category = forms.CharField(max_length=120, required=False)
    collection_mode = forms.ChoiceField(
        choices=Survey.CollectionMode.choices,
        initial=Survey.CollectionMode.ANONYMOUS,
        required=False,
        label="Collection Mode",
        help_text=(
            "Anonymous mode prohibits Email-type questions and requires administrators to avoid "
            "requesting direct identifiers in any prompt."
        ),
    )
    show_client_name_to_participants = forms.BooleanField(
        required=False,
        label="Show sponsoring Client to participants",
        help_text="When enabled, the retained Client name appears after a participant enters a valid code.",
    )
    start_mode = forms.ChoiceField(
        choices=[(START_IMMEDIATE, "Open immediately when published"), (START_SCHEDULED, "Scheduled start")]
    )
    starts_at = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    close_mode = forms.ChoiceField(choices=Survey.CloseMode.choices)
    ends_at = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )

    def __init__(self, *args, request=None, survey=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.survey = survey
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", TEXTAREA_CLASS if isinstance(field.widget, forms.Textarea) else INPUT_CLASS)
        self.fields["client"].widget.attrs.update({"class": SELECT_CLASS, "data-surveyhq-client": ""})
        self.fields["project"].widget.attrs.update({"class": SELECT_CLASS, "data-surveyhq-project": ""})
        self.fields["reporting_month"].widget.attrs["class"] = SELECT_CLASS
        self.fields["collection_mode"].widget.attrs["class"] = SELECT_CLASS
        self.fields["start_mode"].widget.attrs["class"] = SELECT_CLASS
        self.fields["close_mode"].widget.attrs["class"] = SELECT_CLASS
        self.fields["category"].widget.attrs["list"] = "surveyhq-category-suggestions"

        client_id = None
        if self.is_bound:
            client_id = self.data.get(self.add_prefix("client"))
        elif survey and survey.client_id:
            client_id = survey.client_id
        if client_id:
            self.fields["project"].queryset = Project.objects.filter(client_id=client_id).order_by("name")

        if survey and not self.is_bound:
            self.initial.update(
                {
                    "client": survey.client,
                    "project": survey.project,
                    "reporting_month": survey.reporting_month,
                    "reporting_year": survey.reporting_year,
                    "title": survey.title,
                    "description": survey.description,
                    "category": survey.category,
                    "collection_mode": survey.collection_mode or Survey.CollectionMode.ANONYMOUS,
                    "show_client_name_to_participants": survey.show_client_name_to_participants,
                    "start_mode": self.START_SCHEDULED if survey.starts_at else self.START_IMMEDIATE,
                    "starts_at": survey.starts_at,
                    "close_mode": survey.close_mode,
                    "ends_at": survey.ends_at,
                }
            )
        elif not self.is_bound:
            now = timezone.localtime()
            self.initial.setdefault("reporting_month", now.month)
            self.initial.setdefault("reporting_year", now.year)
            self.initial.setdefault("start_mode", self.START_IMMEDIATE)
            self.initial.setdefault("close_mode", Survey.CloseMode.MANUAL)
            self.initial.setdefault("collection_mode", Survey.CollectionMode.ANONYMOUS)

        if request is not None:
            relation = Survey._meta.get_field("client").remote_field
            self.fields["client"].widget = RelatedFieldWidgetWrapper(
                self.fields["client"].widget,
                relation,
                admin.site,
                can_add_related=request.user.has_perm("clients.add_client"),
                can_change_related=False,
                can_delete_related=False,
                can_view_related=False,
            )

    def clean(self):
        cleaned = super().clean()
        cleaned["collection_mode"] = (
            cleaned.get("collection_mode") or Survey.CollectionMode.ANONYMOUS
        )
        client = cleaned.get("client")
        project = cleaned.get("project")
        if project and client and project.client_id != client.pk:
            self.add_error("project", "The selected project must belong to the selected client.")
        start_mode = cleaned.get("start_mode")
        starts_at = cleaned.get("starts_at")
        close_mode = cleaned.get("close_mode")
        ends_at = cleaned.get("ends_at")
        now = timezone.now()
        if start_mode == self.START_SCHEDULED:
            if not starts_at:
                self.add_error("starts_at", "Choose a scheduled start time.")
            elif starts_at <= now:
                self.add_error("starts_at", "The scheduled start must be in the future.")
        else:
            cleaned["starts_at"] = None
            starts_at = None
        if close_mode == Survey.CloseMode.SCHEDULED:
            if not ends_at:
                self.add_error("ends_at", "Choose a scheduled end time.")
            elif ends_at <= now:
                self.add_error("ends_at", "The scheduled end must be in the future.")
            elif starts_at and ends_at <= starts_at:
                self.add_error("ends_at", "The scheduled end must be after the scheduled start.")
        else:
            cleaned["ends_at"] = None
        return cleaned

    def service_values(self):
        return {
            key: self.cleaned_data[key]
            for key in (
                "client",
                "project",
                "reporting_month",
                "reporting_year",
                "title",
                "description",
                "category",
                "collection_mode",
                "show_client_name_to_participants",
                "starts_at",
                "close_mode",
                "ends_at",
            )
        }


class QuestionForm(forms.Form):
    question_type = forms.ChoiceField(choices=SurveyQuestion.Type.choices)
    prompt = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    help_text = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    required = forms.BooleanField(required=False)
    placeholder = forms.CharField(required=False, max_length=500)
    max_length = forms.IntegerField(required=False, min_value=1)
    minimum = forms.DecimalField(required=False, max_digits=20, decimal_places=6)
    maximum = forms.DecimalField(required=False, max_digits=20, decimal_places=6)
    step = forms.DecimalField(required=False, max_digits=20, decimal_places=6)
    low_anchor = forms.CharField(required=False, max_length=200)
    high_anchor = forms.CharField(required=False, max_length=200)
    likert_preset = forms.ChoiceField(
        required=False,
        choices=[("", "Custom / add options manually")]
        + [(key, "5-Point Agreement" if key == "five_agreement" else "7-Point Agreement") for key in LIKERT_PRESETS],
    )
    question_image = forms.FileField(
        required=False,
        label="Question Image — Optional",
        help_text="JPEG, PNG, or static WebP; maximum 8 MB.",
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    image_alt_text = forms.CharField(required=False, max_length=500, label="Alt Text")
    image_is_decorative = forms.BooleanField(required=False, label="This image is decorative")
    remove_image = forms.BooleanField(required=False, label="Remove current image")

    def __init__(self, *args, question=None, survey=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.question = question
        self.survey = survey or (question.survey if question else None)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXTAREA_CLASS if isinstance(field.widget, forms.Textarea) else INPUT_CLASS)
        self.fields["question_type"].widget.attrs.update({"class": SELECT_CLASS, "data-question-type": ""})
        self.fields["likert_preset"].widget.attrs["class"] = SELECT_CLASS
        if question and not self.is_bound:
            self.initial.update(
                {
                    "question_type": question.question_type,
                    "prompt": question.prompt,
                    "help_text": question.help_text,
                    "required": question.required,
                    **question.configuration,
                    "image_alt_text": question.image_alt_text,
                    "image_is_decorative": question.image_is_decorative,
                }
            )
        if question:
            self.fields["question_type"].disabled = True
            self.fields["question_type"].required = False
            if question.question_type != SurveyQuestion.Type.LIKERT or question.choices.exists():
                self.fields["likert_preset"].widget = forms.HiddenInput()
            if not question.image:
                self.fields["remove_image"].widget = forms.HiddenInput()
        elif self.survey and self.survey.collection_mode == Survey.CollectionMode.ANONYMOUS:
            self.fields["question_type"].choices = [
                choice
                for choice in SurveyQuestion.Type.choices
                if choice[0] != SurveyQuestion.Type.EMAIL
            ]

    def clean(self):
        cleaned = super().clean()
        question_type = self.question.question_type if self.question else cleaned.get("question_type")
        if not question_type:
            return cleaned
        if question_type in SurveyQuestion.STRUCTURAL_TYPES:
            cleaned["required"] = False
        config = {}
        if question_type in {SurveyQuestion.Type.SHORT_TEXT, SurveyQuestion.Type.LONG_TEXT}:
            config = {"placeholder": cleaned.get("placeholder"), "max_length": cleaned.get("max_length")}
        elif question_type == SurveyQuestion.Type.EMAIL:
            config = {"placeholder": cleaned.get("placeholder")}
        elif question_type in {
            SurveyQuestion.Type.NUMBER,
            SurveyQuestion.Type.RATING,
            SurveyQuestion.Type.LINEAR_SCALE,
        }:
            config = {
                "minimum": cleaned.get("minimum"),
                "maximum": cleaned.get("maximum"),
                "step": cleaned.get("step"),
                "low_anchor": cleaned.get("low_anchor"),
                "high_anchor": cleaned.get("high_anchor"),
            }
        config = {key: value for key, value in config.items() if value not in (None, "")}
        try:
            cleaned["configuration"] = normalize_question_configuration(question_type, config)
        except ValidationError as exc:
            self.add_error(None, exc)
        cleaned["question_type"] = question_type
        upload = cleaned.get("question_image")
        remove_image = bool(cleaned.get("remove_image"))
        if question_type == SurveyQuestion.Type.PAGE_BREAK and (upload or (self.question and self.question.image)):
            self.add_error("question_image", "Page Break records cannot include an image.")
        if upload and remove_image:
            self.add_error("remove_image", "Choose either a replacement image or Remove, not both.")
        prepared = None
        if upload:
            try:
                prepared = prepare_question_image(upload)
            except ValidationError as exc:
                self.add_error("question_image", exc)
        has_image = bool(prepared or (self.question and self.question.image and not remove_image))
        alt_text = (cleaned.get("image_alt_text") or "").strip()
        decorative = bool(cleaned.get("image_is_decorative"))
        if has_image and decorative and alt_text:
            self.add_error("image_alt_text", "Decorative images must use empty alt text.")
        elif has_image and not decorative and not alt_text:
            self.add_error("image_alt_text", "Provide alt text or mark the image decorative.")
        elif not has_image and (alt_text or decorative):
            self.add_error("question_image", "Upload an image before configuring its accessibility text.")
        cleaned["prepared_image"] = prepared
        return cleaned


class ChoiceForm(forms.Form):
    label = forms.CharField(max_length=500)
    numeric_value = forms.DecimalField(required=False, max_digits=12, decimal_places=4)

    def __init__(self, *args, choice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["label"].widget.attrs["class"] = INPUT_CLASS
        self.fields["numeric_value"].widget.attrs["class"] = INPUT_CLASS
        if choice and not self.is_bound:
            self.initial.update({"label": choice.label, "numeric_value": choice.numeric_value})


class MatrixRowForm(forms.Form):
    label = forms.CharField(max_length=500)

    def __init__(self, *args, row=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["label"].widget.attrs["class"] = INPUT_CLASS
        if row and not self.is_bound:
            self.initial["label"] = row.label


class ReportGenerationForm(forms.Form):
    palette = forms.ChoiceField(label="Report Palette")
    confirm = forms.BooleanField(
        label="Generate an immutable official report using the current submitted responses"
    )

    def __init__(self, *args, **kwargs):
        from .reports import REPORT_PALETTES

        super().__init__(*args, **kwargs)
        self.fields["palette"].choices = [
            (key, values["label"]) for key, values in REPORT_PALETTES.items()
        ]
        self.fields["palette"].widget.attrs["class"] = SELECT_CLASS


class SurveyDuplicateForm(SurveyMetadataForm):
    copy_client = forms.BooleanField(required=False, initial=True)
    copy_project = forms.BooleanField(required=False)
    copy_reporting_period = forms.BooleanField(required=False, initial=True)
    copy_availability = forms.BooleanField(required=False)

    def __init__(self, *args, source=None, **kwargs):
        self.source = source
        super().__init__(*args, **kwargs)
        if source and not self.is_bound:
            self.initial.update(
                {
                    "client": source.client,
                    "project": None,
                    "title": f"{source.title} Copy",
                    "description": source.description,
                    "category": source.category,
                    "reporting_month": source.reporting_month,
                    "reporting_year": source.reporting_year,
                    "start_mode": self.START_IMMEDIATE,
                    "close_mode": Survey.CloseMode.MANUAL,
                }
            )


class TemplateMetadataForm(forms.Form):
    name = forms.CharField(max_length=240)
    category = forms.CharField(max_length=120, required=False)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, template=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = TEXTAREA_CLASS if isinstance(field.widget, forms.Textarea) else INPUT_CLASS
        if template and not self.is_bound:
            self.initial.update(
                {"name": template.name, "category": template.category, "description": template.description}
            )


class ConfirmationForm(forms.Form):
    confirm = forms.BooleanField(required=True, label="I understand and confirm this action")
