import hashlib
import io
import tempfile
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile

from . import builder
from .lifecycle import publish_survey
from .media import prepare_question_image
from .models import Survey, SurveyHQAuditEvent, SurveyQuestion, SurveyResponse
from .participant import GRANT_SESSION_KEY
from .participant_access import get_participant_access, participant_entry_path
from .publication import definition_matches_snapshot
from .reports import generate_survey_report
from .tests_phase3 import PhaseThreeMixin


User = get_user_model()


def prompt_image():
    output = io.BytesIO()
    Image.new("RGB", (120, 80), "#b88420").save(output, format="PNG")
    return SimpleUploadedFile("prompt.png", output.getvalue(), content_type="image/png")


class QuestionImageMigrationTests(TransactionTestCase):
    migrate_from = [("surveyhq", "0004_alter_survey_options_and_more")]
    migrate_to = [("surveyhq", "0006_participant_entry_rotation")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        Client = old_apps.get_model("clients", "Client")
        OldSurvey = old_apps.get_model("surveyhq", "Survey")
        OldQuestion = old_apps.get_model("surveyhq", "SurveyQuestion")
        client = Client.objects.create(
            organization_name="Pre-image Client",
            contact_name="Taylor Rivera",
            contact_email="migration@example.com",
        )
        survey = OldSurvey.objects.create(
            client=client,
            title="Pre-image Survey",
            reporting_month=8,
            reporting_year=2026,
            access_code="Old123",
        )
        self.question_id = OldQuestion.objects.create(
            survey=survey,
            export_key="q001",
            position=1,
            question_type="short_text",
            prompt="Existing question",
            configuration={},
        ).pk

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def test_image_migration_preserves_existing_question_with_blank_metadata(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("surveyhq", "0005_surveyquestion_images")])
        migrated_apps = executor.loader.project_state(
            [("surveyhq", "0005_surveyquestion_images")]
        ).apps
        Question = migrated_apps.get_model("surveyhq", "SurveyQuestion")
        question = Question.objects.get(pk=self.question_id)
        self.assertEqual(question.prompt, "Existing question")
        self.assertFalse(question.image)
        self.assertEqual(question.image_alt_text, "")
        columns = {
            column.name
            for column in connection.introspection.get_table_description(
                connection.cursor(), "surveyhq_surveyquestion"
            )
        }
        self.assertTrue(
            {
                "image",
                "image_alt_text",
                "image_checksum",
                "image_byte_size",
                "image_width",
                "image_height",
            }.issubset(columns)
        )


class ParticipantEntryRotationTests(PhaseThreeMixin, TestCase):
    def test_current_token_works_while_base_random_and_rotated_tokens_fail(self):
        old_url = self.entry_url()
        self.assertEqual(self.client.get(reverse("surveyhq_participant:entry_base")).status_code, 404)
        self.assertEqual(
            self.client.get(
                reverse("surveyhq_participant:entry", kwargs={"entry_token": "random-token"})
            ).status_code,
            404,
        )
        self.assertEqual(self.client.get(old_url).status_code, 200)

        self.client.force_login(self.manager)
        confirmation = self.client.get(reverse("surveyhq:participant_access_rotate"))
        self.assertContains(confirmation, "immediately invalidates the previous SurveyHQ entry link")
        access = get_participant_access()
        old_token = access.active_entry_token
        unconfirmed = self.client.post(reverse("surveyhq:participant_access_rotate"), {})
        self.assertEqual(unconfirmed.status_code, 200)
        access.refresh_from_db()
        self.assertEqual(access.active_entry_token, old_token)

        rotated = self.client.post(
            reverse("surveyhq:participant_access_rotate"), {"confirm": "on"}
        )
        self.assertRedirects(rotated, reverse("surveyhq:participant_access"))
        access.refresh_from_db()
        new_url = participant_entry_path(access)
        self.assertNotEqual(access.active_entry_token, old_token)
        self.assertEqual(self.client.get(old_url).status_code, 404)
        self.assertEqual(self.client.get(new_url).status_code, 200)

        event = SurveyHQAuditEvent.objects.get(event_type="participant_entry_rotated")
        self.assertEqual(event.entity_type, SurveyHQAuditEvent.EntityType.PARTICIPANT_ACCESS)
        self.assertEqual(event.actor, self.manager)
        self.assertNotIn(old_token, str(event.metadata))
        self.assertNotIn(access.active_entry_token, str(event.metadata))
        self.assertNotIn(old_token, event.summary)

    def test_rotation_preserves_survey_code_open_state_and_existing_grant(self):
        survey = self.publish_simple()
        old_code = survey.access_code
        self.grant(survey)
        grant_before = self.client.session[GRANT_SESSION_KEY].copy()

        self.client.force_login(self.manager)
        self.client.post(reverse("surveyhq:participant_access_rotate"), {"confirm": "on"})
        survey.refresh_from_db()
        self.assertEqual(survey.access_code, old_code)
        self.assertEqual(survey.status, Survey.Status.OPEN)

        session = self.client.session
        session[GRANT_SESSION_KEY] = grant_before
        session.save()
        introduction = self.client.get(reverse("surveyhq_participant:introduction"))
        self.assertEqual(introduction.status_code, 200)
        self.assertContains(introduction, survey.title)

    def test_qr_uses_new_url_and_rotation_is_manager_only(self):
        self.client.force_login(self.manager)
        old_url = self.client.get(reverse("surveyhq:participant_access")).context["entry_url"]
        self.client.post(reverse("surveyhq:participant_access_rotate"), {"confirm": "on"})
        new_url = self.client.get(reverse("surveyhq:participant_access")).context["entry_url"]
        self.assertNotEqual(old_url, new_url)

        fake_image = MagicMock()
        fake_image.save.side_effect = lambda output, format: output.write(b"PNG")
        with patch("apps.surveyhq.views.qrcode.QRCode") as qr_class:
            qr_class.return_value.make_image.return_value = fake_image
            self.client.get(reverse("surveyhq:participant_qr"))
            qr_class.return_value.add_data.assert_called_once_with(new_url)

        for user in (self.author, self.analyst):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("surveyhq:participant_access_rotate")).status_code,
                403,
            )


