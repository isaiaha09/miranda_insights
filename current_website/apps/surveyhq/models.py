from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from calendar import month_name

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from apps.clients.models import Client, Project

from .codes import generate_survey_code, is_valid_survey_code
from .configuration import normalize_question_configuration
from .exceptions import SurveyStructureLocked


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def checksum_json(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def survey_question_image_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower() or ".bin"
    return f"surveyhq/question-images/{instance.survey_id}/{instance.pk}/{uuid.uuid4().hex}{extension}"


def generate_participant_entry_token():
    return secrets.token_urlsafe(32)


class RetentionProtectedSurveyQuerySet(models.QuerySet):
    LIFECYCLE_FIELDS = {
        "access_code",
        "status",
        "published_at",
        "opened_at",
        "closed_at",
        "archived_at",
        "retention_until",
        "definition_snapshot",
        "definition_checksum",
    }

    def update(self, **kwargs):
        if self.LIFECYCLE_FIELDS.intersection(kwargs):
            raise ValidationError("Survey lifecycle and publication fields must be changed through SurveyHQ services.")
        if Survey.PUBLISHED_METADATA_FIELDS.intersection(kwargs) and self.filter(published_at__isnull=False).exists():
            raise SurveyStructureLocked("Published survey metadata is read-only; duplicate it into a new Draft.")
        return super().update(**kwargs)

    def delete(self):
        if self.exclude(status="draft", published_at__isnull=True).exists():
            from .exceptions import SurveyRetentionProtected

            raise SurveyRetentionProtected("Published surveys are retained and must be archived instead of deleted.")
        return super().delete()


class Survey(models.Model):
    PUBLISHED_METADATA_FIELDS = {
        "client_id",
        "project_id",
        "client_name_snapshot",
        "project_name_snapshot",
        "title",
        "description",
        "category",
        "collection_mode",
        "reporting_month",
        "reporting_year",
        "starts_at",
        "close_mode",
        "ends_at",
        "source_survey_id",
        "source_template_id",
        "show_client_name_to_participants",
    }
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        ARCHIVED = "archived", "Archived"

    class CloseMode(models.TextChoices):
        MANUAL = "manual", "Manual"
        SCHEDULED = "scheduled", "Scheduled"
        INDEFINITE = "indefinite", "Indefinite"

    class CollectionMode(models.TextChoices):
        ANONYMOUS = "anonymous", "Anonymous"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surveys",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surveys",
    )
    client_name_snapshot = models.CharField(max_length=240, blank=True)
    project_name_snapshot = models.CharField(max_length=180, blank=True)
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=120, blank=True)
    collection_mode = models.CharField(
        max_length=24,
        choices=CollectionMode.choices,
        default=CollectionMode.ANONYMOUS,
        null=True,
        blank=True,
    )
    show_client_name_to_participants = models.BooleanField(default=False)
    reporting_month = models.PositiveSmallIntegerField()
    reporting_year = models.PositiveSmallIntegerField()
    access_code = models.CharField(max_length=6, unique=True, default=generate_survey_code, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    starts_at = models.DateTimeField(null=True, blank=True)
    close_mode = models.CharField(max_length=16, choices=CloseMode.choices, default=CloseMode.MANUAL)
    ends_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    retention_until = models.DateTimeField(null=True, blank=True)
    definition_snapshot = models.JSONField(default=dict, blank=True)
    definition_checksum = models.CharField(max_length=64, blank=True)
    source_survey = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derived_surveys",
    )
    source_template = models.ForeignKey(
        "SurveyTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surveys",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_surveys",
        limit_choices_to={"is_staff": True},
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_surveys",
        limit_choices_to={"is_staff": True},
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = RetentionProtectedSurveyQuerySet.as_manager()

    class Meta:
        ordering = ["-reporting_year", "-reporting_month", "title"]
        permissions = [
            ("access_surveyhq", "Can access SurveyHQ"),
            ("publish_survey", "Can publish SurveyHQ surveys"),
            ("close_survey", "Can close SurveyHQ surveys"),
            ("reopen_survey", "Can reopen SurveyHQ surveys"),
            ("archive_survey", "Can archive SurveyHQ surveys"),
            ("duplicate_survey", "Can duplicate SurveyHQ surveys"),
            ("delete_eligible_survey", "Can delete eligible draft SurveyHQ surveys"),
            ("view_live_report", "Can view live SurveyHQ reports"),
            ("export_survey_data", "Can export SurveyHQ data"),
            ("generate_survey_report", "Can generate official SurveyHQ reports"),
            ("rotate_survey_code", "Can rotate SurveyHQ survey codes"),
            ("manage_participant_access", "Can manage SurveyHQ participant access resources"),
            ("manage_survey_templates", "Can manage SurveyHQ templates"),
            ("view_surveyhq_audit", "Can view SurveyHQ audit history"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(reporting_month__gte=1, reporting_month__lte=12),
                name="svhq_survey_month_range",
            ),
            models.CheckConstraint(
                condition=Q(reporting_year__gte=1000, reporting_year__lte=9999),
                name="svhq_survey_year_range",
            ),
            models.CheckConstraint(
                condition=~Q(status="scheduled") | Q(starts_at__isnull=False),
                name="svhq_scheduled_has_start",
            ),
            models.CheckConstraint(
                condition=~Q(close_mode="scheduled") | Q(ends_at__isnull=False),
                name="svhq_scheduled_has_end",
            ),
            models.CheckConstraint(
                condition=Q(starts_at__isnull=True) | Q(ends_at__isnull=True) | Q(ends_at__gt=models.F("starts_at")),
                name="svhq_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(status="draft")
                | (Q(published_at__isnull=False) & ~Q(definition_checksum="")),
                name="svhq_published_has_hash",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=["closed", "archived"]) | Q(closed_at__isnull=False),
                name="svhq_closed_has_time",
            ),
            models.CheckConstraint(
                condition=~Q(status="archived") | Q(archived_at__isnull=False),
                name="svhq_archived_has_time",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "starts_at"], name="svhq_status_start_idx"),
            models.Index(fields=["status", "ends_at"], name="svhq_status_end_idx"),
            models.Index(fields=["client", "reporting_year", "reporting_month"], name="svhq_client_period_idx"),
            models.Index(fields=["retention_until"], name="svhq_retention_idx"),
        ]

    def __str__(self):
        return self.display_identity

    @property
    def live_client_name(self) -> str:
        if not self.client_id:
            return self.client_name_snapshot or "Unassigned Client"
        return self.client.organization_name or self.client.contact_name

    @property
    def identity_client_name(self) -> str:
        if self.published_at and self.client_name_snapshot:
            return self.client_name_snapshot
        return self.live_client_name

    @property
    def display_identity(self) -> str:
        month = month_name[self.reporting_month] if 1 <= self.reporting_month <= 12 else str(self.reporting_month)
        return f"{month} {self.reporting_year} · {self.identity_client_name} · {self.title}"

    @property
    def is_structure_locked(self) -> bool:
        return self.status != self.Status.DRAFT or bool(self.published_at)

    @property
    def is_retention_locked(self) -> bool:
        return bool(self.published_at) or (
            self.retention_until is not None and self.retention_until > timezone.now()
        )

    @property
    def effective_availability(self) -> str:
        now = timezone.now()
        if self.status == self.Status.SCHEDULED and self.starts_at and self.starts_at <= now:
            return self.Status.OPEN
        if (
            self.status == self.Status.OPEN
            and self.close_mode == self.CloseMode.SCHEDULED
            and self.ends_at
            and self.ends_at <= now
        ):
            return self.Status.CLOSED
        return self.status

    def clean(self):
        errors = {}
        if not is_valid_survey_code(self.access_code):
            errors["access_code"] = "Survey codes must contain six approved characters, including a letter and number."
        if self.project_id and self.client_id and self.project.client_id != self.client_id:
            errors["project"] = "The selected project must belong to the selected client."
        if self.project_id and not self.client_id:
            errors["client"] = "A client is required when a project is selected."
        if self.close_mode == self.CloseMode.SCHEDULED and not self.ends_at:
            errors["ends_at"] = "A scheduled close requires an end time."
        if self.status == self.Status.SCHEDULED and not self.starts_at:
            errors["starts_at"] = "A scheduled survey requires a start time."
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "The end time must be later than the start time."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        allow_locked_metadata = kwargs.pop("allow_locked_metadata", False)
        if self.pk and not allow_locked_metadata:
            original = type(self).objects.filter(pk=self.pk).values(
                "published_at", *self.PUBLISHED_METADATA_FIELDS
            ).first()
            if original and original["published_at"]:
                changed = [field for field in self.PUBLISHED_METADATA_FIELDS if original[field] != getattr(self, field)]
                if changed:
                    raise SurveyStructureLocked(
                        "Published survey metadata is read-only; duplicate it into a new Draft."
                    )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_retention_locked or self.status != self.Status.DRAFT:
            from .exceptions import SurveyRetentionProtected

            raise SurveyRetentionProtected("Published surveys are retained and must be archived instead of deleted.")
        return super().delete(*args, **kwargs)


