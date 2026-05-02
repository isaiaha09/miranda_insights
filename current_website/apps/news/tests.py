import tempfile
from datetime import datetime, time, timezone as datetime_timezone
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.templatetags.static import static

from .admin import HasAccountListFilter, NewsletterCampaignAdmin, NewsletterSubscriberAdmin
from .newsletter_blocks import normalize_blocks
from .models import NewsletterBlockTemplate, NewsletterCampaign, NewsletterImageAsset, NewsletterSendLog, NewsletterSubscriber
from .services import send_campaign


TEMP_MEDIA_ROOT = tempfile.mkdtemp()
User = get_user_model()


class PublicPageTests(TestCase):
	def test_services_page_lists_deliverable_examples(self):
		response = self.client.get(reverse("services"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Deliverable Examples")
		self.assertContains(response, "Student Dashboard")
		self.assertContains(response, static("deliverables/student-dashboard.html"))
		self.assertContains(response, static("deliverables/student-data-analysis.png"))
		self.assertContains(response, static("deliverables/student-data-analysis.xlsx"))
		self.assertContains(response, static("deliverables/student-dashboard-presentation.pdf"))
		self.assertContains(response, static("deliverables/deliverable-documentation.pdf"))


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	CONTACT_RECIPIENT="support@example.com",
	DEFAULT_FROM_EMAIL="no-reply@example.com",
	SITE_URL="https://mirandainsights.com",
	TURNSTILE_SITE_KEY="",
	TURNSTILE_SECRET_KEY="",
)
class ContactSupportFlowTests(TestCase):
	def setUp(self):
		self.payload = {
			"name": "Taylor Client",
			"organization": "Northwind",
			"email": "taylor@example.com",
			"phone": "",
			"business_location": "",
			"subject_choice": "support",
			"message": "Need help with the portal.",
		}

	def test_contact_support_redirects_back_to_contact_for_website(self):
		response = self.client.post(reverse("contact_support"), self.payload)

		self.assertRedirects(response, reverse("contact_support"))
		self.assertEqual(len(mail.outbox), 2)
		messages = list(get_messages(response.wsgi_request))
		self.assertEqual(len(messages), 1)
		self.assertEqual(
			str(messages[0]),
			"Thanks, your support request has been received. A confirmation message has been sent to your email.",
		)

	def test_mobile_app_contact_support_redirects_to_dashboard_with_success_message(self):
		user = User.objects.create_user(
			username="mobileclient",
			email="taylor@example.com",
			password="test-pass-123",
			first_name="Taylor",
		)
		self.client.force_login(user)

		response = self.client.post(reverse("contact_support"), {**self.payload, "mobile_app": "1"}, follow=True)

		self.assertRedirects(response, reverse("dashboard"))
		self.assertEqual(len(mail.outbox), 2)
		self.assertContains(
			response,
			"Thanks, your support request has been received. A confirmation message has been sent to your email.",
		)
		self.assertContains(response, "Welcome back, Taylor")


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	SITE_URL="https://mirandainsights.com",
	MEDIA_ROOT=TEMP_MEDIA_ROOT,
	MEDIA_URL="/media/",
	TURNSTILE_SITE_KEY="",
	TURNSTILE_SECRET_KEY="",
)
class NewsletterSendCampaignTests(TestCase):
	def create_campaign(self, **overrides):
		defaults = {
			"name": "Test campaign",
			"subject": "Hello from test",
			"body": "Body text",
			"include_subscribers": True,
			"direct_recipients": "",
		}
		defaults.update(overrides)
		return NewsletterCampaign.objects.create(**defaults)

	def test_send_campaign_direct_recipients_only(self):
		NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		campaign = self.create_campaign(
			include_subscribers=False,
			direct_recipients="direct1@example.com, direct2@example.com",
		)

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 2)
		self.assertEqual(failed, 0)
		logged = list(
			NewsletterSendLog.objects.filter(campaign=campaign, status=NewsletterSendLog.STATUS_SENT)
			.values_list("recipient_email", flat=True)
		)
		self.assertCountEqual(logged, ["direct1@example.com", "direct2@example.com"])

	def test_send_campaign_deduplicates_subscribers_and_direct_recipients(self):
		NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		NewsletterSubscriber.objects.create(email="sub2@example.com", is_active=True)
		campaign = self.create_campaign(
			include_subscribers=True,
			direct_recipients="sub1@example.com, extra@example.com",
		)

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 3)
		self.assertEqual(failed, 0)
		logged = list(
			NewsletterSendLog.objects.filter(campaign=campaign, status=NewsletterSendLog.STATUS_SENT)
			.values_list("recipient_email", flat=True)
		)
		self.assertCountEqual(logged, ["sub1@example.com", "sub2@example.com", "extra@example.com"])

	def test_send_campaign_logs_invalid_direct_recipient(self):
		campaign = self.create_campaign(
			include_subscribers=False,
			direct_recipients="good@example.com, not-an-email",
		)

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 1)
		self.assertEqual(failed, 1)
		failed_log = NewsletterSendLog.objects.get(
			campaign=campaign,
			recipient_email="not-an-email",
			status=NewsletterSendLog.STATUS_FAILED,
		)
		self.assertIn("Invalid email", failed_log.error_message)

	def test_send_campaign_adds_unsubscribe_footer_and_headers(self):
		NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		campaign = self.create_campaign(body="Body text")

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 1)
		self.assertEqual(failed, 0)
		self.assertEqual(len(mail.outbox), 1)
		message = mail.outbox[0]
		self.assertIn(
			"If you wish to not receive anymore newsletters from us, click Unsubscribe.",
			message.body,
		)
		self.assertIn("https://mirandainsights.com/newsletter/unsubscribe/?token=", message.body)
		self.assertEqual(len(message.alternatives), 1)
		html_body, mime_type = message.alternatives[0]
		self.assertEqual(mime_type, "text/html")
		self.assertIn(
			"If you wish to not receive anymore newsletters from us, click <a href=\"https://mirandainsights.com/newsletter/unsubscribe/?token=",
			html_body,
		)
		self.assertIn(">Unsubscribe</a>.", html_body)
		self.assertEqual(message.extra_headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
		self.assertTrue(
			message.extra_headers["List-Unsubscribe"].startswith(
				"<https://mirandainsights.com/newsletter/unsubscribe/?token="
			)
		)

	def test_subscribe_ajax_returns_json_without_redirect(self):
		response = self.client.post(
			reverse("newsletter_subscribe"),
			{"email": "person@example.com"},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["level"], "success")
		self.assertEqual(response.json()["sectionId"], "newsletter-signup")
		self.assertTrue(NewsletterSubscriber.objects.filter(email="person@example.com", is_active=True).exists())

	def test_home_renders_turnstile_widget_when_enabled(self):
		with override_settings(TURNSTILE_SITE_KEY="site-key", TURNSTILE_SECRET_KEY="secret-key"):
			response = self.client.get(reverse("home"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'class="cf-turnstile"', html=False)
		self.assertContains(response, 'data-sitekey="site-key"', html=False)

	def test_subscribe_requires_turnstile_when_enabled(self):
		with override_settings(TURNSTILE_SITE_KEY="site-key", TURNSTILE_SECRET_KEY="secret-key"):
			response = self.client.post(
				reverse("newsletter_subscribe"),
				{"email": "person@example.com"},
				HTTP_X_REQUESTED_WITH="XMLHttpRequest",
			)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.json()["level"], "error")
		self.assertEqual(response.json()["message"], "Security verification failed. Please try again.")
		self.assertFalse(NewsletterSubscriber.objects.filter(email="person@example.com").exists())

	@patch("apps.news.views.verify_turnstile_for_request", return_value=(True, []))
	def test_subscribe_accepts_valid_turnstile_when_enabled(self, verify_turnstile_for_request_mock):
		with override_settings(TURNSTILE_SITE_KEY="site-key", TURNSTILE_SECRET_KEY="secret-key"):
			response = self.client.post(
				reverse("newsletter_subscribe"),
				{
					"email": "person@example.com",
					"cf-turnstile-response": "token-value",
				},
				HTTP_X_REQUESTED_WITH="XMLHttpRequest",
			)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["level"], "success")
		self.assertTrue(NewsletterSubscriber.objects.filter(email="person@example.com", is_active=True).exists())
		verify_turnstile_for_request_mock.assert_called_once()

	def test_unsubscribe_link_deletes_subscriber(self):
		subscriber = NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		campaign = self.create_campaign(body="Body text")

		send_campaign(campaign)

		unsubscribe_url = mail.outbox[0].extra_headers["List-Unsubscribe"].strip("<>")
		parsed_url = urlsplit(unsubscribe_url)
		response = self.client.get(f"{parsed_url.path}?{parsed_url.query}", follow=True)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.redirect_chain)
		self.assertIn("newsletter_status=unsubscribed#newsletter-signup", response.redirect_chain[0][0])
		self.assertFalse(NewsletterSubscriber.objects.filter(pk=subscriber.pk).exists())
		self.assertContains(response, "You have been unsubscribed from newsletter emails.")

	def test_send_campaign_renders_structured_blocks(self):
		NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		campaign = self.create_campaign(
			body="",
			preheader="Quarterly highlights",
			content_blocks=[
				{"type": "heading", "text": "Q1 Highlights", "level": "1", "align": "left"},
				{"type": "paragraph", "text": "A polished newsletter without raw HTML.", "style": "lead", "align": "left"},
				{"type": "button", "text": "Read more", "url": "https://mirandainsights.com/services/", "style": "primary", "align": "center"},
			],
		)

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 1)
		self.assertEqual(failed, 0)
		self.assertEqual(len(mail.outbox), 1)
		message = mail.outbox[0]
		self.assertIn("Q1 Highlights", message.body)
		html_body, _ = message.alternatives[0]
		self.assertIn("Quarterly highlights", html_body)
		self.assertIn("Read more", html_body)
		self.assertIn("https://mirandainsights.com/services/", html_body)

	def test_normalize_blocks_rejects_invalid_image_url(self):
		with self.assertRaises(ValidationError):
			normalize_blocks([
				{"type": "image", "image_url": "notaurl", "alt_text": "Chart"},
			])

	def test_send_campaign_renders_uploaded_image_asset(self):
		NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		asset = NewsletterImageAsset.objects.create(
			name="Hero Chart",
			alt_text="Growth chart",
			default_caption="Monthly growth snapshot",
			image=SimpleUploadedFile(
				"chart.gif",
				b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;",
				content_type="image/gif",
			),
		)
		campaign = self.create_campaign(
			body="",
			content_blocks=[
				{"type": "image", "image_asset_id": asset.pk, "caption": "", "link_url": "", "width": "wide", "alt_text": ""},
			],
		)

		sent, failed = send_campaign(campaign)

		self.assertEqual(sent, 1)
		self.assertEqual(failed, 0)
		self.assertIn("Growth chart", mail.outbox[0].body)
		self.assertIn("Monthly growth snapshot", mail.outbox[0].body)
		html_body, _ = mail.outbox[0].alternatives[0]
		self.assertIn("https://mirandainsights.com/media/newsletter/images/", html_body)
		self.assertIn("Growth chart", html_body)
		self.assertIn("Monthly growth snapshot", html_body)

	def test_normalize_blocks_accepts_uploaded_image_without_url(self):
		blocks = normalize_blocks([
			{"type": "image", "image_asset_id": 7, "alt_text": "", "caption": "", "link_url": "", "width": "full"},
		])
		self.assertEqual(blocks[0]["image_asset_id"], 7)

	def test_default_templates_exist(self):
		self.assertTrue(NewsletterBlockTemplate.objects.filter(slug="hero-spotlight", is_builtin=True).exists())
		self.assertTrue(NewsletterBlockTemplate.objects.filter(slug="event-announcement", is_builtin=True).exists())
		self.assertTrue(NewsletterBlockTemplate.objects.filter(slug="article-digest", is_builtin=True).exists())

	@override_settings(TIME_ZONE="UTC", NEWSLETTER_TIME_ZONE="America/Los_Angeles")
	def test_compute_next_send_at_uses_newsletter_timezone(self):
		campaign = self.create_campaign(
			mode=NewsletterCampaign.MODE_AUTOMATED,
			frequency=NewsletterCampaign.FREQ_DAILY,
			send_time=time(15, 0),
		)

		next_send_at = campaign.compute_next_send_at(
			datetime(2026, 4, 30, 19, 0, tzinfo=datetime_timezone.utc)
		)

		self.assertEqual(
			next_send_at,
			datetime(2026, 4, 30, 22, 0, tzinfo=datetime_timezone.utc),
		)


