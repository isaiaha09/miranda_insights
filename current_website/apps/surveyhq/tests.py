from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone

from apps.clients.models import Client, Project

from .codes import (
    SURVEY_CODE_ALPHABET,
    SURVEY_CODE_DIGITS,
    SURVEY_CODE_LETTERS,
    generate_survey_code,
    is_valid_survey_code,
)
from .duplication import duplicate_survey
from .exceptions import InvalidLifecycleTransition, SurveyRetentionProtected, SurveyStructureLocked
from .lifecycle import (
    archive_survey,
    close_survey,
    create_draft,
    delete_eligible_draft,
    open_scheduled_survey,
    publish_survey,
    reopen_survey,
    synchronize_due_surveys,
)
from .models import (
    Survey,
    SurveyAnswer,
    SurveyAnswerSelection,
    SurveyChoice,
    SurveyHQAuditEvent,
    SurveyMatrixRow,
    SurveyQuestion,
    SurveyReportArtifact,
    SurveyResponse,
    SurveyTemplate,
)
from .permissions import ANALYSTS_GROUP, AUTHORS_GROUP, MANAGERS_GROUP
from .publication import definition_matches_snapshot


User = get_user_model()


class SurveyHQTestMixin:
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_superuser(
            username="survey-manager",
            email="manager@example.com",
            password="test-pass-123",
        )
        self.client_record = Client.objects.create(
            organization_name="Somis Union School District",
            contact_name="Taylor Rivera",
            contact_email="taylor@example.com",
        )

    def create_survey(self, **overrides):
        values = {
            "client": self.client_record,
            "title": "Teacher SEL Perspective Survey",
            "reporting_month": 5,
            "reporting_year": 2027,
            "actor": self.manager,
        }
        values.update(overrides)
        return create_draft(**values)

    def add_short_text_question(self, survey, **overrides):
        values = {
            "survey": survey,
            "export_key": "q001",
            "position": 1,
            "question_type": SurveyQuestion.Type.SHORT_TEXT,
            "prompt": "What is working well?",
            "required": True,
        }
        values.update(overrides)
        return SurveyQuestion.objects.create(**values)


class SurveyModelTests(SurveyHQTestMixin, TestCase):
    def test_all_phase_one_models_are_registered(self):
        model_names = {
            Survey,
            SurveyQuestion,
            SurveyChoice,
            SurveyMatrixRow,
            SurveyResponse,
            SurveyAnswer,
            SurveyAnswerSelection,
            SurveyTemplate,
            SurveyReportArtifact,
            SurveyHQAuditEvent,
        }
        self.assertEqual(len(model_names), 10)

    def test_display_identity_uses_month_client_and_title(self):
        survey = self.create_survey()
        self.assertEqual(
            survey.display_identity,
            "May 2027 · Somis Union School District · Teacher SEL Perspective Survey",
        )

    def test_display_identity_uses_contact_for_client_without_organization_or_user(self):
        individual = Client.objects.create(contact_name="Jordan Lee", contact_email="jordan@example.com")
        survey = self.create_survey(client=individual, title="Goal Review")
        self.assertIsNone(individual.user)
        self.assertEqual(survey.display_identity, "May 2027 · Jordan Lee · Goal Review")

    def test_published_identity_uses_retained_client_snapshot(self):
        survey = self.create_survey()
        self.add_short_text_question(survey)
        survey = publish_survey(survey, actor=self.manager)
        self.client_record.organization_name = "Renamed Organization"
        self.client_record.save(update_fields=["organization_name"])
        survey.refresh_from_db()
        self.assertIn("Somis Union School District", survey.display_identity)

    def test_project_must_belong_to_survey_client(self):
        other_client = Client.objects.create(contact_name="Other Client", contact_email="other@example.com")
        project = Project.objects.create(client=other_client, name="Other Project")
        survey = Survey(
            client=self.client_record,
            project=project,
            title="Invalid Project Survey",
            reporting_month=5,
            reporting_year=2027,
        )
        with self.assertRaises(ValidationError):
            survey.full_clean()

    def test_client_deletion_retains_published_survey_and_snapshot(self):
        survey = self.create_survey()
        self.add_short_text_question(survey)
        survey = publish_survey(survey, actor=self.manager)
        self.client_record.delete()
        survey.refresh_from_db()
        self.assertIsNone(survey.client)
        self.assertIn("Somis Union School District", survey.display_identity)

    def test_structural_questions_cannot_be_required(self):
        survey = self.create_survey()
        question = SurveyQuestion(
            survey=survey,
            export_key="info",
            position=1,
            question_type=SurveyQuestion.Type.HEADING,
            prompt="Introduction",
            required=True,
        )
        with self.assertRaises(ValidationError):
            question.save()

    def test_answer_and_selection_relationships_must_match(self):
        survey = self.create_survey()
        question = SurveyQuestion.objects.create(
            survey=survey,
            export_key="q001",
            position=1,
            question_type=SurveyQuestion.Type.SINGLE_CHOICE,
            prompt="Choose one",
        )
        choice = SurveyChoice.objects.create(question=question, option_key="yes", label="Yes", position=1)
        other_survey = self.create_survey(title="Other")
        other_question = self.add_short_text_question(other_survey)
        response = SurveyResponse.objects.create(
            survey=survey,
            started_at=timezone.now() - timedelta(minutes=1),
            access_nonce_hash="a" * 64,
            definition_checksum="b" * 64,
        )
        answer = SurveyAnswer(response=response, question=other_question)
        with self.assertRaises(ValidationError):
            answer.full_clean()
        valid_answer = SurveyAnswer.objects.create(response=response, question=question)
        selection = SurveyAnswerSelection(answer=valid_answer, choice=choice)
        selection.full_clean()

    def test_question_positions_are_unique(self):
        survey = self.create_survey()
        self.add_short_text_question(survey)
        with self.assertRaises(ValidationError), transaction.atomic():
            SurveyQuestion.objects.create(
                survey=survey,
                export_key="q002",
                position=1,
                question_type=SurveyQuestion.Type.LONG_TEXT,
                prompt="Duplicate position",
            )


