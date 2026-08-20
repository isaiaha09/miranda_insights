from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from apps.clients.models import Client, Project

from . import builder
from .configuration import normalize_question_configuration
from .lifecycle import create_draft, publish_survey, rotate_access_code, update_draft_metadata
from .models import Survey, SurveyChoice, SurveyHQAuditEvent, SurveyQuestion, SurveyResponse, SurveyTemplate
from .exceptions import InvalidLifecycleTransition, SurveyStructureLocked
from .permissions import ANALYSTS_GROUP, AUTHORS_GROUP, MANAGERS_GROUP
from .template_services import (
    archive_template,
    create_survey_from_template,
    create_template_from_survey,
    delete_eligible_template,
    duplicate_template,
)


User = get_user_model()


class PhaseTwoMixin:
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user(username="manager2", password="pass", is_staff=True)
        self.manager.groups.add(Group.objects.get(name=MANAGERS_GROUP))
        self.author = User.objects.create_user(username="author2", password="pass", is_staff=True)
        self.author.groups.add(Group.objects.get(name=AUTHORS_GROUP))
        self.analyst = User.objects.create_user(username="analyst2", password="pass", is_staff=True)
        self.analyst.groups.add(Group.objects.get(name=ANALYSTS_GROUP))
        self.client_record = Client.objects.create(
            organization_name="Somis Union School District",
            contact_name="Taylor Rivera",
            contact_email="taylor@example.com",
        )
        self.project = Project.objects.create(client=self.client_record, name="SEL Review")

    def draft(self, actor=None, **overrides):
        values = {
            "client": self.client_record,
            "project": self.project,
            "title": "Teacher SEL Perspective Survey",
            "reporting_month": 5,
            "reporting_year": 2027,
            "actor": actor or self.manager,
        }
        values.update(overrides)
        return create_draft(**values)

    def answerable(self, survey, actor=None, **overrides):
        values = {
            "survey": survey,
            "actor": actor or self.manager,
            "question_type": SurveyQuestion.Type.SHORT_TEXT,
            "prompt": "What is working well?",
            "required": True,
        }
        values.update(overrides)
        return builder.create_question(**values)


class DashboardAndMetadataTests(PhaseTwoMixin, TestCase):
    def test_dashboard_counts_filters_search_and_page_size(self):
        survey = self.draft()
        for number in range(26):
            self.draft(title=f"Additional Survey {number}", project=None)
        self.client.force_login(self.manager)
        response = self.client.get(reverse("surveyhq:dashboard"), {"q": survey.access_code})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, survey.display_identity)
        self.assertEqual(len(response.context["survey_page"]), 1)
        response = self.client.get(reverse("surveyhq:dashboard"))
        self.assertEqual(len(response.context["survey_page"]), 25)
        self.assertEqual(response.context["counts"]["draft"], 27)
        self.assertContains(response, "Participant entry is available")

    def test_create_form_accepts_client_without_user_and_filters_projects(self):
        self.assertIsNone(self.client_record.user)
        self.client.force_login(self.author)
        options = self.client.get(reverse("surveyhq:project_options"), {"client": self.client_record.pk})
        self.assertEqual(options.status_code, 200)
        self.assertEqual(options.json()["projects"][0]["id"], self.project.pk)
        response = self.client.post(
            reverse("surveyhq:survey_create"),
            {
                "client": self.client_record.pk,
                "project": self.project.pk,
                "reporting_month": 6,
                "reporting_year": 2027,
                "title": "Created in Admin",
                "description": "",
                "category": "Education",
                "start_mode": "immediate",
                "close_mode": Survey.CloseMode.MANUAL,
                "starts_at": "",
                "ends_at": "",
            },
        )
        survey = Survey.objects.get(title="Created in Admin")
        self.assertRedirects(response, reverse("surveyhq:survey_builder", args=[survey.pk]))

    def test_metadata_rejects_other_client_project_and_locks_after_publish(self):
        other = Client.objects.create(contact_name="Other", contact_email="other@example.com")
        wrong_project = Project.objects.create(client=other, name="Wrong")
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("surveyhq:survey_create"),
            {
                "client": self.client_record.pk,
                "project": wrong_project.pk,
                "reporting_month": 5,
                "reporting_year": 2027,
                "title": "Mismatch",
                "start_mode": "immediate",
                "close_mode": Survey.CloseMode.MANUAL,
            },
        )
        self.assertContains(response, "Select a valid choice", status_code=200)
        survey = self.draft()
        self.answerable(survey)
        published = publish_survey(survey, actor=self.manager)
        with self.assertRaises(InvalidLifecycleTransition):
            update_draft_metadata(
                published,
                actor=self.manager,
                client=self.client_record,
                title="Changed",
                reporting_month=5,
                reporting_year=2027,
            )
        published.title = "Direct model change"
        with self.assertRaises(SurveyStructureLocked):
            published.save()
        with self.assertRaises(SurveyStructureLocked):
            Survey.objects.filter(pk=published.pk).update(title="Bulk change")


