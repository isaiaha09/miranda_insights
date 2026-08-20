import hashlib
import io
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import builder
from .exports import long_csv_rows, safe_csv_text, wide_csv_rows
from .exceptions import SurveyStructureLocked
from .lifecycle import publish_survey
from .media import prepare_question_image, read_verified_question_image
from .models import SurveyQuestion, SurveyReportArtifact
from .participant import ParticipantSurveyForm
from .publication import build_definition_snapshot, checksum_json, definition_matches_snapshot
from .reports import REPORT_PALETTES, generate_survey_report
from .tests_phase3 import PhaseThreeMixin
from .tests_phase4 import PhaseFourMixin


User = get_user_model()


def image_upload(name="prompt.png", *, image_format="PNG", size=(80, 50), color="#c99a3d"):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format)
    content_type = "image/png" if image_format == "PNG" else "image/jpeg"
    return SimpleUploadedFile(name, output.getvalue(), content_type=content_type)


class ParticipantInteractionTests(PhaseThreeMixin, TestCase):
    def test_linear_scale_is_explicitly_unanswered_and_has_no_script_fallback(self):
        survey = self.draft()
        builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=SurveyQuestion.Type.LINEAR_SCALE,
            prompt="Progress",
            required=True,
            configuration={"minimum": "0", "maximum": "10", "step": "0.5", "low_anchor": "Low", "high_anchor": "High"},
        )
        survey = publish_survey(survey, actor=self.manager)
        self.grant(survey)
        response = self.client.get(reverse("surveyhq_participant:survey"))
        self.assertContains(response, 'type="range"')
        self.assertContains(response, "Not answered")
        self.assertContains(response, "<noscript>")
        self.assertContains(response, 'step="0.5"')

        question = survey.questions.get()
        blank = ParticipantSurveyForm(data={}, survey=survey)
        self.assertFalse(blank.is_valid())
        valid = ParticipantSurveyForm(data={question.export_key: "7.5"}, survey=survey)
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertEqual(valid.cleaned_data[question.export_key], Decimal("7.5"))

    def test_ranking_keeps_enabled_numbered_fallback_and_enhancement_hooks(self):
        survey = self.draft()
        question = builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=SurveyQuestion.Type.RANKING,
            prompt="Priorities",
            required=True,
        )
        for label in ("First", "Second", "Third"):
            builder.add_choice(question=question, actor=self.manager, label=label)
        survey = publish_survey(survey, actor=self.manager)
        self.grant(survey)
        response = self.client.get(reverse("surveyhq_participant:survey"))
        self.assertContains(response, "This numbered control works without JavaScript")
        self.assertContains(response, "data-ranking-enhanced")
        self.assertContains(response, "data-ranking-reset")
        self.assertContains(response, "data-ranked-list")
        self.assertNotContains(response, "disabled")

        keys = list(question.choices.order_by("position").values_list("option_key", flat=True))
        incomplete = ParticipantSurveyForm(data={f"{question.export_key}__{keys[0]}": "1"}, survey=survey)
        self.assertFalse(incomplete.is_valid())
        complete = ParticipantSurveyForm(
            data={f"{question.export_key}__{key}": str(index) for index, key in enumerate(keys, 1)},
            survey=survey,
        )
        self.assertTrue(complete.is_valid(), complete.errors)


class QuestionImageTests(PhaseThreeMixin, TestCase):
    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.settings_override.enable()
        super().setUp()

    def tearDown(self):
        self.settings_override.disable()
        self.media_directory.cleanup()
        super().tearDown()

    def add_image_question(self, survey):
        prepared = prepare_question_image(image_upload())
        return builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=SurveyQuestion.Type.SHORT_TEXT,
            prompt="Describe the image",
            prepared_image=prepared,
            image_alt_text="A gold rectangular prompt image.",
        )

    def test_normalizes_metadata_protects_delivery_and_locks_published_image(self):
        survey = self.draft()
        question = self.add_image_question(survey)
        self.assertEqual(question.image_content_type, "image/png")
        self.assertEqual((question.image_width, question.image_height), (80, 50))
        self.assertEqual(hashlib.sha256(read_verified_question_image(question)).hexdigest(), question.image_checksum)

        self.client.force_login(self.manager)
        admin_image = self.client.get(reverse("surveyhq:question_image", args=[question.pk]))
        self.assertEqual(admin_image.status_code, 200)
        self.assertIn("private", admin_image["Cache-Control"])
        self.assertIn("no-store", admin_image["Cache-Control"])

        survey = publish_survey(survey, actor=self.manager)
        question.refresh_from_db()
        self.assertEqual(survey.definition_snapshot["schema_version"], 2)
        self.assertEqual(survey.definition_snapshot["questions"][0]["image"]["checksum"], question.image_checksum)
        with self.assertRaises((SurveyStructureLocked, ValidationError)):
            builder.update_question(
                question=question,
                actor=self.manager,
                prompt=question.prompt,
                remove_image=True,
            )

        self.client.logout()
        cache.clear()
        self.grant(survey)
        participant_image = self.client.get(
            reverse("surveyhq_participant:question_image", args=[question.pk])
        )
        self.assertEqual(participant_image.status_code, 200)
        self.assertIn("no-store", participant_image["Cache-Control"])

    def test_rejects_extension_mismatch_alt_violations_and_production_without_durable_storage(self):
        with self.assertRaises(ValidationError):
            prepare_question_image(image_upload("wrong.jpg", image_format="PNG"))
        survey = self.draft()
        prepared = prepare_question_image(image_upload())
        with self.assertRaises(ValidationError):
            builder.create_question(
                survey=survey,
                actor=self.manager,
                question_type=SurveyQuestion.Type.SHORT_TEXT,
                prompt="Missing alt",
                prepared_image=prepared,
            )
        with override_settings(DEBUG=False, SURVEYHQ_DURABLE_STORAGE_READY=False):
            with self.assertRaises(ValidationError):
                prepare_question_image(image_upload())

    def test_version_one_definition_still_verifies_and_duplicate_reuses_immutable_asset(self):
        survey = self.draft()
        question = self.add_image_question(survey)
        duplicate = builder.duplicate_question(question, actor=self.manager)
        self.assertEqual(duplicate.image.name, question.image.name)
        version_one = build_definition_snapshot(survey, schema_version=1)
        survey.definition_snapshot = version_one
        survey.definition_checksum = checksum_json(version_one)
        self.assertTrue(definition_matches_snapshot(survey))

    def test_tampered_image_blocks_publication_and_protected_delivery(self):
        survey = self.draft()
        question = self.add_image_question(survey)
        with question.image.storage.open(question.image.name, "wb") as stored_file:
            stored_file.write(b"altered")
        with self.assertRaises(ValidationError):
            read_verified_question_image(question)
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(reverse("surveyhq:question_image", args=[question.pk])).status_code,
            404,
        )
        with self.assertRaises(ValidationError):
            publish_survey(survey, actor=self.manager)


