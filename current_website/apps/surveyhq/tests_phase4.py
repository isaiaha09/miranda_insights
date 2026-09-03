from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client

from . import builder
from .analytics import build_survey_analytics
from .lifecycle import archive_survey, close_survey, create_draft, publish_survey
from .models import SurveyAnswer, SurveyAnswerSelection, SurveyQuestion, SurveyResponse
from .permissions import ANALYSTS_GROUP, AUTHORS_GROUP, MANAGERS_GROUP


User = get_user_model()


class PhaseFourMixin:
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user(username="analytics-manager", password="pass", is_staff=True)
        self.manager.groups.add(Group.objects.get(name=MANAGERS_GROUP))
        self.analyst = User.objects.create_user(username="analytics-analyst", password="pass", is_staff=True)
        self.analyst.groups.add(Group.objects.get(name=ANALYSTS_GROUP))
        self.author = User.objects.create_user(username="analytics-author", password="pass", is_staff=True)
        self.author.groups.add(Group.objects.get(name=AUTHORS_GROUP))
        self.staff = User.objects.create_user(username="analytics-staff", password="pass", is_staff=True)
        self.superuser = User.objects.create_superuser(username="analytics-root", password="pass")
        self.client_record = Client.objects.create(
            organization_name="Somis Union School District",
            contact_name="Taylor Rivera",
            contact_email="taylor@example.com",
        )
        self.survey, self.questions = self.build_survey()

    def add(self, survey, question_type, prompt, **kwargs):
        return builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=question_type,
            prompt=prompt,
            **kwargs,
        )

    def options(self, question, values):
        return [
            builder.add_choice(
                question=question,
                actor=self.manager,
                label=label,
                numeric_value=numeric,
            )
            for label, numeric in values
        ]

    def build_survey(self):
        survey = create_draft(
            client=self.client_record,
            title="Analytics Survey",
            reporting_month=8,
            reporting_year=2026,
            actor=self.manager,
        )
        questions = {}
        questions["single"] = self.add(survey, "single_choice", "Choose one", required=False)
        questions["single_choices"] = self.options(questions["single"], [("First", None), ("Second", None)])
        questions["multiple"] = self.add(survey, "multiple_choice", "Choose all")
        questions["multiple_choices"] = self.options(questions["multiple"], [("Alpha", None), ("Beta", None)])
        questions["likert"] = self.add(survey, "likert", "Agreement")
        questions["likert_choices"] = self.options(questions["likert"], [("Low", 1), ("High", 5)])
        questions["custom_likert"] = self.add(survey, "likert", "Custom agreement")
        questions["custom_likert_choices"] = self.options(
            questions["custom_likert"], [("Unsure", None), ("Certain", None)]
        )
        questions["matrix"] = self.add(survey, "matrix", "Rate each area")
        questions["matrix_choices"] = self.options(questions["matrix"], [("Low", 1), ("High", 2)])
        questions["matrix_rows"] = [
            builder.add_matrix_row(question=questions["matrix"], actor=self.manager, label="Quality"),
            builder.add_matrix_row(question=questions["matrix"], actor=self.manager, label="Clarity"),
        ]
        questions["number"] = self.add(
            survey,
            "number",
            "Numeric result",
            configuration={"minimum": "0", "maximum": "10", "step": "0.5"},
        )
        questions["rating"] = self.add(survey, "rating", "Rating")
        questions["linear"] = self.add(survey, "linear_scale", "Linear scale")
        questions["ranking"] = self.add(survey, "ranking", "Rank options")
        questions["ranking_choices"] = self.options(questions["ranking"], [("North", None), ("South", None)])
        questions["date"] = self.add(survey, "date", "Select a date")
        questions["text"] = self.add(survey, "long_text", "Explain your answer")
        self.add(survey, "heading", "Results context")
        self.add(survey, "description", "Structural information")
        self.add(survey, "page_break", "Page break")
        return publish_survey(survey, actor=self.manager), questions

    def response(self, index, submitted_at):
        return SurveyResponse.objects.create(
            survey=self.survey,
            started_at=submitted_at - timedelta(minutes=2),
            submitted_at=submitted_at,
            access_nonce_hash=(str(index) * 64)[:64],
            definition_checksum=self.survey.definition_checksum,
            source=SurveyResponse.Source.BROWSER,
        )

    def answer(self, response, question, *, text="", numeric=None, date_value=None, row=None, selections=()):
        answer = SurveyAnswer.objects.create(
            response=response,
            question=question,
            matrix_row=row,
            text_value=text,
            numeric_value=numeric,
            date_value=date_value,
        )
        for choice, rank in selections:
            SurveyAnswerSelection.objects.create(answer=answer, choice=choice, rank=rank)
        return answer

    def populate(self):
        now = timezone.now()
        first = self.response(1, now - timedelta(days=1))
        second = self.response(2, now - timedelta(minutes=20))
        third = self.response(3, now - timedelta(minutes=5))
        q = self.questions

        self.answer(first, q["single"], selections=[(q["single_choices"][1], None)])
        self.answer(second, q["single"], selections=[(q["single_choices"][0], None)])
        self.answer(first, q["multiple"], selections=[(q["multiple_choices"][0], None), (q["multiple_choices"][1], None)])
        self.answer(second, q["multiple"], selections=[(q["multiple_choices"][0], None)])
        self.answer(first, q["likert"], numeric=1, selections=[(q["likert_choices"][0], None)])
        self.answer(second, q["likert"], numeric=5, selections=[(q["likert_choices"][1], None)])
        self.answer(first, q["custom_likert"], selections=[(q["custom_likert_choices"][0], None)])
        self.answer(first, q["matrix"], row=q["matrix_rows"][0], numeric=1, selections=[(q["matrix_choices"][0], None)])
        self.answer(first, q["matrix"], row=q["matrix_rows"][1], numeric=2, selections=[(q["matrix_choices"][1], None)])
        self.answer(second, q["matrix"], row=q["matrix_rows"][0], numeric=2, selections=[(q["matrix_choices"][1], None)])
        self.answer(first, q["number"], numeric=Decimal("1.5"))
        self.answer(second, q["number"], numeric=Decimal("2.5"))
        self.answer(first, q["rating"], numeric=1)
        self.answer(second, q["rating"], numeric=5)
        self.answer(first, q["linear"], numeric=0)
        self.answer(second, q["linear"], numeric=10)
        self.answer(first, q["ranking"], selections=[(q["ranking_choices"][0], 1), (q["ranking_choices"][1], 2)])
        self.answer(second, q["ranking"], selections=[(q["ranking_choices"][0], 2), (q["ranking_choices"][1], 1)])
        self.answer(first, q["date"], date_value=date(2026, 8, 1))
        self.answer(second, q["date"], date_value=date(2026, 8, 3))
        self.answer(first, q["text"], text="<script>alert('x')</script>")
        self.answer(second, q["text"], text="Useful context")
        return first, second, third, now