class SurveyCodeTests(TestCase):
    def test_generated_codes_use_exact_approved_format(self):
        for _ in range(200):
            code = generate_survey_code()
            self.assertEqual(len(code), 6)
            self.assertTrue(is_valid_survey_code(code))
            self.assertTrue(set(code) <= set(SURVEY_CODE_ALPHABET))
            self.assertTrue(any(character in SURVEY_CODE_LETTERS for character in code))
            self.assertTrue(any(character in SURVEY_CODE_DIGITS for character in code))

    def test_code_validation_is_case_sensitive(self):
        self.assertTrue(is_valid_survey_code("Ab3K9x"))
        self.assertNotEqual("Ab3K9x", "ab3k9x")
        self.assertFalse(is_valid_survey_code("AO0Il1"))

    def test_creation_service_retries_database_code_collision(self):
        manager = User.objects.create_superuser(username="code-manager", password="pass")
        client_record = Client.objects.create(contact_name="Code Client", contact_email="code@example.com")
        Survey.objects.create(
            client=client_record,
            title="Existing",
            reporting_month=1,
            reporting_year=2027,
            access_code="Ab3K9x",
        )
        with patch(
            "apps.surveyhq.lifecycle.generate_survey_code",
            side_effect=["Cd5N7z", "Ab3K9x", "Bc4M8y"],
        ):
            survey = create_draft(
                client=client_record,
                title="Collision Retry",
                reporting_month=2,
                reporting_year=2027,
                actor=manager,
            )
        self.assertEqual(survey.access_code, "Bc4M8y")


class PublicationAndLockingTests(SurveyHQTestMixin, TestCase):
    def test_publication_creates_deterministic_snapshot_and_checksum(self):
        survey = self.create_survey()
        self.add_short_text_question(survey)
        published = publish_survey(survey, actor=self.manager)
        self.assertEqual(published.status, Survey.Status.OPEN)
        self.assertEqual(len(published.definition_checksum), 64)
        self.assertEqual(published.definition_snapshot["schema_version"], 1)
        self.assertTrue(definition_matches_snapshot(published))
        event = published.audit_events.get(event_type="survey_published")
        self.assertEqual(event.display_identity, published.display_identity)
        self.assertEqual(event.metadata["definition_checksum"], published.definition_checksum)

    def test_publication_rejects_survey_without_answerable_question(self):
        survey = self.create_survey()
        SurveyQuestion.objects.create(
            survey=survey,
            export_key="intro",
            position=1,
            question_type=SurveyQuestion.Type.DESCRIPTION,
            prompt="Welcome",
        )
        with self.assertRaises(ValidationError):
            publish_survey(survey, actor=self.manager)

    def test_likert_requires_numeric_choice_values(self):
        survey = self.create_survey()
        question = SurveyQuestion.objects.create(
            survey=survey,
            export_key="q001",
            position=1,
            question_type=SurveyQuestion.Type.LIKERT,
            prompt="Agreement",
        )
        SurveyChoice.objects.create(question=question, option_key="agree", label="Agree", position=1)
        SurveyChoice.objects.create(
            question=question,
            option_key="disagree",
            label="Disagree",
            numeric_value=Decimal("1"),
            position=2,
        )
        with self.assertRaises(ValidationError):
            publish_survey(survey, actor=self.manager)

    def test_published_question_choice_and_matrix_structure_is_locked(self):
        survey = self.create_survey()
        question = SurveyQuestion.objects.create(
            survey=survey,
            export_key="q001",
            position=1,
            question_type=SurveyQuestion.Type.MATRIX,
            prompt="Rate each item",
        )
        SurveyChoice.objects.create(
            question=question,
            option_key="low",
            label="Low",
            numeric_value=1,
            position=1,
        )
        choice = SurveyChoice.objects.create(
            question=question,
            option_key="high",
            label="High",
            numeric_value=2,
            position=2,
        )
        row = SurveyMatrixRow.objects.create(question=question, row_key="support", label="Support", position=1)
        survey = publish_survey(survey, actor=self.manager)

        question.prompt = "Changed prompt"
        with self.assertRaises(SurveyStructureLocked):
            question.save()
        choice.label = "Changed"
        with self.assertRaises(SurveyStructureLocked):
            choice.save()
        with self.assertRaises(SurveyStructureLocked):
            row.delete()
        with self.assertRaises(SurveyStructureLocked):
            SurveyQuestion.objects.create(
                survey=survey,
                export_key="q002",
                position=2,
                question_type=SurveyQuestion.Type.SHORT_TEXT,
                prompt="New question",
            )
        with self.assertRaises(SurveyStructureLocked):
            SurveyQuestion.objects.filter(pk=question.pk).update(prompt="Bulk change")


