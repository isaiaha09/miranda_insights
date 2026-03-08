import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.utils import timezone

from .models import NewsletterCampaign, NewsletterSendLog, NewsletterSubscriber


def _parse_direct_recipient_emails(raw_recipients: str):
    """Split comma/newline separated recipients and return valid + invalid lists."""
    valid_emails = []
    invalid_emails = []
    seen = set()

    for token in re.split(r"[,\n\r\t]+", raw_recipients or ""):
        email = token.strip().lower()
        if not email:
            continue
        if email in seen:
            continue
        seen.add(email)

        try:
            validate_email(email)
            valid_emails.append(email)
        except ValidationError:
            invalid_emails.append(email)

    return valid_emails, invalid_emails


def _build_recipient_list(campaign: NewsletterCampaign, subscribers=None):
    """Build recipient list based on campaign targeting options."""
    recipients = []
    seen = set()

    if campaign.include_subscribers:
        active_subscribers = subscribers or NewsletterSubscriber.objects.filter(is_active=True)
        for subscriber in active_subscribers.iterator():
            email = subscriber.email.strip().lower()
            if email and email not in seen:
                recipients.append(email)
                seen.add(email)

    direct_valid, direct_invalid = _parse_direct_recipient_emails(campaign.direct_recipients)
    for email in direct_valid:
        if email not in seen:
            recipients.append(email)
            seen.add(email)

    return recipients, direct_invalid


def send_campaign(campaign: NewsletterCampaign, subscribers=None):
    """Send one campaign to selected recipients and persist delivery logs."""
    sent_count = 0
    failed_count = 0

    from_email = getattr(settings, "NEWSLETTER_FROM_EMAIL", getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com"))
    body = campaign.rendered_body()

    recipients, invalid_direct_recipients = _build_recipient_list(campaign, subscribers)

    for invalid_email in invalid_direct_recipients:
        NewsletterSendLog.objects.create(
            campaign=campaign,
            recipient_email=invalid_email,
            status=NewsletterSendLog.STATUS_FAILED,
            error_message="Invalid email in direct_recipients.",
        )
        failed_count += 1

    for recipient_email in recipients:
        try:
            send_mail(
                subject=campaign.subject,
                message=body,
                from_email=from_email,
                recipient_list=[recipient_email],
                fail_silently=False,
            )
            NewsletterSendLog.objects.create(
                campaign=campaign,
                recipient_email=recipient_email,
                status=NewsletterSendLog.STATUS_SENT,
            )
            sent_count += 1
        except Exception as exc:
            NewsletterSendLog.objects.create(
                campaign=campaign,
                recipient_email=recipient_email,
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
