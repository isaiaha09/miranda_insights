from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.conf import settings
from django.core.cache import cache
from django.test import Client as TestClient
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from apps.clients.models import Client

from . import builder
from .exceptions import SurveyStructureLocked
from .lifecycle import archive_survey, close_survey, create_draft, publish_survey, rotate_access_code
from .models import (
    Survey,
    SurveyAnswer,
    SurveyAnswerSelection,
    SurveyChoice,
    SurveyMatrixRow,
    SurveyQuestion,
    SurveyResponse,
)
from .participant import (
    COMPLETION_SESSION_KEY,
    GRANT_SESSION_KEY,
    DuplicateParticipantSubmission,
    ParticipantAccessError,
    ParticipantSurveyForm,
    get_participant_grant,
    submit_participant_response,
    validate_granted_survey,
)
from .participant_views import participant_entry
from .participant_access import participant_entry_path
from .permissions import ANALYSTS_GROUP, AUTHORS_GROUP, MANAGERS_GROUP


User = get_user_model()


class PhaseThreeMixin:
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user(username="phase3-manager", password="pass", is_staff=True)
        self.manager.groups.add(Group.objects.get(name=MANAGERS_GROUP))
        self.author = User.objects.create_user(username="phase3-author", password="pass", is_staff=True)
        self.author.groups.add(Group.objects.get(name=AUTHORS_GROUP))
        self.analyst = User.objects.create_user(username="phase3-analyst", password="pass", is_staff=True)
        self.analyst.groups.add(Group.objects.get(name=ANALYSTS_GROUP))
        self.client_record = Client.objects.create(
            organization_name="Somis Union School District",
            contact_name="Taylor Rivera",
            contact_email="taylor@example.com",
        )

    def draft(self, **overrides):
        values = {
            "client": self.client_record,
            "title": "Participant Experience Survey",
            "reporting_month": 8,
            "reporting_year": 2026,
            "actor": self.manager,
        }
        values.update(overrides)
        return create_draft(**values)

    def publish_simple(self, **overrides):
        survey = self.draft(**overrides)
        builder.create_question(
            survey=survey,
            actor=self.manager,
            question_type=SurveyQuestion.Type.SHORT_TEXT,
            prompt="What should we know?",
            required=True,
            configuration={"max_length": 100},
        )
        return publish_survey(survey, actor=self.manager)

    def grant(self, survey):
        response = self.client.post(self.entry_url(), {"survey_code": survey.access_code})
        self.assertRedirects(response, reverse("surveyhq_participant:introduction"))
        return self.client.session[GRANT_SESSION_KEY]

    def entry_url(self):
        return participant_entry_path()


