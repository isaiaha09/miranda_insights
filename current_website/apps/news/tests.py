from django.test import TestCase, override_settings

from .models import NewsletterCampaign, NewsletterSendLog, NewsletterSubscriber
from .services import send_campaign


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
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