class BuilderTests(PhaseTwoMixin, TestCase):
    def test_supported_configuration_contracts_and_defaults(self):
        self.assertEqual(normalize_question_configuration("rating", {}), {"minimum": "1", "maximum": "5", "step": "1"})
        self.assertEqual(normalize_question_configuration("linear_scale", {}), {"minimum": "0", "maximum": "10", "step": "1"})
        with self.assertRaises(ValidationError):
            normalize_question_configuration("date", {"placeholder": "No"})
        with self.assertRaises(ValidationError):
            normalize_question_configuration("number", {"minimum": 10, "maximum": 1})

    def test_stable_keys_reorder_duplicate_and_fixed_type(self):
        survey = self.draft()
        first = self.answerable(survey, actor=self.author, prompt="First")
        second = self.answerable(survey, actor=self.author, prompt="Second")
        builder.move_question(second, actor=self.author, direction="up")
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual((second.position, first.position), (1, 2))
        duplicate = builder.duplicate_question(first, actor=self.author)
        self.assertEqual(duplicate.export_key, "q003")
        self.assertEqual(duplicate.position, first.position + 1)
        self.assertEqual(duplicate.question_type, first.question_type)
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("surveyhq:question_edit", args=[first.pk]),
            {"question_type": SurveyQuestion.Type.DATE, "prompt": "Edited", "help_text": "", "required": "on"},
        )
        first.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(first.question_type, SurveyQuestion.Type.SHORT_TEXT)
        first.question_type = SurveyQuestion.Type.DATE
        with self.assertRaises(ValidationError):
            first.save()
        with self.assertRaises(ValidationError):
            SurveyQuestion.objects.filter(pk=first.pk).update(question_type=SurveyQuestion.Type.DATE)

    def test_yes_no_likert_matrix_and_choice_management(self):
        survey = self.draft()
        yes_no = builder.create_question(survey=survey, actor=self.author, question_type="yes_no", prompt="Agree?")
        self.assertEqual(list(yes_no.choices.values_list("option_key", flat=True)), ["yes", "no"])
        with self.assertRaises(PermissionDenied):
            builder.update_choice(choice=yes_no.choices.first(), actor=self.author, label="Maybe")
        likert = builder.create_question(
            survey=survey, actor=self.author, question_type="likert", prompt="Agreement", preset="five_agreement"
        )
        self.assertEqual(likert.choices.count(), 5)
        self.assertTrue(all(value is not None for value in likert.choices.values_list("numeric_value", flat=True)))
        custom_likert = builder.create_question(
            survey=survey, actor=self.author, question_type="likert", prompt="Custom later"
        )
        builder.apply_likert_preset(custom_likert, actor=self.author, preset="seven_agreement")
        self.assertEqual(custom_likert.choices.count(), 7)
        with self.assertRaises(ValidationError):
            builder.apply_likert_preset(custom_likert, actor=self.author, preset="five_agreement")
        matrix = builder.create_question(survey=survey, actor=self.author, question_type="matrix", prompt="Rate areas")
        row = builder.add_matrix_row(question=matrix, actor=self.author, label="Support")
        one = builder.add_choice(question=matrix, actor=self.author, label="Low", numeric_value=1)
        two = builder.add_choice(question=matrix, actor=self.author, label="High", numeric_value=2)
        builder.move_choice(two, actor=self.author, direction="up")
        two.refresh_from_db(); one.refresh_from_db()
        self.assertEqual((two.position, one.position), (1, 2))
        self.assertEqual(row.row_key, "row001")
        self.client.force_login(self.author)
        response = self.client.get(reverse("surveyhq:question_edit", args=[matrix.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ordered options")
        self.assertContains(response, "Matrix structure")

    def test_preview_renders_all_without_creating_response(self):
        survey = self.draft()
        for question_type in SurveyQuestion.Type.values:
            question = builder.create_question(
                survey=survey,
                actor=self.manager,
                question_type=question_type,
                prompt=f"Preview {question_type}",
            )
            if question_type in SurveyQuestion.CHOICE_TYPES and question_type not in {"yes_no"}:
                builder.add_choice(question=question, actor=self.manager, label="One", numeric_value=1)
                builder.add_choice(question=question, actor=self.manager, label="Two", numeric_value=2)
            if question_type == "matrix":
                builder.add_matrix_row(question=question, actor=self.manager, label="Row")
        self.client.force_login(self.analyst)
        before = SurveyResponse.objects.count()
        response = self.client.get(reverse("surveyhq:survey_preview", args=[survey.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-SurveyHQ-Preview"], "true")
        self.assertContains(response, "Preview Mode")
        self.assertEqual(SurveyResponse.objects.count(), before)


class LifecyclePermissionAndTemplateTests(PhaseTwoMixin, TestCase):
    def test_author_cannot_publish_or_rotate_but_manager_can(self):
        survey = self.draft(actor=self.author)
        self.answerable(survey, actor=self.author)
        with self.assertRaises(PermissionDenied):
            publish_survey(survey, actor=self.author)
        published = publish_survey(survey, actor=self.manager)
        with self.assertRaises(PermissionDenied):
            rotate_access_code(published, actor=self.author)
        old_code = published.access_code
        rotated = rotate_access_code(published, actor=self.manager)
        self.assertNotEqual(old_code, rotated.access_code)

    def test_template_round_trip_duplicate_archive_and_delete_rules(self):
        survey = self.draft()
        question = builder.create_question(
            survey=survey, actor=self.manager, question_type="single_choice", prompt="Choose"
        )
        builder.add_choice(question=question, actor=self.manager, label="One")
        builder.add_choice(question=question, actor=self.manager, label="Two")
        template = create_template_from_survey(survey=survey, actor=self.manager, name="SEL Base")
        self.assertNotIn("id", template.definition["questions"][0])
        created = create_survey_from_template(
            template=template,
            actor=self.author,
            client=self.client_record,
            title="From Template",
            reporting_month=6,
            reporting_year=2027,
        )
        self.assertEqual(created.source_template, template)
        self.assertEqual(created.questions.count(), 1)
        self.assertEqual(created.responses.count(), 0)
        self.assertTrue(created.audit_events.filter(event_type="survey_created_from_template").exists())
        with self.assertRaises(ValidationError):
            delete_eligible_template(template, actor=self.manager)
        copied = duplicate_template(template, actor=self.manager, name="SEL Base Copy")
        copied_id = copied.pk
        delete_eligible_template(copied, actor=self.manager)
        self.assertFalse(SurveyTemplate.objects.filter(pk=copied_id).exists())
        archived = archive_template(template, actor=self.manager)
        self.assertEqual(archived.status, SurveyTemplate.Status.ARCHIVED)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("surveyhq:template_list")).status_code, 200)
        self.assertContains(self.client.get(reverse("surveyhq:template_detail", args=[template.pk])), "Definition")
        self.assertEqual(self.client.get(reverse("surveyhq:audit_log")).status_code, 200)

    def test_permission_aware_admin_views_and_isolated_participant_route(self):
        survey = self.draft()
        self.client.force_login(self.analyst)
        self.assertEqual(self.client.get(reverse("surveyhq:survey_detail", args=[survey.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("surveyhq:survey_builder", args=[survey.pk])).status_code, 403)
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(reverse("surveyhq:survey_builder", args=[survey.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("surveyhq:audit_log")).status_code, 403)
        self.assertEqual(resolve("/surveyhq/participate/").namespace, "surveyhq_participant")
        self.assertFalse(any("participant" in str(pattern).lower() for pattern in resolve(reverse("surveyhq:dashboard")).route))

    def test_builder_mutations_emit_only_meaningful_duplication_audit(self):
        survey = self.draft()
        question = self.answerable(survey)
        builder.update_question(question=question, actor=self.manager, prompt="Edited", configuration={})
        builder.move_question(question, actor=self.manager, direction="up")
        self.assertFalse(SurveyHQAuditEvent.objects.filter(survey=survey, event_type__in=["question_edited", "question_moved"]).exists())
        builder.duplicate_question(question, actor=self.manager)
        self.assertEqual(SurveyHQAuditEvent.objects.filter(survey=survey, event_type="question_duplicated").count(), 1)