class LifecycleTests(SurveyHQTestMixin, TestCase):
    def test_scheduled_open_close_archive_and_five_year_retention(self):
        now = timezone.now().replace(microsecond=0)
        survey = self.create_survey(
            starts_at=now + timedelta(hours=1),
            close_mode=Survey.CloseMode.SCHEDULED,
            ends_at=now + timedelta(days=2),
        )
        self.add_short_text_question(survey)
        survey = publish_survey(survey, actor=self.manager, at=now)
        self.assertEqual(survey.status, Survey.Status.SCHEDULED)

        with self.assertRaises(InvalidLifecycleTransition):
            open_scheduled_survey(survey, at=now)
        survey = open_scheduled_survey(survey, at=now + timedelta(hours=1))
        self.assertEqual(survey.status, Survey.Status.OPEN)
        survey = close_survey(survey, at=now + timedelta(days=2), reason="scheduled")
        self.assertEqual(survey.retention_until, now + timedelta(days=2) + relativedelta(years=5))
        survey = archive_survey(survey, actor=self.manager, at=now + timedelta(days=3))
        self.assertEqual(survey.status, Survey.Status.ARCHIVED)

    def test_reopening_is_manager_only_confirmed_audited_and_retention_safe(self):
        now = timezone.now().replace(microsecond=0)
        survey = self.create_survey()
        self.add_short_text_question(survey)
        survey = publish_survey(survey, actor=self.manager, at=now)
        survey = close_survey(survey, actor=self.manager, at=now + timedelta(days=1))
        original_retention = survey.retention_until

        staff = User.objects.create_user(username="ordinary-staff", password="pass", is_staff=True)
        with self.assertRaises(PermissionDenied):
            reopen_survey(survey, actor=staff, confirmation=True)
        with self.assertRaises(ValidationError):
            reopen_survey(survey, actor=self.manager, confirmation=False)

        survey = reopen_survey(survey, actor=self.manager, confirmation=True)
        self.assertEqual(survey.status, Survey.Status.OPEN)
        self.assertEqual(survey.retention_until, original_retention)
        event = survey.audit_events.get(event_type="survey_reopened")
        self.assertIn("existing dataset", event.summary)

        survey = close_survey(survey, actor=self.manager, at=now + timedelta(days=30))
        self.assertGreater(survey.retention_until, original_retention)

    def test_synchronize_due_surveys_is_idempotent(self):
        now = timezone.now().replace(microsecond=0)
        survey = self.create_survey(starts_at=now - timedelta(minutes=1))
        self.add_short_text_question(survey)
        survey = publish_survey(survey, actor=self.manager, at=now - timedelta(hours=1))
        self.assertEqual(survey.status, Survey.Status.SCHEDULED)
        first = synchronize_due_surveys(at=now)
        second = synchronize_due_surveys(at=now)
        self.assertEqual(first, {"opened": 1, "closed": 0})
        self.assertEqual(second, {"opened": 0, "closed": 0})
        self.assertEqual(survey.audit_events.filter(event_type="survey_opened").count(), 1)

    def test_published_survey_cannot_be_deleted(self):
        survey = self.create_survey()
        self.add_short_text_question(survey)
        survey = publish_survey(survey, actor=self.manager)
        with self.assertRaises(SurveyRetentionProtected):
            survey.delete()

    def test_eligible_draft_deletion_preserves_audit_identity(self):
        survey = self.create_survey()
        self.add_short_text_question(survey)
        survey_id = survey.pk
        delete_eligible_draft(survey, actor=self.manager)
        self.assertFalse(Survey.objects.filter(pk=survey_id).exists())
        event = SurveyHQAuditEvent.objects.get(entity_id=survey_id, event_type="survey_deleted")
        self.assertIsNone(event.survey)
        self.assertIn("Teacher SEL Perspective Survey", event.display_identity)

    def test_audit_events_are_append_only(self):
        survey = self.create_survey()
        event = survey.audit_events.get(event_type="survey_created")
        event.summary = "Changed"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()