class NewsletterSubscriberAdminTests(TestCase):
	def setUp(self):
		self.site = AdminSite()
		self.admin = NewsletterSubscriberAdmin(NewsletterSubscriber, self.site)
		self.factory = RequestFactory()

	def test_get_queryset_annotates_has_account(self):
		NewsletterSubscriber.objects.create(email="with-account@example.com", is_active=True)
		NewsletterSubscriber.objects.create(email="without-account@example.com", is_active=True)
		User.objects.create_user(username="withaccount", email="with-account@example.com", password="test-pass-123")

		request = self.factory.get("/admin/news/newslettersubscriber/")
		queryset = self.admin.get_queryset(request)

		results = {subscriber.email: subscriber.has_account for subscriber in queryset}
		self.assertTrue(results["with-account@example.com"])
		self.assertFalse(results["without-account@example.com"])

	def test_has_account_filter_returns_only_matching_rows(self):
		NewsletterSubscriber.objects.create(email="with-account@example.com", is_active=True)
		NewsletterSubscriber.objects.create(email="without-account@example.com", is_active=True)
		User.objects.create_user(username="withaccount", email="with-account@example.com", password="test-pass-123")

		request = self.factory.get("/admin/news/newslettersubscriber/", {"has_account": "yes"})
		filter_instance = HasAccountListFilter(
			request,
			{},
			NewsletterSubscriber,
			self.admin,
		)
		filter_instance.used_parameters = {"has_account": "yes"}
		filtered = filter_instance.queryset(request, self.admin.get_queryset(request))

		self.assertEqual(list(filtered.values_list("email", flat=True)), ["with-account@example.com"])