class SurveyQuestionQuerySet(models.QuerySet):
    def _assert_editable(self):
        if self.exclude(survey__status="draft", survey__published_at__isnull=True).exists():
            raise SurveyStructureLocked("Published survey structure cannot be changed; duplicate it into a new draft.")

    def update(self, **kwargs):
        self._assert_editable()
        if "question_type" in kwargs and self.exists():
            raise ValidationError("Question type is fixed after creation.")
        return super().update(**kwargs)

    def delete(self):
        self._assert_editable()
        return super().delete()

    def bulk_update(self, objs, fields, batch_size=None):
        objs = list(objs)
        survey_ids = {obj.survey_id for obj in objs}
        if Survey.objects.filter(pk__in=survey_ids).exclude(status="draft", published_at__isnull=True).exists():
            raise SurveyStructureLocked("Published survey structure cannot be changed; duplicate it into a new draft.")
        if "question_type" in fields and objs:
            raise ValidationError("Question type is fixed after creation.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        survey_ids = {obj.survey_id for obj in objs}
        if Survey.objects.filter(pk__in=survey_ids).exclude(status="draft", published_at__isnull=True).exists():
            raise SurveyStructureLocked("Published survey structure cannot be changed; duplicate it into a new draft.")
        return super().bulk_create(objs, **kwargs)


class SurveyQuestion(models.Model):
    class Type(models.TextChoices):
        SHORT_TEXT = "short_text", "Short text"
        LONG_TEXT = "long_text", "Long text"
        EMAIL = "email", "Email"
        NUMBER = "number", "Number"
        SINGLE_CHOICE = "single_choice", "Single choice"
        MULTIPLE_CHOICE = "multiple_choice", "Multiple choice"
        DROPDOWN = "dropdown", "Dropdown"
        YES_NO = "yes_no", "Yes / No"
        LIKERT = "likert", "Likert scale"
        RATING = "rating", "Rating"
        LINEAR_SCALE = "linear_scale", "Linear numeric scale"
        MATRIX = "matrix", "Matrix / grid"
        RANKING = "ranking", "Ranking"
        DATE = "date", "Date"
        HEADING = "heading", "Heading"
        DESCRIPTION = "description", "Description / information"
        PAGE_BREAK = "page_break", "Page break"

    STRUCTURAL_TYPES = {Type.HEADING, Type.DESCRIPTION, Type.PAGE_BREAK}
    CHOICE_TYPES = {
        Type.SINGLE_CHOICE,
        Type.MULTIPLE_CHOICE,
        Type.DROPDOWN,
        Type.YES_NO,
        Type.LIKERT,
        Type.MATRIX,
        Type.RANKING,
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(Survey, on_delete=models.PROTECT, related_name="questions")
    export_key = models.CharField(max_length=80)
    position = models.PositiveIntegerField()
    question_type = models.CharField(max_length=32, choices=Type.choices)
    prompt = models.TextField()
    help_text = models.TextField(blank=True)
    required = models.BooleanField(default=False)
    configuration = models.JSONField(default=dict, blank=True)
    image = models.ImageField(upload_to=survey_question_image_path, blank=True, max_length=500)
    image_original_name = models.CharField(max_length=255, blank=True)
    image_content_type = models.CharField(max_length=40, blank=True)
    image_checksum = models.CharField(max_length=64, blank=True)
    image_byte_size = models.PositiveBigIntegerField(default=0)
    image_width = models.PositiveIntegerField(default=0)
    image_height = models.PositiveIntegerField(default=0)
    image_alt_text = models.CharField(max_length=500, blank=True)
    image_is_decorative = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = SurveyQuestionQuerySet.as_manager()

    class Meta:
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["survey", "position"], name="svhq_question_position_uq"),
            models.UniqueConstraint(fields=["survey", "export_key"], name="svhq_question_key_uq"),
            models.CheckConstraint(
                condition=~Q(question_type__in=["heading", "description", "page_break"], required=True),
                name="svhq_structural_not_required",
            ),
            models.CheckConstraint(
                condition=~Q(question_type="page_break") | Q(image=""),
                name="svhq_page_break_no_image",
            ),
            models.CheckConstraint(
                condition=~Q(image_is_decorative=True) | Q(image_alt_text=""),
                name="svhq_decorative_alt_empty",
            ),
            models.CheckConstraint(
                condition=Q(image="") | Q(image_is_decorative=True) | ~Q(image_alt_text=""),
                name="svhq_image_alt_required",
            ),
        ]
        indexes = [models.Index(fields=["survey", "position"], name="svhq_question_order_idx")]

    def __str__(self):
        return f"{self.export_key}: {self.prompt[:80]}"

    def clean(self):
        try:
            self.configuration = normalize_question_configuration(self.question_type, self.configuration)
        except ValidationError as exc:
            raise ValidationError({"configuration": exc.messages}) from exc
        if self.question_type in self.STRUCTURAL_TYPES and self.required:
            raise ValidationError({"required": "Structural content cannot require an answer."})
        if self.question_type == self.Type.PAGE_BREAK and self.image:
            raise ValidationError({"image": "Page Break records cannot include an image."})
        if self.image:
            if not self.image_is_decorative and not self.image_alt_text.strip():
                raise ValidationError({"image_alt_text": "Provide alt text or mark the image decorative."})
            if self.image_is_decorative and self.image_alt_text.strip():
                raise ValidationError({"image_alt_text": "Decorative images must use empty alt text."})
        elif any(
            (
                self.image_original_name,
                self.image_content_type,
                self.image_checksum,
                self.image_byte_size,
                self.image_width,
                self.image_height,
                self.image_alt_text,
                self.image_is_decorative,
            )
        ):
            raise ValidationError({"image": "Image metadata requires an image file."})

    def _assert_structure_editable(self):
        survey_ids = {self.survey_id}
        if self.pk:
            original_survey_id = type(self).objects.filter(pk=self.pk).values_list("survey_id", flat=True).first()
            if original_survey_id:
                survey_ids.add(original_survey_id)
        if Survey.objects.filter(pk__in=survey_ids).exclude(status=Survey.Status.DRAFT, published_at__isnull=True).exists():
            raise SurveyStructureLocked("Published survey structure cannot be changed; duplicate it into a new draft.")

    def save(self, *args, **kwargs):
        self._assert_structure_editable()
        if self.pk:
            original_type = type(self).objects.filter(pk=self.pk).values_list("question_type", flat=True).first()
            if original_type and original_type != self.question_type:
                raise ValidationError({"question_type": "Question type is fixed after creation."})
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._assert_structure_editable()
        return super().delete(*args, **kwargs)


