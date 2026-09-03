import sys
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.views.debug import ExceptionReporter

from apps.clients.models import Client
from landingpage.throttling import check_request_throttle

from . import builder
from .duplication import duplicate_survey
from .exceptions import SurveyStructureLocked
from .forms import QuestionForm
from .lifecycle import create_draft, publish_survey
from .models import Survey, SurveyQuestion, SurveyResponse
from .template_services import create_survey_from_template, create_template_from_survey
from .tests_phase3 import PhaseThreeMixin


User = get_user_model()


class AnonymousModeMigrationTests(TransactionTestCase):
    migrate_from = [("surveyhq", "0006_participant_entry_rotation")]
    migrate_to = [("surveyhq", "0007_survey_collection_mode")]
    restore_to = [("surveyhq", "0008_identifiable_mode_and_permanent_delete")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldClient = old_apps.get_model("clients", "Client")
        OldSurvey = old_apps.get_model("surveyhq", "Survey")
        client = OldClient.objects.create(
            organization_name="Migration Client",
            contact_name="Jordan Lee",
            contact_email="migration@example.com",
        )
        self.draft_id = OldSurvey.objects.create(
            client=client,
            title="Existing Draft",
            reporting_month=8,
            reporting_year=2026,
            access_code="Drf123",
            status="draft",
        ).pk
        self.open_id = OldSurvey.objects.create(
            client=client,
            title="Existing Published Survey",
            reporting_month=8,
            reporting_year=2026,
            access_code="Opn123",
            status="open",
            published_at=timezone.now(),
            opened_at=timezone.now(),
            definition_checksum="a" * 64,
        ).pk

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.restore_to)
        super().tearDown()

    def test_existing_drafts_become_anonymous_and_published_surveys_remain_unclassified(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        migrated_apps = executor.loader.project_state(self.migrate_to).apps
        MigratedSurvey = migrated_apps.get_model("surveyhq", "Survey")
        self.assertEqual(
            MigratedSurvey.objects.get(pk=self.draft_id).collection_mode,
            "anonymous",
        )
        self.assertIsNone(
            MigratedSurvey.objects.get(pk=self.open_id).collection_mode
        )


class IdentifiableModeMigrationTests(TransactionTestCase):
    migrate_from = [("surveyhq", "0007_survey_collection_mode")]
    migrate_to = [("surveyhq", "0008_identifiable_mode_and_permanent_delete")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldClient = old_apps.get_model("clients", "Client")
        OldSurvey = old_apps.get_model("surveyhq", "Survey")
        client = OldClient.objects.create(
            organization_name="Migration Client",
            contact_name="Jordan Lee",
            contact_email="migration-identifiable@example.com",
        )
        self.anonymous_id = OldSurvey.objects.create(
            client=client,
            title="Anonymous Draft",
            reporting_month=9,
            reporting_year=2026,
            access_code="Ano123",
            collection_mode="anonymous",
        ).pk
        self.legacy_id = OldSurvey.objects.create(
            client=client,
            title="Legacy Published",
            reporting_month=9,
            reporting_year=2026,
            access_code="Leg123",
            status="open",
            collection_mode=None,
            published_at=timezone.now(),
            opened_at=timezone.now(),
            definition_checksum="a" * 64,
        ).pk

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def test_choice_and_permission_migration_preserves_existing_classification(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        MigratedSurvey = apps.get_model("surveyhq", "Survey")
        Group = apps.get_model("auth", "Group")
        self.assertEqual(MigratedSurvey.objects.get(pk=self.anonymous_id).collection_mode, "anonymous")
        self.assertIsNone(MigratedSurvey.objects.get(pk=self.legacy_id).collection_mode)
        self.assertTrue(
            Group.objects.get(name="SurveyHQ Managers").permissions.filter(
                codename="permanently_delete_survey"
            ).exists()
        )


class AnonymousModeLifecycleTests(PhaseThreeMixin, TestCase):
    def _add_publishable_choice_question(self, survey, question_type, prompt):
        question = builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=question_type,
            prompt=prompt,
        )
        builder.add_choice(question=question, actor=self.manager, label="First")
        builder.add_choice(question=question, actor=self.manager, label="Second")
        return question

    def test_new_duplicated_and_template_created_surveys_are_anonymous(self):
        source = self.draft()
        builder.create_question(
            survey=source,
            actor=self.manager,
            question_type=SurveyQuestion.Type.SHORT_TEXT,
            prompt="Share a reflection",
        )
        template = create_template_from_survey(
            survey=source,
            actor=self.manager,
            name="Anonymous Base",
        )
        duplicate = duplicate_survey(
            source,
            actor=self.manager,
            copy_client=True,
        )
        from_template = create_survey_from_template(
            template=template,
            actor=self.author,
            client=self.client_record,
            title="From Template",
            reporting_month=9,
            reporting_year=2026,
        )
        self.assertEqual(source.collection_mode, Survey.CollectionMode.ANONYMOUS)
        self.assertEqual(duplicate.collection_mode, Survey.CollectionMode.ANONYMOUS)
        self.assertEqual(from_template.collection_mode, Survey.CollectionMode.ANONYMOUS)

    def test_duplication_and_template_materialization_require_explicit_identifiable_mode(self):
        source = self.draft(collection_mode=Survey.CollectionMode.IDENTIFIABLE)
        builder.create_question(
            survey=source,
            actor=self.manager,
            question_type=SurveyQuestion.Type.EMAIL,
            prompt="Contact email",
        )
        template = create_template_from_survey(
            survey=source,
            actor=self.manager,
            name="Contact Structure",
        )
        anonymous_duplicate = duplicate_survey(source, actor=self.manager, copy_client=True)
        identifiable_duplicate = duplicate_survey(
            source,
            actor=self.manager,
            copy_client=True,
            collection_mode=Survey.CollectionMode.IDENTIFIABLE,
        )
        anonymous_from_template = create_survey_from_template(
            template=template,
            actor=self.author,
            client=self.client_record,
            title="Anonymous From Contact Template",
            reporting_month=10,
            reporting_year=2026,
        )
        identifiable_from_template = create_survey_from_template(
            template=template,
            actor=self.author,
            client=self.client_record,
            title="Identifiable From Contact Template",
            reporting_month=10,
            reporting_year=2026,
            collection_mode=Survey.CollectionMode.IDENTIFIABLE,
        )
        self.assertEqual(anonymous_duplicate.collection_mode, Survey.CollectionMode.ANONYMOUS)
        self.assertEqual(anonymous_duplicate.questions.get().question_type, SurveyQuestion.Type.EMAIL)
        self.assertEqual(identifiable_duplicate.collection_mode, Survey.CollectionMode.IDENTIFIABLE)
        self.assertEqual(anonymous_from_template.collection_mode, Survey.CollectionMode.ANONYMOUS)
        self.assertEqual(identifiable_from_template.collection_mode, Survey.CollectionMode.IDENTIFIABLE)

    def test_anonymous_publication_rejects_email_question_with_clear_message(self):
        survey = self.draft()
        question = builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=SurveyQuestion.Type.EMAIL,
            prompt="What is your email address?",
        )
        with self.assertRaises(ValidationError) as raised:
            publish_survey(survey, actor=self.manager)
        survey.refresh_from_db()
        self.assertEqual(survey.status, Survey.Status.DRAFT)
        self.assertIn("Anonymous surveys cannot request email addresses", str(raised.exception))
        self.assertIn(question.export_key, str(raised.exception))

    def test_identifiable_survey_can_publish_email_question(self):
        survey = self.draft(collection_mode=Survey.CollectionMode.IDENTIFIABLE)
        builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=SurveyQuestion.Type.EMAIL,
            prompt="What email address should we associate with this response?",
            required=True,
        )
        published = publish_survey(survey, actor=self.manager)
        self.assertEqual(published.status, Survey.Status.OPEN)
        self.assertEqual(published.collection_mode, Survey.CollectionMode.IDENTIFIABLE)

    def test_all_approved_non_email_question_types_can_publish_anonymously(self):
        survey = self.draft(title="Approved Anonymous Types")
        simple_types = (
            SurveyQuestion.Type.HEADING,
            SurveyQuestion.Type.DESCRIPTION,
            SurveyQuestion.Type.SHORT_TEXT,
            SurveyQuestion.Type.LONG_TEXT,
            SurveyQuestion.Type.NUMBER,
            SurveyQuestion.Type.RATING,
            SurveyQuestion.Type.LINEAR_SCALE,
            SurveyQuestion.Type.DATE,
            SurveyQuestion.Type.PAGE_BREAK,
        )
        for position, question_type in enumerate(simple_types, start=1):
            builder.create_question(
                survey=survey,
                actor=self.manager,
                question_type=question_type,
                prompt=f"Approved prompt {position}",
            )
        for question_type in (
            SurveyQuestion.Type.SINGLE_CHOICE,
            SurveyQuestion.Type.MULTIPLE_CHOICE,
            SurveyQuestion.Type.DROPDOWN,
            SurveyQuestion.Type.RANKING,
            SurveyQuestion.Type.LIKERT,
        ):
            self._add_publishable_choice_question(survey, question_type, question_type)
        builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=SurveyQuestion.Type.YES_NO,
            prompt="Yes or no",
        )
        matrix = self._add_publishable_choice_question(
            survey, SurveyQuestion.Type.MATRIX, "Matrix"
        )
        builder.add_matrix_row(question=matrix, actor=self.manager, label="Row one")
        published = publish_survey(survey, actor=self.manager)
        self.assertEqual(published.status, Survey.Status.OPEN)

    def test_collection_mode_is_locked_after_publication_and_legacy_checksum_is_unchanged(self):
        legacy = self.draft(collection_mode=None, title="Legacy Survey")
        builder.create_question(
            survey=legacy,
            actor=self.manager,
            question_type=SurveyQuestion.Type.EMAIL,
            prompt="Legacy email question",
        )
        published = publish_survey(legacy, actor=self.manager)
        checksum = published.definition_checksum
        self.assertIsNone(published.collection_mode)
        self.assertEqual(published.definition_snapshot["schema_version"], 2)
        published.collection_mode = Survey.CollectionMode.ANONYMOUS
        with self.assertRaises(SurveyStructureLocked):
            published.save()
        published.refresh_from_db()
        self.assertEqual(published.definition_checksum, checksum)


