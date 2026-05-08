from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from landingpage.health import SkipHealthCheckRequestFilter


class HealthCheckTests(TestCase):
    def test_request_log_filter_skips_health_endpoint(self):
        filter_instance = SkipHealthCheckRequestFilter()

        health_record = type("Record", (), {"request": type("Request", (), {"path_info": "/health/"})()})()
        dashboard_record = type("Record", (), {"request": type("Request", (), {"path_info": "/dashboard/"})()})()

        self.assertEqual(filter_instance.filter(health_record), False)
        self.assertEqual(filter_instance.filter(dashboard_record), True)

    def test_health_endpoint_reports_ok(self):
        response = self.client.get(reverse("health_check"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["checks"]["database"], True)
        self.assertEqual(response.json()["checks"]["cache"], True)

    @patch("landingpage.health.logger.warning")
    @patch("landingpage.health.connections")
    def test_health_endpoint_reports_degraded_without_error_logging(self, mock_connections, mock_warning):
        mock_connections.__getitem__.return_value.cursor.side_effect = RuntimeError("database is full")

        response = self.client.get(reverse("health_check"), secure=True)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["checks"]["database"], False)
        self.assertEqual(response.json()["checks"]["cache"], True)
        mock_warning.assert_called_once_with("Health check database probe failed", exc_info=True)