class QuestionChildQuerySet(models.QuerySet):
    def _assert_editable(self):
        if self.exclude(question__survey__status="draft", question__survey__published_at__isnull=True).exists():
            raise SurveyStructureLocked("Published survey structure cannot be changed; duplicate it into a new draft.")

    def update(self, **kwargs):
        self._assert_editable()
        return super().update(**kwargs)

    def delete(self):
        self._assert_editable()
        return super().delete()

    def bulk_update(self, objs, fields, batch_size=None):
        objs = list(objs)
        survey_ids = {obj.question.survey_id for obj in objs}
        if Survey.objects.filter(pk__in=survey_ids).exclude(status="draft", published_at__isnull=True).exists():
            raise SurveyStructureLocked("Published survey structure cannot be changed; duplicate it into a new draft.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        survey_ids = {obj.question.survey_id for obj in objs}
        if Survey.objects.filter(pk__in=survey_ids).exclude(status="draft", published_at__isnull=True).exists():
            raise SurveyStructureLocked("Published survey structure cannot be changed; duplicate it into a new draft.")
        return super().bulk_create(objs, **kwargs)


class QuestionChildMixin(models.Model):
    class Meta:
        abstract = True

    def _assert_structure_editable(self):
        survey_ids = {self.question.survey_id}
        if self.pk:
            original_survey_id = (
                type(self).objects.filter(pk=self.pk).values_list("question__survey_id", flat=True).first()
            )
            if original_survey_id:
                survey_ids.add(original_survey_id)
        if Survey.objects.filter(pk__in=survey_ids).exclude(status=Survey.Status.DRAFT, published_at__isnull=True).exists():
            raise SurveyStructureLocked("Published survey structure cannot be changed; duplicate it into a new draft.")

    def save(self, *args, **kwargs):
        self._assert_structure_editable()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._assert_structure_editable()
        return super().delete(*args, **kwargs)


class SurveyChoice(QuestionChildMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(SurveyQuestion, on_delete=models.PROTECT, related_name="choices")
    option_key = models.CharField(max_length=80)
    label = models.CharField(max_length=500)
    numeric_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    position = models.PositiveIntegerField()
    objects = QuestionChildQuerySet.as_manager()

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["question", "position"], name="svhq_choice_position_uq"),
            models.UniqueConstraint(fields=["question", "option_key"], name="svhq_choice_key_uq"),
        ]
        indexes = [models.Index(fields=["question", "position"], name="svhq_choice_order_idx")]

    def __str__(self):
        return self.label

    def clean(self):
        if self.question_id and self.question.question_type not in SurveyQuestion.CHOICE_TYPES:
            raise ValidationError({"question": "This question type does not accept choices."})
        if self.pk and self.question_id and self.question.question_type == SurveyQuestion.Type.YES_NO:
            original = type(self).objects.filter(pk=self.pk).values(
                "option_key", "label", "numeric_value", "position"
            ).first()
            if original and any(original[field] != getattr(self, field) for field in original):
                raise ValidationError("Yes/No choices are fixed and cannot be customized.")

    def delete(self, *args, **kwargs):
        if self.question_id and self.question.question_type == SurveyQuestion.Type.YES_NO:
            raise ValidationError("Yes/No choices are fixed and cannot be deleted.")
        return super().delete(*args, **kwargs)