class AnonymousModePresentationTests(PhaseThreeMixin, TestCase):
    def test_admin_guidance_and_question_selector_are_explicit(self):
        survey = self.draft()
        self.client.force_login(self.manager)
        builder_page = self.client.get(
            reverse("surveyhq:survey_builder", args=[survey.pk])
        )
        self.assertContains(
            builder_page,
            "cannot automatically determine the semantic meaning of arbitrary prompts",
        )
        for warning in (
            "names",
            "dates of birth",
            "email addresses",
            "phone numbers",
            "student IDs",
            "employee IDs",
            "addresses",
            "account identifiers",
            "other direct identifiers",
        ):
            self.assertContains(builder_page, warning)
        self.assertContains(builder_page, "Free-text and Date questions remain available")
        question_page = self.client.get(
            reverse("surveyhq:question_create", args=[survey.pk])
        )
        self.assertNotContains(question_page, '<option value="email"')
        self.assertContains(question_page, "Prompt meaning is not automatically detected")

    def test_participant_notice_appears_only_for_anonymous_surveys(self):
        anonymous = self.publish_simple(title="Anonymous Survey")
        self.grant(anonymous)
        anonymous_intro = self.client.get(
            reverse("surveyhq_participant:introduction")
        )
        self.assertContains(anonymous_intro, "Responses are intended to be anonymous.")
        self.assertContains(
            anonymous_intro,
            "Do not include your name, email address, student/staff ID",
        )

        legacy = self.publish_simple(title="Legacy Survey", collection_mode=None)
        self.grant(legacy)
        legacy_intro = self.client.get(reverse("surveyhq_participant:introduction"))
        self.assertNotContains(legacy_intro, "Responses are intended to be anonymous.")

    def test_identifiable_selector_disclosure_and_anonymous_switch_warning(self):
        survey = self.draft(collection_mode=Survey.CollectionMode.IDENTIFIABLE)
        identifiable_form = QuestionForm(survey=survey)
        self.assertIn(
            SurveyQuestion.Type.EMAIL,
            {value for value, _label in identifiable_form.fields["question_type"].choices},
        )
        email_question = builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=SurveyQuestion.Type.EMAIL,
            prompt="Your contact email",
        )
        survey.collection_mode = Survey.CollectionMode.ANONYMOUS
        survey.save(update_fields=["collection_mode", "updated_at"])
        self.assertTrue(SurveyQuestion.objects.filter(pk=email_question.pk).exists())
        anonymous_form = QuestionForm(survey=survey)
        self.assertNotIn(
            SurveyQuestion.Type.EMAIL,
            {value for value, _label in anonymous_form.fields["question_type"].choices},
        )
        self.client.force_login(self.manager)
        builder_page = self.client.get(reverse("surveyhq:survey_builder", args=[survey.pk]))
        self.assertContains(builder_page, "Publication is blocked.")
        self.assertContains(builder_page, email_question.export_key)
        with self.assertRaises(ValidationError):
            publish_survey(survey, actor=self.manager)

        identifiable = self.publish_simple(
            title="Identifiable Survey",
            collection_mode=Survey.CollectionMode.IDENTIFIABLE,
        )
        self.grant(identifiable)
        introduction = self.client.get(reverse("surveyhq_participant:introduction"))
        self.assertContains(introduction, "This survey may request identifying information.")
        self.assertContains(introduction, "Information you choose to provide will be associated")
        self.assertNotContains(introduction, "Responses are intended to be anonymous.")

    def test_response_schema_has_no_direct_identity_or_detailed_device_fields(self):
        field_names = {field.name for field in SurveyResponse._meta.get_fields()}
        self.assertTrue(
            {
                "survey",
                "started_at",
                "submitted_at",
                "access_nonce_hash",
                "definition_checksum",
                "source",
            }.issubset(field_names)
        )
        self.assertTrue(
            field_names.isdisjoint(
                {
                    "user",
                    "account",
                    "client",
                    "ip",
                    "ip_address",
                    "user_agent",
                    "device",
                    "operating_system",
                    "fingerprint",
                    "email",
                    "name",
                }
            )
        )


class AnonymousModeTechnicalProtectionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_participant_code_and_answer_post_values_are_redacted_from_exception_reports(self):
        from .participant_views import participant_entry, participant_survey

        code_secret = "Secr31"
        request = self.factory.post(
            "/surveyhq/participate/current-entry-token/",
            {"survey_code": code_secret},
        )
        with patch(
            "apps.surveyhq.participant_views.participant_entry_token_is_active",
            return_value=True,
        ), patch(
            "apps.surveyhq.participant_views.check_request_throttle",
            side_effect=RuntimeError("entry failure"),
        ):
            try:
                participant_entry(request, "current-entry-token")
            except RuntimeError:
                report = ExceptionReporter(request, *sys.exc_info()).get_traceback_text()
        self.assertNotIn(code_secret, report)
        self.assertEqual(request.sensitive_post_parameters, "__ALL__")

        answer_secret = "private written response"
        request = self.factory.post(
            "/surveyhq/participate/survey/",
            {"q001": answer_secret},
        )
        with patch(
            "apps.surveyhq.participant_views._granted_context",
            return_value=(object(), object()),
        ), patch(
            "apps.surveyhq.participant_views.ParticipantSurveyForm",
            side_effect=RuntimeError("survey failure"),
        ):
            try:
                participant_survey(request)
            except RuntimeError:
                report = ExceptionReporter(request, *sys.exc_info()).get_traceback_text()
        self.assertNotIn(answer_secret, report)
        self.assertEqual(request.sensitive_post_parameters, "__ALL__")

    @override_settings(THROTTLE_ENABLED=True)
    def test_surveyhq_throttle_logging_uses_pseudonym_and_omits_sensitive_path(self):
        cache.clear()
        raw_ip = "203.0.113.77"
        token = "rotating-participant-entry-token"
        code = "Secr31"
        request = self.factory.post(
            f"/surveyhq/participate/{token}/",
            {"survey_code": code},
            REMOTE_ADDR=raw_ip,
        )
        with patch("landingpage.throttling.logger.warning") as warning:
            check_request_throttle(
                request,
                "surveyhq-entry-ip",
                "1/15m",
                pseudonymize_log_identity=True,
                include_request_path_in_log=False,
            )
            check_request_throttle(
                request,
                "surveyhq-entry-ip",
                "1/15m",
                pseudonymize_log_identity=True,
                include_request_path_in_log=False,
            )
        context = warning.call_args.kwargs["extra"]
        serialized = str(context)
        self.assertIn("client_identifier", context)
        self.assertNotIn("client_ip", context)
        self.assertNotIn("path", context)
        self.assertNotIn(raw_ip, serialized)
        self.assertNotIn(token, serialized)
        self.assertNotIn(code, serialized)


