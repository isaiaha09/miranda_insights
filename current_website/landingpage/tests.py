import json
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.templatetags.static import static
from django.urls import reverse
from unittest.mock import patch
from PIL import Image

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


class PwaAssetTests(TestCase):
    def test_manifest_uses_current_branding_and_icon_purposes(self):
        response = self.client.get(reverse("webmanifest"))

        self.assertEqual(response.status_code, 200)
        manifest = response.json()
        self.assertEqual(manifest["name"], "Miranda Insights")
        self.assertEqual(manifest["short_name"], "Miranda Insights")
        self.assertEqual(
            [(icon["src"], icon["sizes"], icon["purpose"]) for icon in manifest["icons"]],
            [
                (static("pwa/icon-192.png"), "192x192", "any"),
                (static("pwa/icon-512.png"), "512x512", "any"),
                (static("pwa/icon-maskable-192.png"), "192x192", "maskable"),
                (static("pwa/icon-maskable-512.png"), "512x512", "maskable"),
            ],
        )
        self.assertEqual(
            [(shortcut["name"], shortcut["url"]) for shortcut in manifest["shortcuts"]],
            [
                ("Services", reverse("services")),
                ("Individual Support", reverse("individual_services")),
                ("Resources", reverse("contact_support")),
                ("Client Portal", reverse("dashboard")),
            ],
        )

    @override_settings(DEBUG=False)
    def test_service_worker_rolls_brand_assets_cache_forward(self):
        response = self.client.get(reverse("service_worker"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "const CACHE_NAME = 'insights-pwa-v5';")
        self.assertContains(response, "'/static/css/contact.css?v=4'")
        for asset in (
            "pwa/icon-32.png",
            "pwa/icon-180.png",
            "pwa/icon-192.png",
            "pwa/icon-512.png",
            "pwa/icon-maskable-192.png",
            "pwa/icon-maskable-512.png",
        ):
            self.assertContains(response, f"'{static(asset)}'")
        self.assertNotContains(response, static("favicon.svg"))
        self.assertEqual(response.headers["Cache-Control"], "max-age=0, no-cache, no-store, must-revalidate, private")

    @override_settings(DEBUG=True)
    def test_debug_service_worker_removes_persistent_pwa_caching(self):
        response = self.client.get(reverse("service_worker"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "const CACHE_PREFIX = 'insights-pwa-';")
        self.assertContains(response, "self.registration.unregister()")
        self.assertContains(response, "event.respondWith(fetch(event.request));")
        self.assertNotContains(response, "const CACHE_NAME")
        self.assertNotContains(response, "cache.addAll(APP_SHELL)")

    @override_settings(DEBUG=True)
    def test_debug_pages_disable_service_worker_registration(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, "serviceWorkerEnabled: false")

    @override_settings(DEBUG=False)
    def test_production_pages_enable_service_worker_registration(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, "serviceWorkerEnabled: true")

    def test_brand_icon_derivatives_have_expected_dimensions(self):
        expected_dimensions = {
            "static/pwa/icon-32.png": (32, 32),
            "static/pwa/icon-180.png": (180, 180),
            "static/pwa/icon-192.png": (192, 192),
            "static/pwa/icon-512.png": (512, 512),
            "static/pwa/icon-maskable-192.png": (192, 192),
            "static/pwa/icon-maskable-512.png": (512, 512),
            "mobile_app/assets/icon.png": (1024, 1024),
            "mobile_app/assets/splash-icon.png": (1024, 1024),
            "mobile_app/assets/favicon.png": (192, 192),
            "mobile_app/assets/drawer-logo.png": (500, 500),
            "mobile_app/assets/android-icon-foreground.png": (1024, 1024),
        }

        for relative_path, dimensions in expected_dimensions.items():
            with self.subTest(relative_path=relative_path):
                with Image.open(Path(settings.BASE_DIR) / relative_path) as image:
                    self.assertEqual(image.size, dimensions)


class MobileBrandConfigTests(TestCase):
    def test_expo_config_uses_current_brand_without_changing_identifiers(self):
        mobile_root = Path(settings.BASE_DIR) / "mobile_app"
        app_config = json.loads((mobile_root / "app.json").read_text())["expo"]

        self.assertEqual(app_config["name"], "Miranda Insights")
        self.assertEqual(app_config["slug"], "insights-mobile")
        self.assertEqual(app_config["icon"], "./assets/icon.png")
        self.assertEqual(app_config["splash"]["image"], "./assets/splash-icon.png")
        self.assertEqual(app_config["ios"]["bundleIdentifier"], "com.mirandainsights.mobile")
        self.assertEqual(app_config["android"]["package"], "com.mirandainsights.mobile")
        self.assertEqual(
            app_config["android"]["adaptiveIcon"]["foregroundImage"],
            "./assets/android-icon-foreground.png",
        )
        self.assertNotIn("monochromeImage", app_config["android"]["adaptiveIcon"])

    def test_native_routes_use_current_public_architecture(self):
        config_source = (Path(settings.BASE_DIR) / "mobile_app" / "src" / "config.ts").read_text()
        route_paths = [
            "/about/",
            "/operational-partnership/",
            "/services/",
            "/individual-services/",
            "/contact/",
            "/dashboard/",
        ]

        positions = [config_source.index(f"path: '{path}'") for path in route_paths]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("path: '/products/'", config_source)
        self.assertNotIn("path: '/faq/'", config_source)
        self.assertIn(
            "PRIMARY_ROUTES[5],\n  PRIMARY_ROUTES[2],\n  PRIMARY_ROUTES[3],\n  PRIMARY_ROUTES[4],",
            config_source,
        )