class MissingImageReliabilityTests(PhaseThreeMixin, TestCase):
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

    def test_missing_published_image_does_not_break_runtime_paths_or_report(self):
        survey = self.draft()
        prepared = prepare_question_image(prompt_image())
        question = builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=SurveyQuestion.Type.SHORT_TEXT,
            prompt="Optional image question",
            required=False,
            prepared_image=prepared,
            image_alt_text="A gold prompt image.",
        )
        survey = publish_survey(survey, actor=self.manager)
        question.refresh_from_db()
        question.image.storage.delete(question.image.name)
        self.assertTrue(definition_matches_snapshot(survey))

        self.client.force_login(self.manager)
        preview = self.client.get(reverse("surveyhq:survey_preview", args=[survey.pk]))
        self.assertEqual(preview.status_code, 200)
        self.assertNotContains(preview, reverse("surveyhq:question_image", args=[question.pk]))
        self.assertEqual(
            self.client.get(reverse("surveyhq:survey_analytics", args=[survey.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("surveyhq:question_image", args=[question.pk])).status_code,
            404,
        )

        self.client.logout()
        self.grant(survey)
        self.assertEqual(
            self.client.get(reverse("surveyhq_participant:introduction")).status_code,
            200,
        )
        form_page = self.client.get(reverse("surveyhq_participant:survey"))
        self.assertEqual(form_page.status_code, 200)
        self.assertContains(form_page, question.prompt)
        self.assertNotContains(
            form_page,
            reverse("surveyhq_participant:question_image", args=[question.pk]),
        )
        submitted = self.client.post(
            reverse("surveyhq_participant:survey"), {question.export_key: ""}
        )
        self.assertRedirects(submitted, reverse("surveyhq_participant:thank_you"))
        self.assertEqual(SurveyResponse.objects.filter(survey=survey).count(), 1)

        artifact = generate_survey_report(
            survey,
            actor=self.manager,
            palette_key="miranda_navy_gold",
        )
        with artifact.file.open("rb") as report_file:
            report = report_file.read()
        self.assertTrue(report.startswith(b"%PDF"))
        self.assertEqual(hashlib.sha256(report).hexdigest(), artifact.file_checksum)

    def test_no_image_survey_preview_participant_and_analytics_work(self):
        survey = self.publish_simple()
        self.client.force_login(self.manager)
        for route in (
            reverse("surveyhq:survey_preview", args=[survey.pk]),
            reverse("surveyhq:survey_analytics", args=[survey.pk]),
        ):
            self.assertEqual(self.client.get(route).status_code, 200)
        self.client.logout()
        self.grant(survey)
        self.assertEqual(self.client.get(reverse("surveyhq_participant:introduction")).status_code, 200)
        self.assertEqual(self.client.get(reverse("surveyhq_participant:survey")).status_code, 200)