class SurveyMatrixRow(QuestionChildMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(SurveyQuestion, on_delete=models.PROTECT, related_name="matrix_rows")
    row_key = models.CharField(max_length=80)
    label = models.CharField(max_length=500)
    position = models.PositiveIntegerField()
    objects = QuestionChildQuerySet.as_manager()

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["question", "position"], name="svhq_matrix_position_uq"),
            models.UniqueConstraint(fields=["question", "row_key"], name="svhq_matrix_key_uq"),
        ]
        indexes = [models.Index(fields=["question", "position"], name="svhq_matrix_order_idx")]

    def __str__(self):
        return self.label

    def clean(self):
        if self.question_id and self.question.question_type != SurveyQuestion.Type.MATRIX:
            raise ValidationError({"question": "Matrix rows can only be added to matrix questions."})


class SurveyResponse(models.Model):
    class Source(models.TextChoices):
        BROWSER = "browser", "Browser"
        WEBVIEW = "webview", "Mobile WebView"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(Survey, on_delete=models.PROTECT, related_name="responses")
    started_at = models.DateTimeField()
    submitted_at = models.DateTimeField(default=timezone.now)
    access_nonce_hash = models.CharField(max_length=64, unique=True)
    definition_checksum = models.CharField(max_length=64)
    source = models.CharField(max_length=16, choices=Source.choices, blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            models.CheckConstraint(condition=Q(submitted_at__gte=models.F("started_at")), name="svhq_submit_after_start"),
        ]
        indexes = [models.Index(fields=["survey", "-submitted_at"], name="svhq_response_time_idx")]

    def __str__(self):
        return f"Response {self.pk} · {self.survey.display_identity}"


class SurveyAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    response = models.ForeignKey(SurveyResponse, on_delete=models.PROTECT, related_name="answers")
    question = models.ForeignKey(SurveyQuestion, on_delete=models.PROTECT, related_name="answers")
    matrix_row = models.ForeignKey(
        SurveyMatrixRow,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="answers",
    )
    text_value = models.TextField(blank=True)
    numeric_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    date_value = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["response", "question"],
                condition=Q(matrix_row__isnull=True),
                name="svhq_answer_question_uq",
            ),
            models.UniqueConstraint(
                fields=["response", "question", "matrix_row"],
                condition=Q(matrix_row__isnull=False),
                name="svhq_answer_matrix_uq",
            ),
        ]
        indexes = [
            models.Index(fields=["question", "response"], name="svhq_answer_question_idx"),
            models.Index(fields=["matrix_row", "response"], name="svhq_answer_matrix_idx"),
        ]

    def __str__(self):
        return f"Answer to {self.question.export_key}"

    def clean(self):
        errors = {}
        if self.response_id and self.question_id and self.response.survey_id != self.question.survey_id:
            errors["question"] = "The answer question must belong to the response survey."
        if self.matrix_row_id and self.matrix_row.question_id != self.question_id:
            errors["matrix_row"] = "The matrix row must belong to the answer question."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SurveyAnswerSelection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    answer = models.ForeignKey(SurveyAnswer, on_delete=models.PROTECT, related_name="selections")
    choice = models.ForeignKey(SurveyChoice, on_delete=models.PROTECT, related_name="answer_selections")
    rank = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["answer", "choice"], name="svhq_selection_choice_uq"),
            models.CheckConstraint(condition=Q(rank__isnull=True) | Q(rank__gte=1), name="svhq_selection_rank_pos"),
        ]
        indexes = [models.Index(fields=["choice", "answer"], name="svhq_selection_choice_idx")]

    def __str__(self):
        return self.choice.label

    def clean(self):
        if self.answer_id and self.choice_id and self.answer.question_id != self.choice.question_id:
            raise ValidationError({"choice": "The selected choice must belong to the answer question."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SurveyTemplate(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    schema_version = models.PositiveSmallIntegerField(default=1)
    definition = models.JSONField(default=dict)
    definition_checksum = models.CharField(max_length=64, blank=True, editable=False)
    source_survey = models.ForeignKey(
        Survey,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derived_templates",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_survey_templates",
        limit_choices_to={"is_staff": True},
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_survey_templates",
        limit_choices_to={"is_staff": True},
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                condition=Q(status="active"),
                name="svhq_active_template_name_uq",
            ),
            models.CheckConstraint(condition=Q(schema_version__gte=1), name="svhq_template_schema_pos"),
            models.CheckConstraint(
                condition=~Q(status="archived") | Q(archived_at__isnull=False),
                name="svhq_template_archive_time",
            ),
        ]
        indexes = [models.Index(fields=["status", "name"], name="svhq_template_status_idx")]

    def __str__(self):
        return self.name

    def clean(self):
        if not isinstance(self.definition, dict):
            raise ValidationError({"definition": "Template definitions must be objects."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.definition_checksum = checksum_json(self.definition)
        return super().save(*args, **kwargs)


class ImmutableArtifactQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if kwargs == {"generated_by": None}:
            return super().update(**kwargs)
        raise ValidationError("Official generated report artifacts are immutable snapshots.")

    def delete(self):
        raise ValidationError("Official generated report artifacts require an explicit retention-aware purge service.")


class SurveyReportArtifact(models.Model):
    class Format(models.TextChoices):
        PDF = "pdf", "PDF"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(Survey, on_delete=models.PROTECT, related_name="report_artifacts")
    file = models.FileField(upload_to="surveyhq/reports/%Y/%m/")
    format = models.CharField(max_length=12, choices=Format.choices, default=Format.PDF)
    palette_key = models.CharField(max_length=40)
    response_count = models.PositiveIntegerField()
    response_cutoff_at = models.DateTimeField()
    definition_checksum = models.CharField(max_length=64)
    file_checksum = models.CharField(max_length=64)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_survey_reports",
        limit_choices_to={"is_staff": True},
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableArtifactQuerySet.as_manager()

    class Meta:
        ordering = ["-generated_at"]
        indexes = [models.Index(fields=["survey", "-generated_at"], name="svhq_report_history_idx")]

    def __str__(self):
        generated_label = self.generated_at.strftime("%Y-%m-%d") if self.generated_at else "pending"
        return f"Official report · {self.survey.display_identity} · {generated_label}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Official generated report artifacts are immutable snapshots.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.survey.is_retention_locked:
            from .exceptions import SurveyRetentionProtected

            raise SurveyRetentionProtected("Official reports remain protected with the authoritative survey record.")
        return super().delete(*args, **kwargs)


class AppendOnlyAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        nullable_references = {"survey", "template", "actor"}
        if kwargs and set(kwargs).issubset(nullable_references) and all(value is None for value in kwargs.values()):
            return super().update(**kwargs)
        raise ValidationError("SurveyHQ audit events are append-only.")

    def delete(self):
        raise ValidationError("SurveyHQ audit events are append-only.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("SurveyHQ audit events are append-only.")


class SurveyHQParticipantAccess(models.Model):
    SINGLETON_KEY = "global"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    singleton_key = models.CharField(max_length=16, default=SINGLETON_KEY, unique=True, editable=False)
    active_entry_token = models.CharField(
        max_length=64,
        unique=True,
        default=generate_participant_entry_token,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    rotated_at = models.DateTimeField(default=timezone.now)
    rotated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surveyhq_participant_access_rotations",
        limit_choices_to={"is_staff": True},
    )

    class Meta:
        verbose_name = "SurveyHQ participant access"
        constraints = [
            models.CheckConstraint(
                condition=Q(singleton_key="global"),
                name="svhq_participant_access_global_ck",
            )
        ]

    def __str__(self):
        return "SurveyHQ Participant Access"


class SurveyHQAuditEvent(models.Model):
    class EntityType(models.TextChoices):
        SURVEY = "survey", "Survey"
        TEMPLATE = "template", "Template"
        PARTICIPANT_ACCESS = "participant_access", "Participant Access"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=24, choices=EntityType.choices)
    entity_id = models.UUIDField()
    survey = models.ForeignKey(
        Survey,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    template = models.ForeignKey(
        SurveyTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    event_type = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surveyhq_audit_events",
    )
    occurred_at = models.DateTimeField(auto_now_add=True)
    display_identity = models.CharField(max_length=700, blank=True)
    summary = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    objects = AppendOnlyAuditQuerySet.as_manager()

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "-occurred_at"], name="svhq_audit_entity_idx"),
            models.Index(fields=["survey", "-occurred_at"], name="svhq_audit_survey_idx"),
            models.Index(fields=["event_type", "-occurred_at"], name="svhq_audit_event_idx"),
        ]

    def __str__(self):
        return f"{self.get_entity_type_display()}: {self.event_type}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("SurveyHQ audit events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("SurveyHQ audit events are append-only.")