class AnalyticsServiceTests(PhaseFourMixin, TestCase):
    def by_prompt(self, analytics, prompt):
        return next(question for question in analytics["questions"] if question["prompt"] == prompt)

    def test_zero_response_summary_and_published_question_order(self):
        analytics = build_survey_analytics(self.survey)
        self.assertEqual(analytics["summary"]["total_responses"], 0)
        self.assertEqual(analytics["summary"]["responses_today"], 0)
        self.assertEqual(analytics["summary"]["first_submission_display"], "—")
        prompts = [question["prompt"] for question in analytics["questions"]]
        self.assertEqual(prompts[0], "Choose one")
        self.assertNotIn("Results context", prompts)
        self.assertNotIn("Structural information", prompts)

    def test_summary_choice_multiple_and_missing_denominators(self):
        first, _second, third, now = self.populate()
        analytics = build_survey_analytics(self.survey, at=now)
        self.assertEqual(analytics["summary"]["total_responses"], 3)
        expected_today = sum(
            timezone.localdate(response.submitted_at) == timezone.localdate(now)
            for response in self.survey.responses.all()
        )
        self.assertEqual(analytics["summary"]["responses_today"], expected_today)
        self.assertEqual(analytics["summary"]["first_submission"], first.submitted_at.isoformat())
        self.assertEqual(analytics["summary"]["last_submission"], third.submitted_at.isoformat())

        single = self.by_prompt(analytics, "Choose one")
        self.assertEqual([row["label"] for row in single["rows"]], ["First", "Second"])
        self.assertEqual([row["count"] for row in single["rows"]], [1, 1])
        self.assertEqual(single["missing_count"], 1)
        self.assertEqual(single["rows"][0]["percentage"], 50.0)

        multiple = self.by_prompt(analytics, "Choose all")
        self.assertEqual([row["percentage"] for row in multiple["rows"]], [100.0, 50.0])
        self.assertIn("more than 100%", multiple["note"])

    def test_likert_matrix_numeric_ranking_and_date_statistics(self):
        self.populate()
        analytics = build_survey_analytics(self.survey)
        likert = self.by_prompt(analytics, "Agreement")
        self.assertEqual(likert["statistics"]["mean"], 3.0)
        self.assertEqual(likert["statistics"]["median"], 3.0)
        custom = self.by_prompt(analytics, "Custom agreement")
        self.assertEqual(custom["statistics"], {})

        matrix = self.by_prompt(analytics, "Rate each area")
        self.assertEqual(matrix["matrix_rows"][0]["weighted_mean"], 1.5)
        self.assertEqual(matrix["matrix_rows"][1]["missing_count"], 2)

        number = self.by_prompt(analytics, "Numeric result")
        self.assertEqual(number["statistics"]["mean"], 2.0)
        self.assertEqual(number["statistics"]["median"], 2.0)
        self.assertEqual(number["statistics"]["minimum"], 1.5)
        self.assertEqual(number["statistics"]["maximum"], 2.5)
        self.assertAlmostEqual(number["statistics"]["standard_deviation"], 0.707106, places=5)
        self.assertEqual(self.by_prompt(analytics, "Rating")["statistics"]["mean"], 3.0)
        self.assertEqual(self.by_prompt(analytics, "Linear scale")["statistics"]["median"], 5.0)

        ranking = self.by_prompt(analytics, "Rank options")
        self.assertEqual([row["average_rank"] for row in ranking["rows"]], [1.5, 1.5])
        self.assertEqual([row["first_choice_count"] for row in ranking["rows"]], [1, 1])
        dates = self.by_prompt(analytics, "Select a date")
        self.assertEqual(dates["statistics"], {"earliest": "2026-08-01", "latest": "2026-08-03"})

    def test_text_values_are_safe_for_template_and_omitted_from_polling_payload(self):
        self.populate()
        analytics = build_survey_analytics(self.survey)
        text = self.by_prompt(analytics, "Explain your answer")
        self.assertEqual(text["text_response_total"], 2)
        self.assertEqual(text["missing_count"], 1)
        self.assertIn("<script>", text["text_responses"][1]["value"])
        polling = build_survey_analytics(self.survey, include_text_values=False)
        self.assertNotIn("text_responses", self.by_prompt(polling, "Explain your answer"))

        self.client.force_login(self.manager)
        page = self.client.get(reverse("surveyhq:survey_analytics", args=[self.survey.pk]))
        self.assertContains(page, "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;")
        self.assertNotContains(page, "<script>alert('x')</script>")

    def test_service_query_count_does_not_scale_per_question(self):
        self.populate()
        with self.assertNumQueries(8):
            build_survey_analytics(self.survey)