class NewsletterCampaignAdminTests(TestCase):
	def setUp(self):
		self.site = AdminSite()
		self.admin = NewsletterCampaignAdmin(NewsletterCampaign, self.site)
		self.factory = RequestFactory()
		self.staff_user = User.objects.create_user(
			username="newsletteradmin",
			email="newsletteradmin@example.com",
			password="test-pass-123",
			is_staff=True,
		)

	@override_settings(TIME_ZONE="UTC", NEWSLETTER_TIME_ZONE="America/Los_Angeles")
	def test_save_model_recomputes_next_send_at_when_schedule_changes(self):
		campaign = NewsletterCampaign.objects.create(
			name="Monthly campaign",
			subject="Monthly update",
			body="Body text",
			mode=NewsletterCampaign.MODE_AUTOMATED,
			is_active=True,
			frequency=NewsletterCampaign.FREQ_MONTHLY,
			day_of_month=1,
			send_time=time(8, 0),
			next_send_at=datetime(2026, 5, 1, 15, 0, tzinfo=datetime_timezone.utc),
		)
		campaign.day_of_month = 5
		campaign.send_time = time(15, 0)
		request = self.factory.post(f"/admin/news/newslettercampaign/{campaign.pk}/change/")
		request.user = self.staff_user

		class StubForm:
			changed_data = ["day_of_month", "send_time"]

		with patch("apps.news.models.timezone.now", return_value=datetime(2026, 4, 30, 19, 0, tzinfo=datetime_timezone.utc)):
			self.admin.save_model(request, campaign, StubForm(), change=True)

		campaign.refresh_from_db()
		self.assertEqual(
			campaign.next_send_at,
			datetime(2026, 5, 5, 22, 0, tzinfo=datetime_timezone.utc),
		)

	@override_settings(TIME_ZONE="UTC", NEWSLETTER_TIME_ZONE="America/Los_Angeles")
	def test_last_sent_at_display_uses_newsletter_timezone(self):
		campaign = NewsletterCampaign.objects.create(
			name="Daily campaign",
			subject="Daily update",
			body="Body text",
			mode=NewsletterCampaign.MODE_AUTOMATED,
			is_active=True,
			frequency=NewsletterCampaign.FREQ_DAILY,
			last_sent_at=datetime(2026, 5, 1, 19, 0, tzinfo=datetime_timezone.utc),
		)

		display_value = self.admin.last_sent_at_display(campaign)

		self.assertEqual(display_value, "May 1, 2026, noon")


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	CONTACT_RATE_LIMIT="1/1h",
	CONTACT_RECIPIENT="support@example.com",
	DEFAULT_FROM_EMAIL="no-reply@example.com",
	SITE_URL="https://mirandainsights.com",
	TURNSTILE_SITE_KEY="",
	TURNSTILE_SECRET_KEY="",
)
class ContactSupportThrottleTests(TestCase):
	def test_contact_support_rate_limit_returns_429_after_limit(self):
		payload = {
			"name": "Taylor Client",
			"organization": "Northwind",
			"email": "taylor@example.com",
			"phone": "",
			"business_location": "",
			"subject_choice": "support",
			"message": "Need help with the portal.",
		}

		first_response = self.client.post(reverse("contact_support"), payload, secure=True)
		second_response = self.client.post(reverse("contact_support"), payload, secure=True)

		self.assertEqual(first_response.status_code, 302)
		self.assertEqual(second_response.status_code, 429)
		self.assertContains(second_response, "Too many contact requests were submitted. Please wait and try again.", status_code=429)
		self.assertGreater(int(second_response["Retry-After"]), 0)
		self.assertLessEqual(int(second_response["Retry-After"]), 3600)


@override_settings(
	NEWSLETTER_SUBSCRIBE_RATE_LIMIT="1/1h",
	TURNSTILE_SITE_KEY="",
	TURNSTILE_SECRET_KEY="",
)
class NewsletterSubscribeThrottleTests(TestCase):
	def test_subscribe_rate_limit_returns_429_after_limit(self):
		payload = {"email": "throttle-person@example.com"}
		first_response = self.client.post(reverse("newsletter_subscribe"), payload, secure=True)
		second_response = self.client.post(reverse("newsletter_subscribe"), payload, secure=True)

		self.assertEqual(first_response.status_code, 302)
		self.assertEqual(second_response.status_code, 429)
		self.assertGreater(int(second_response["Retry-After"]), 0)
		self.assertLessEqual(int(second_response["Retry-After"]), 3600)
