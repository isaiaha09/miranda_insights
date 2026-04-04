from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_health_endpoint_reports_ok(self):
        response = self.client.get(reverse("health_check"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["checks"]["database"], True)
        self.assertEqual(response.json()["checks"]["cache"], True)