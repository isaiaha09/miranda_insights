from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class SurveyHqAdminFoundationTests(TestCase):
    def test_anonymous_access_uses_existing_admin_login(self):
        response = self.client.get(reverse("surveyhq:dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_non_staff_user_cannot_access_surveyhq(self):
        user = User.objects.create_user(username="survey-client", password="test-pass-123")
        self.client.force_login(user)

        response = self.client.get(reverse("surveyhq:dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_staff_user_can_access_admin_only_shell(self):
        staff_user = User.objects.create_user(
            username="survey-staff",
            password="test-pass-123",
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse("surveyhq:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/surveyhq/dashboard.html")
        self.assertContains(response, "SurveyHQ")
        self.assertContains(response, "Admin-only foundation")
        self.assertNotContains(response, "participant survey")

    def test_admin_index_exposes_surveyhq_entry_to_staff(self):
        staff_user = User.objects.create_superuser(
            username="survey-admin",
            email="survey-admin@example.com",
            password="test-pass-123",
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Operational Tool")
        self.assertContains(response, "Open SurveyHQ")
        self.assertContains(response, reverse("surveyhq:dashboard"))

    def test_surveyhq_has_no_models_or_migrations(self):
        from django.apps import apps

        app_config = apps.get_app_config("surveyhq")

        self.assertEqual(list(app_config.get_models()), [])