class ExportAndReportTests(PhaseFourMixin, TestCase):
    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_directory.name,
            SURVEYHQ_DURABLE_STORAGE_READY=True,
        )
        self.settings_override.enable()
        super().setUp()

    def tearDown(self):
        self.settings_override.disable()
        self.media_directory.cleanup()
        super().tearDown()

    def test_wide_and_long_exports_preserve_order_cutoff_missing_and_formula_safety(self):
        first, second, third, now = self.populate()
        self.answer(third, self.questions["text"], text="  =SUM(A1:A2)")
        wide = list(wide_csv_rows(self.survey, now))
        long = list(long_csv_rows(self.survey, now))
        self.assertEqual(wide[0][:8], ["survey_id", "survey_display_identity", "client", "reporting_month", "reporting_year", "response_id", "submitted_at", "source"])
        self.assertEqual(len(wide), 4)
        self.assertEqual(long[0][8:12], ["question_id", "export_key", "question_text", "question_type"])
        self.assertTrue(any(str(cell).startswith("'") and "=SUM" in str(cell) for row in long for cell in row))
        self.assertEqual(safe_csv_text(" -command"), "' -command")
        multiple_columns = [index for index, name in enumerate(wide[0]) if "choose_all" in name]
        third_row = next(row for row in wide[1:] if row[5] == str(third.pk))
        self.assertTrue(multiple_columns)
        self.assertTrue(all(third_row[index] == "" for index in multiple_columns))

    def test_csv_views_are_private_bom_crlf_permissioned_and_audited(self):
        self.populate()
        self.client.force_login(self.analyst)
        response = self.client.get(reverse("surveyhq:survey_responses_csv", args=[self.survey.pk]))
        self.assertEqual(response.status_code, 200)
        payload = b"".join(response.streaming_content)
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", payload)
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(self.survey.audit_events.filter(event_type="survey_data_exported").exists())

        self.client.force_login(self.author)
        denied = self.client.get(reverse("surveyhq:survey_analytical_csv", args=[self.survey.pk]))
        self.assertEqual(denied.status_code, 403)

    def test_generated_pdf_is_retained_immutable_permissioned_and_checksum_verified(self):
        self.populate()
        artifact = generate_survey_report(
            self.survey,
            actor=self.manager,
            palette_key="miranda_navy_gold",
        )
        self.assertEqual(artifact.response_count, 3)
        self.assertEqual(artifact.definition_checksum, self.survey.definition_checksum)
        self.assertEqual(set(REPORT_PALETTES), {"miranda_navy_gold", "neutral_professional", "education", "high_contrast", "grayscale_print"})
        with artifact.file.open("rb") as report_file:
            content = report_file.read()
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertEqual(hashlib.sha256(content).hexdigest(), artifact.file_checksum)

        self.client.force_login(self.analyst)
        download = self.client.get(reverse("surveyhq:survey_report_download", args=[artifact.pk]))
        self.assertEqual(download.status_code, 200)
        self.assertIn("private", download["Cache-Control"])
        self.assertIn("no-store", download["Cache-Control"])
        self.assertTrue(self.survey.audit_events.filter(event_type="survey_report_downloaded").exists())
        with self.assertRaises(ValidationError):
            artifact.save()

        self.client.force_login(self.author)
        self.assertEqual(
            self.client.get(reverse("surveyhq:survey_report_download", args=[artifact.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("surveyhq:survey_report_generate", args=[self.survey.pk])).status_code,
            403,
        )

    def test_all_report_palettes_generate_and_prior_artifact_response_count_stays_fixed(self):
        _first, _second, _third, now = self.populate()
        artifacts = [
            generate_survey_report(self.survey, actor=self.manager, palette_key=palette)
            for palette in REPORT_PALETTES
        ]
        self.response(9, now + timedelta(minutes=1))
        self.assertTrue(all(artifact.response_count == 3 for artifact in artifacts))
        self.assertEqual(SurveyReportArtifact.objects.filter(survey=self.survey).count(), 5)
