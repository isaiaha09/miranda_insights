from urllib.parse import urlsplit

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import NewsletterCampaign, NewsletterSendLog, NewsletterSubscriber
from .services import send_campaign


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	SITE_URL="https://mirandainsights.com",
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

	def test_unsubscribe_link_deactivates_subscriber(self):
		subscriber = NewsletterSubscriber.objects.create(email="sub1@example.com", is_active=True)
		campaign = self.create_campaign(body="Body text")

		send_campaign(campaign)

		unsubscribe_url = mail.outbox[0].extra_headers["List-Unsubscribe"].strip("<>")
		parsed_url = urlsplit(unsubscribe_url)
		response = self.client.get(f"{parsed_url.path}?{parsed_url.query}", follow=True)

		subscriber.refresh_from_db()
		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.redirect_chain)
		self.assertIn("newsletter_status=unsubscribed#newsletter-signup", response.redirect_chain[0][0])
		self.assertFalse(subscriber.is_active)
		self.assertIsNotNone(subscriber.unsubscribed_at)
		self.assertContains(response, "You have been unsubscribed from newsletter emails.")
