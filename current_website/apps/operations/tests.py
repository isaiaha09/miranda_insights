from django.core import mail
from django.test import TestCase, override_settings

from apps.news.models import NewsletterCampaign, NewsletterSubscriber
from landingpage.emailing import send_templated_email

from .models import OutboundJob
from .services import dispatch_newsletter_campaign, process_pending_jobs


@override_settings(
    OUTBOUND_DELIVERY_MODE="queue",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@example.com",
    SITE_URL="https://mirandainsights.com",
    NEWSLETTER_FROM_EMAIL="news@example.com",
)
class OutboundJobTests(TestCase):
    def test_templated_email_is_queued_and_processed(self):
        queued = send_templated_email(
            subject="Queued message",
            to=["person@example.com"],
            template_prefix="username_recovery",
            context={
                "email_title": "Queued message",
                "heading": "Queued message",
                "subheading": "Testing queue delivery.",
                "usernames": ["person"],
            },
            from_email="no-reply@example.com",
        )

        self.assertEqual(queued, 1)
        self.assertEqual(OutboundJob.objects.count(), 1)

        summary = process_pending_jobs()

        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["person@example.com"])

    def test_newsletter_campaign_is_queued_and_processed(self):
        NewsletterSubscriber.objects.create(email="subscriber@example.com", is_active=True)
        campaign = NewsletterCampaign.objects.create(
            name="Queued campaign",
            subject="Queued campaign",
            body="Body text",
            include_subscribers=True,
            direct_recipients="",
        )

        queued, sent, failed = dispatch_newsletter_campaign(campaign)

        self.assertTrue(queued)
        self.assertEqual(sent, 0)
        self.assertEqual(failed, 0)
        self.assertEqual(OutboundJob.objects.count(), 1)

        summary = process_pending_jobs()

        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["subscriber@example.com"])