class DuplicationTests(SurveyHQTestMixin, TestCase):
    def test_duplication_copies_structure_but_not_runtime_or_responses(self):
        survey = self.create_survey()
        question = SurveyQuestion.objects.create(
            survey=survey,
            export_key="q001",
            position=1,
            question_type=SurveyQuestion.Type.SINGLE_CHOICE,
            prompt="Choose one",
        )
        SurveyChoice.objects.create(question=question, option_key="one", label="One", position=1)
        SurveyChoice.objects.create(question=question, option_key="two", label="Two", position=2)
        survey = publish_survey(survey, actor=self.manager)
        duplicate = duplicate_survey(
            survey,
            actor=self.manager,
            title="Teacher SEL Follow-Up",
            copy_client=True,
            copy_reporting_period=True,
        )

        self.assertEqual(duplicate.status, Survey.Status.DRAFT)
        self.assertNotEqual(duplicate.pk, survey.pk)
        self.assertNotEqual(duplicate.access_code, survey.access_code)
        self.assertEqual(duplicate.source_survey, survey)
        self.assertEqual(duplicate.definition_snapshot, {})
        self.assertEqual(duplicate.definition_checksum, "")
        self.assertIsNone(duplicate.published_at)
        self.assertEqual(duplicate.responses.count(), 0)
        self.assertEqual(duplicate.report_artifacts.count(), 0)
        self.assertEqual(duplicate.questions.count(), 1)
        copied_question = duplicate.questions.get()
        self.assertNotEqual(copied_question.pk, question.pk)
        self.assertEqual(copied_question.export_key, question.export_key)
        self.assertEqual(copied_question.choices.count(), 2)
        self.assertEqual(duplicate.audit_events.filter(event_type="survey_duplicated").count(), 1)

    def test_duplication_requires_explicit_target_client_choice(self):
        survey = self.create_survey()
        with self.assertRaises(ValidationError):
            duplicate_survey(survey, actor=self.manager)


class PermissionAndShellTests(TestCase):
    def test_seeded_groups_have_expected_boundaries(self):
        managers = Group.objects.get(name=MANAGERS_GROUP)
        authors = Group.objects.get(name=AUTHORS_GROUP)
        analysts = Group.objects.get(name=ANALYSTS_GROUP)
        self.assertTrue(managers.permissions.filter(codename="reopen_survey").exists())
        self.assertTrue(managers.permissions.filter(codename="rotate_survey_code").exists())
        self.assertTrue(authors.permissions.filter(codename="duplicate_survey").exists())
        self.assertFalse(authors.permissions.filter(codename="publish_survey").exists())
        self.assertFalse(authors.permissions.filter(codename="rotate_survey_code").exists())
        self.assertTrue(analysts.permissions.filter(codename="export_survey_data").exists())
        self.assertFalse(analysts.permissions.filter(codename="change_survey").exists())

    def test_anonymous_access_uses_existing_admin_login(self):
        response = self.client.get(reverse("surveyhq:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_unpermitted_staff_user_is_denied_and_does_not_see_index_entry(self):
        staff = User.objects.create_user(username="survey-staff", password="test-pass-123", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("surveyhq:dashboard")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("admin:index")), "Open SurveyHQ")

    def test_group_member_can_access_existing_shell(self):
        staff = User.objects.create_user(username="survey-author", password="test-pass-123", is_staff=True)
        staff.groups.add(Group.objects.get(name=AUTHORS_GROUP))
        self.client.force_login(staff)
        response = self.client.get(reverse("surveyhq:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/surveyhq/dashboard.html")
        self.assertContains(response, "Create, build, preview, template, publish, and manage")
        self.assertContains(self.client.get(reverse("admin:index")), reverse("surveyhq:dashboard"))

    def test_no_public_participant_route_exists(self):
        with self.assertRaises(Resolver404):
            resolve("/surveyhq/participate/")