class ParticipantEntryTests(PhaseThreeMixin, TestCase):
    def test_routes_are_hidden_standalone_and_security_headers_apply(self):
        entry = self.entry_url()
        self.assertTrue(entry.startswith("/surveyhq/participate/"))
        self.assertNotEqual(entry, "/surveyhq/participate/")
        self.assertEqual(resolve(entry).namespace, "surveyhq_participant")
        response = self.client.get(entry)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter your survey code")
        self.assertNotContains(response, "Client Portal")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow, noarchive")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        base = self.client.get(reverse("surveyhq_participant:entry_base"))
        self.assertEqual(base.status_code, 404)
        self.assertIn("no-store", base["Cache-Control"])

    def test_code_entry_preserves_strict_csrf_and_accepts_same_origin_post(self):
        survey = self.publish_simple()
        csrf_client = TestClient(enforce_csrf_checks=True)
        entry_url = self.entry_url()
        entry = csrf_client.get(entry_url)
        token = entry.cookies["csrftoken"].value

        missing = csrf_client.post(entry_url, {"survey_code": survey.access_code})
        self.assertEqual(missing.status_code, 403)

        invalid = csrf_client.post(
            entry_url,
            {"survey_code": "AAAAA1", "csrfmiddlewaretoken": token},
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "unavailable or the code is invalid")

        valid = csrf_client.post(
            entry_url,
            {"survey_code": survey.access_code, "csrfmiddlewaretoken": token},
            HTTP_ORIGIN="http://testserver",
        )
        self.assertRedirects(valid, reverse("surveyhq_participant:introduction"))

        opaque = csrf_client.post(
            entry_url,
            {"survey_code": survey.access_code, "csrfmiddlewaretoken": token},
            HTTP_ORIGIN="null",
        )
        self.assertEqual(opaque.status_code, 403)
        self.assertFalse(getattr(participant_entry, "csrf_exempt", False))
        self.assertNotIn("*", settings.CSRF_TRUSTED_ORIGINS)
        self.assertNotIn("null", settings.CSRF_TRUSTED_ORIGINS)

    def test_code_is_exact_case_sensitive_and_all_unavailable_states_are_generic(self):
        open_survey = self.publish_simple()
        invalid = self.client.post(self.entry_url(), {"survey_code": "AAAAA1"})
        wrong_case = self.client.post(
            self.entry_url(), {"survey_code": open_survey.access_code.swapcase()}
        )
        draft = self.draft(title="Draft")
        unavailable = self.client.post(
            self.entry_url(), {"survey_code": draft.access_code}
        )
        for response in (invalid, wrong_case, unavailable):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "unavailable or the code is invalid")
        self.assertFalse(SurveyResponse.objects.exists())

    @override_settings(
        THROTTLE_ENABLED=True,
        SURVEYHQ_ENTRY_IP_RATE_LIMIT="2/15m",
        SURVEYHQ_ENTRY_CODE_RATE_LIMIT="2/15m",
    )
    def test_entry_attempts_are_throttled_without_raw_code_cache_keys(self):
        cache.clear()
        url = self.entry_url()
        self.client.post(url, {"survey_code": "Secret1"})
        self.client.post(url, {"survey_code": "Secret2"})
        limited = self.client.post(url, {"survey_code": "Secret3"})
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Retry-After", limited)

    def test_grant_has_only_approved_values_and_no_response_is_created(self):
        survey = self.publish_simple(show_client_name_to_participants=True)
        grant = self.grant(survey)
        self.assertEqual(
            set(grant),
            {"survey_id", "nonce", "issued_at", "expires_at", "definition_checksum"},
        )
        self.assertNotIn(survey.access_code, str(grant))
        self.assertGreaterEqual(len(grant["nonce"]), 48)
        self.assertFalse(SurveyResponse.objects.exists())
        intro = self.client.get(reverse("surveyhq_participant:introduction"))
        self.assertContains(intro, survey.client_name_snapshot)

    def test_concurrent_survey_grants_replace_one_another_without_codes_in_urls(self):
        first = self.publish_simple(title="First")
        second = self.publish_simple(title="Second")
        self.grant(first)
        self.grant(second)
        self.assertEqual(self.client.session[GRANT_SESSION_KEY]["survey_id"], str(second.pk))
        for route in ("introduction", "survey", "thank_you"):
            self.assertNotIn(first.access_code, reverse(f"surveyhq_participant:{route}"))