class AnalyticsAdminTests(PhaseFourMixin, TestCase):
    def test_permissions_and_no_public_analytics_route(self):
        self.populate()
        url = reverse("surveyhq:survey_analytics", args=[self.survey.pk])
        data_url = reverse("surveyhq:survey_analytics_data", args=[self.survey.pk])
        self.assertTrue(url.startswith(f"{reverse('admin:index')}surveyhq/"))
        self.assertRedirects(self.client.get(url), f"{reverse('admin:login')}?next={url}")
        for user in (self.manager, self.analyst, self.superuser):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.get(data_url).status_code, 200)
        for user in (self.author, self.staff):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.get(data_url).status_code, 403)

        portal_user = User.objects.create_user(username="analytics-client", password="pass")
        self.client_record.user = portal_user
        self.client_record.save(update_fields=["user"])
        self.client.force_login(portal_user)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertNotContains(dashboard, url)
        self.assertNotContains(dashboard, "Survey Analytics")

    def test_analytics_page_uses_local_chart_and_contains_no_export_controls(self):
        self.populate()
        self.client.force_login(self.manager)
        response = self.client.get(reverse("surveyhq:survey_analytics", args=[self.survey.pk]))
        self.assertContains(response, "/static/vendor/chartjs/chart.umd.min.js")
        self.assertContains(response, "Live descriptive analytics")
        self.assertContains(response, "Total Submitted Responses")
        self.assertNotContains(response, "Export CSV")
        self.assertNotContains(response, "Generate PDF")
        chart_license = Path(__file__).resolve().parents[2] / "static/vendor/chartjs/LICENSE"
        self.assertIn("MIT License", chart_license.read_text())
        polling_script = Path(__file__).resolve().parents[2] / "static/js/surveyhq-analytics.js"
        script = polling_script.read_text()
        self.assertIn("setInterval(poll, 20000)", script)
        self.assertIn("document.hidden", script)
        self.assertIn('visibilitychange', script)

    def test_analytics_entry_points_appear_for_published_surveys_with_responses(self):
        self.populate()
        self.client.force_login(self.manager)
        analytics_url = reverse("surveyhq:survey_analytics", args=[self.survey.pk])
        self.assertContains(self.client.get(reverse("surveyhq:dashboard")), analytics_url)
        self.assertContains(
            self.client.get(reverse("surveyhq:survey_detail", args=[self.survey.pk])),
            "View Analytics",
        )
        self.assertContains(
            self.client.get(reverse("surveyhq:response_list"), {"survey": self.survey.pk}),
            analytics_url,
        )

    def test_polling_payload_updates_and_contains_aggregates_only(self):
        self.client.force_login(self.analyst)
        url = reverse("surveyhq:survey_analytics_data", args=[self.survey.pk])
        before = self.client.get(url).json()["analytics"]
        self.assertEqual(before["summary"]["total_responses"], 0)
        self.response(9, timezone.now())
        after_response = self.client.get(url)
        after = after_response.json()["analytics"]
        self.assertEqual(after["summary"]["total_responses"], 1)
        self.assertNotIn("access_nonce_hash", str(after))
        self.assertNotIn("text_responses", str(after))
        self.assertIn("private, no-store", after_response["Cache-Control"])

    def test_analytics_remains_available_when_closed_and_archived(self):
        self.populate()
        self.client.force_login(self.analyst)
        url = reverse("surveyhq:survey_analytics", args=[self.survey.pk])
        self.survey = close_survey(self.survey, actor=self.manager)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.survey = archive_survey(self.survey, actor=self.manager)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_response_review_sort_date_filter_and_no_grant_hash(self):
        first, second, _third, _now = self.populate()
        self.client.force_login(self.analyst)
        response = self.client.get(
            reverse("surveyhq:response_list"),
            {"survey": self.survey.pk, "sort": "oldest", "date_from": timezone.localdate(first.submitted_at)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["response_page"][0].pk, first.pk)
        detail = self.client.get(reverse("surveyhq:response_detail", args=[second.pk]))
        self.assertNotContains(detail, second.access_nonce_hash)
        self.assertNotContains(detail, "Definition checksum")
        self.assertContains(detail, "Question and answer pairs")
