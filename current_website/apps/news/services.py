from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import NewsletterCampaign, NewsletterSendLog, NewsletterSubscriber


def send_campaign(campaign: NewsletterCampaign, subscribers=None):
    """Send one campaign to active subscribers and persist delivery logs."""
    active_subscribers = subscribers or NewsletterSubscriber.objects.filter(is_active=True)
    sent_count = 0
    failed_count = 0

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")
    body = campaign.rendered_body()

    for subscriber in active_subscribers.iterator():
        try:
            send_mail(
                subject=campaign.subject,
                message=body,
                from_email=from_email,
                recipient_list=[subscriber.email],
                fail_silently=False,
            )
            NewsletterSendLog.objects.create(
                campaign=campaign,
                recipient_email=subscriber.email,
                status=NewsletterSendLog.STATUS_SENT,
            )
            sent_count += 1
        except Exception as exc:
            NewsletterSendLog.objects.create(
                campaign=campaign,
                recipient_email=subscriber.email,
                status=NewsletterSendLog.STATUS_FAILED,
                error_message=str(exc),
            )
            failed_count += 1

    campaign.last_sent_at = timezone.now()
    if campaign.mode == NewsletterCampaign.MODE_AUTOMATED:
        campaign.next_send_at = campaign.compute_next_send_at(campaign.last_sent_at)
    campaign.save(update_fields=["last_sent_at", "next_send_at", "updated_at"])

    return sent_count, failed_count


def process_due_automated_campaigns():
    """Process all automated campaigns due to be sent now."""
    now = timezone.now()
    campaigns = NewsletterCampaign.objects.filter(
        mode=NewsletterCampaign.MODE_AUTOMATED,
        is_active=True,
    )

    processed = 0
    for campaign in campaigns:
        if campaign.next_send_at is None:
            campaign.next_send_at = campaign.compute_next_send_at(now)
            campaign.save(update_fields=["next_send_at", "updated_at"])

        if campaign.next_send_at and campaign.next_send_at <= now:
            send_campaign(campaign)
            processed += 1

    return processed