class ClientPortalSurveyHQAuthorizationTests(PhaseThreeMixin, TestCase):
    def test_ordinary_client_cannot_access_sensitive_surveyhq_admin_endpoints(self):
        portal_user = User.objects.create_user(
            username="portal-client",
            password="pass",
            email="portal@example.com",
        )
        Client.objects.create(
            user=portal_user,
            contact_name="Portal Client",
            contact_email="portal@example.com",
        )
        survey = self.publish_simple()
        self.grant(survey)
        response = SurveyResponse.objects.create(
            survey=survey,
            started_at=timezone.now(),
            access_nonce_hash="a" * 64,
            definition_checksum=survey.definition_checksum,
            source=SurveyResponse.Source.BROWSER,
        )
        self.client.force_login(portal_user)
        protected_routes = (
            reverse("surveyhq:response_list"),
            reverse("surveyhq:response_detail", args=[response.pk]),
            reverse("surveyhq:survey_analytics", args=[survey.pk]),
            reverse("surveyhq:survey_analytics_data", args=[survey.pk]),
            reverse("surveyhq:survey_responses_csv", args=[survey.pk]),
            reverse("surveyhq:survey_analytical_csv", args=[survey.pk]),
            reverse("surveyhq:survey_report_download", args=[uuid.uuid4()]),
            reverse("surveyhq:survey_delete_permanently", args=[survey.pk]),
            reverse("surveyhq:survey_audit", args=[survey.pk]),
            reverse("surveyhq:audit_log"),
        )
        for route in protected_routes:
            result = self.client.get(route)
            self.assertEqual(result.status_code, 302, route)
            self.assertIn(reverse("admin:login"), result.url)