class ParticipantFormAndSubmissionTests(PhaseThreeMixin, TestCase):
    def add_choices(self, question, labels):
        return [builder.add_choice(question=question, actor=self.manager, label=label) for label in labels]

    def build_all_types(self):
        survey = self.draft(
            show_client_name_to_participants=True,
            collection_mode=None,
        )
        questions = {}

        def add(question_type, prompt, **kwargs):
            question = builder.create_question(
                survey=survey,
                actor=self.manager,
                question_type=question_type,
                prompt=prompt,
                **kwargs,
            )
            questions[question.export_key] = question
            return question

        add(SurveyQuestion.Type.HEADING, "About your experience")
        add(SurveyQuestion.Type.DESCRIPTION, "Please answer thoughtfully.")
        add(SurveyQuestion.Type.SHORT_TEXT, "Short response", required=True, configuration={"max_length": 20})
        add(SurveyQuestion.Type.LONG_TEXT, "Long response")
        add(SurveyQuestion.Type.EMAIL, "Email", required=True)
        add(SurveyQuestion.Type.NUMBER, "Number", required=True, configuration={"minimum": "0", "maximum": "10", "step": "2"})
        for qtype, prompt in (
            (SurveyQuestion.Type.SINGLE_CHOICE, "Single"),
            (SurveyQuestion.Type.MULTIPLE_CHOICE, "Multiple"),
            (SurveyQuestion.Type.DROPDOWN, "Dropdown"),
        ):
            self.add_choices(add(qtype, prompt, required=True), ["First option", "Second option"])
        add(SurveyQuestion.Type.YES_NO, "Yes or no", required=True)
        add(SurveyQuestion.Type.LIKERT, "Agreement", required=True, preset="five_agreement")
        add(SurveyQuestion.Type.RATING, "Rating", required=True)
        add(SurveyQuestion.Type.LINEAR_SCALE, "Scale", required=True)
        matrix = add(SurveyQuestion.Type.MATRIX, "Matrix", required=True)
        self.add_choices(matrix, ["Low", "High"])
        builder.add_matrix_row(question=matrix, actor=self.manager, label="Quality")
        builder.add_matrix_row(question=matrix, actor=self.manager, label="Clarity")
        ranking = add(SurveyQuestion.Type.RANKING, "Ranking", required=True)
        self.add_choices(ranking, ["Alpha", "Beta", "Gamma"])
        add(SurveyQuestion.Type.PAGE_BREAK, "Page break")
        add(SurveyQuestion.Type.DATE, "Date", required=True)
        return publish_survey(survey, actor=self.manager), questions

    def valid_payload(self, survey):
        by_prompt = {q.prompt: q for q in survey.questions.prefetch_related("choices", "matrix_rows")}
        payload = {}
        values = {
            "Short response": "Clear progress",
            "Long response": "Longer context",
            "Email": "person@example.com",
            "Number": "4",
            "Single": "opt001",
            "Multiple": ["opt001", "opt002"],
            "Dropdown": "opt002",
            "Yes or no": "yes",
            "Agreement": "scale04",
            "Rating": "5",
            "Scale": "8",
            "Date": "2026-08-19",
        }
        for prompt, value in values.items():
            payload[by_prompt[prompt].export_key] = value
        matrix = by_prompt["Matrix"]
        payload[f"{matrix.export_key}__row001"] = "opt001"
        payload[f"{matrix.export_key}__row002"] = "opt002"
        ranking = by_prompt["Ranking"]
        payload[f"{ranking.export_key}__opt001"] = "2"
        payload[f"{ranking.export_key}__opt002"] = "1"
        payload[f"{ranking.export_key}__opt003"] = "3"
        return payload

    def test_all_types_render_in_published_order_and_ranking_has_no_js_fallback(self):
        survey, _questions = self.build_all_types()
        self.grant(survey)
        response = self.client.get(reverse("surveyhq_participant:survey"))
        self.assertEqual(response.status_code, 200)
        prompts = [q.prompt for q in survey.questions.order_by("position") if q.question_type != "page_break"]
        html = response.content.decode()
        positions = [html.index(prompt) for prompt in prompts]
        self.assertEqual(positions, sorted(positions))
        self.assertContains(response, "This numbered control works without JavaScript")
        self.assertContains(response, '<select name=')
        self.assertContains(response, "First option")
        self.assertLess(html.index("First option"), html.index("Second option"))

    def test_invalid_submission_preserves_values_and_creates_nothing(self):
        survey, _questions = self.build_all_types()
        self.grant(survey)
        payload = self.valid_payload(survey)
        payload["q003"] = "This response exceeds twenty characters"
        payload["q005"] = "not-an-email"
        payload["q006"] = "3"
        payload["q015__opt001"] = "1"
        payload["q015__opt002"] = "1"
        response = self.client.post(reverse("surveyhq_participant:survey"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please review your responses")
        self.assertContains(response, "This response exceeds twenty characters")
        self.assertFalse(SurveyResponse.objects.exists())
        self.assertFalse(SurveyAnswer.objects.exists())

    def test_atomic_submission_stores_typed_answers_ordered_selections_and_coarse_source(self):
        survey, _questions = self.build_all_types()
        self.grant(survey)
        response = self.client.post(
            reverse("surveyhq_participant:survey") + "?mobile_app=1",
            self.valid_payload(survey),
        )
        self.assertRedirects(response, reverse("surveyhq_participant:thank_you"))
        saved = SurveyResponse.objects.get()
        self.assertEqual(saved.source, SurveyResponse.Source.WEBVIEW)
        self.assertNotEqual(saved.access_nonce_hash, self.client.session.get(GRANT_SESSION_KEY, ""))
        self.assertGreater(SurveyAnswer.objects.filter(response=saved).count(), 10)
        ranks = list(
            SurveyAnswerSelection.objects.filter(answer__response=saved, rank__isnull=False)
            .order_by("rank")
            .values_list("rank", flat=True)
        )
        self.assertEqual(ranks, [1, 2, 3])
        marker = self.client.session[COMPLETION_SESSION_KEY]
        self.assertEqual(set(marker), {"expires_at"})
        self.assertNotIn(str(saved.pk), str(marker))
        thank_you = self.client.get(reverse("surveyhq_participant:thank_you"))
        self.assertContains(thank_you, "Your response has been submitted successfully")

    def test_duplicate_nonce_cannot_create_a_second_response(self):
        survey = self.publish_simple()
        self.grant(survey)
        request = RequestFactory().post(reverse("surveyhq_participant:survey"))
        grant_request = RequestFactory().get("/")
        grant_request.session = self.client.session
        grant = get_participant_grant(grant_request)
        form = ParticipantSurveyForm({"q001": "One"}, survey=survey)
        self.assertTrue(form.is_valid(), form.errors)
        submit_participant_response(grant=grant, form=form, request=request)
        with self.assertRaises(DuplicateParticipantSubmission):
            submit_participant_response(grant=grant, form=form, request=request)
        self.assertEqual(SurveyResponse.objects.count(), 1)


class LifecycleAndAdminTests(PhaseThreeMixin, TestCase):
    def test_close_grace_archive_and_rotation_rules(self):
        now = timezone.now()
        survey = self.publish_simple()
        self.grant(survey)
        grant_request = RequestFactory().get("/")
        grant_request.session = self.client.session
        grant = get_participant_grant(grant_request, at=now)
        old_code = survey.access_code
        rotate_access_code(survey, actor=self.manager)
        validate_granted_survey(grant, at=now + timedelta(minutes=1))
        survey = close_survey(survey, actor=self.manager, at=now + timedelta(minutes=5))
        validate_granted_survey(grant, at=now + timedelta(minutes=50))
        survey = archive_survey(survey, actor=self.manager, at=now + timedelta(minutes=51))
        validate_granted_survey(grant, at=now + timedelta(minutes=59))
        with self.assertRaises(ParticipantAccessError):
            validate_granted_survey(grant, at=now + timedelta(minutes=66))
        self.assertNotEqual(old_code, Survey.objects.get(pk=survey.pk).access_code)

    def test_participant_visibility_flag_is_locked_after_publication(self):
        survey = self.publish_simple(show_client_name_to_participants=True)
        survey.show_client_name_to_participants = False
        with self.assertRaises(SurveyStructureLocked):
            survey.save()

    def test_admin_participant_resources_qr_and_response_permissions(self):
        survey = self.publish_simple()
        self.client.force_login(self.manager)
        page = self.client.get(reverse("surveyhq:participant_access"))
        self.assertEqual(page.status_code, 200)
        entry_url = page.context["entry_url"]
        self.assertTrue(entry_url.endswith(self.entry_url()))
        self.assertNotIn(survey.access_code, entry_url)

        fake_image = MagicMock()
        fake_image.save.side_effect = lambda output, format: output.write(b"PNG")
        with patch("apps.surveyhq.views.qrcode.QRCode") as qr_class:
            qr_class.return_value.make_image.return_value = fake_image
            qr_response = self.client.get(reverse("surveyhq:participant_qr"))
            qr_class.return_value.add_data.assert_called_once_with(entry_url)
        self.assertEqual(qr_response.status_code, 200)
        self.assertEqual(qr_response["Content-Type"], "image/png")
        self.assertIn("attachment", qr_response["Content-Disposition"])

        self.client.force_login(self.author)
        self.assertEqual(self.client.get(reverse("surveyhq:participant_access")).status_code, 403)
        self.client.force_login(self.analyst)
        self.assertEqual(self.client.get(reverse("surveyhq:participant_access")).status_code, 403)

    def test_manager_and_analyst_can_inspect_responses_but_author_cannot(self):
        survey = self.publish_simple()
        self.grant(survey)
        self.client.post(reverse("surveyhq_participant:survey"), {"q001": "Verified answer"})
        saved = SurveyResponse.objects.get()
        for user in (self.manager, self.analyst):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("surveyhq:response_list")).status_code, 200)
            detail = self.client.get(reverse("surveyhq:response_detail", args=[saved.pk]))
            self.assertContains(detail, "Verified answer")
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(reverse("surveyhq:response_list")).status_code, 403)

    @override_settings(DEBUG=False)
    def test_service_worker_excludes_participant_path_from_cache_and_offline_fallback(self):
        response = self.client.get(reverse("service_worker"))
        self.assertContains(response, "/surveyhq/participate/")
        content = response.content.decode()
        exclusion = content.index("requestUrl.pathname.indexOf('/surveyhq/participate/')")
        navigation_cache = content.index("event.request.mode === 'navigate'")
        self.assertLess(exclusion, navigation_cache)
        self.assertIn("event.respondWith(fetch(event.request))", content[exclusion:navigation_cache])
