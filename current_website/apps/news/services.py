import re
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.urls import reverse
from django.utils.html import escape
from django.utils import timezone
from django.template.loader import render_to_string

from landingpage.emailing import build_email_context

from .models import NewsletterCampaign, NewsletterSendLog, NewsletterSubscriber


UNSUBSCRIBE_TOKEN_SALT = "news.unsubscribe"
UNSUBSCRIBE_LABEL = "Unsubscribe"
UNSUBSCRIBE_FOOTER_TEXT = "If you wish to not receive anymore newsletters from us, click"


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


def build_unsubscribe_token(recipient_email: str) -> str:
    return signing.dumps({"email": recipient_email}, salt=UNSUBSCRIBE_TOKEN_SALT)


def get_unsubscribe_email(token: str) -> str:
    payload = signing.loads(token, salt=UNSUBSCRIBE_TOKEN_SALT)
    return payload["email"]


def build_unsubscribe_url(recipient_email: str) -> str:
    base_url = getattr(settings, "SITE_URL", "http://localhost:8000").rstrip("/")
    path = reverse("newsletter_unsubscribe")
    query = urlencode({"token": build_unsubscribe_token(recipient_email)})
    return f"{base_url}{path}?{query}"


def _build_campaign_body(campaign: NewsletterCampaign, recipient_email: str) -> str:
    body = campaign.rendered_body().rstrip()
    unsubscribe_url = build_unsubscribe_url(recipient_email)
    return (
        f"{body}\n\n"
        f"{UNSUBSCRIBE_FOOTER_TEXT} {UNSUBSCRIBE_LABEL}.\n"
        f"{unsubscribe_url}"
    )


def _build_campaign_html_body(campaign: NewsletterCampaign, recipient_email: str) -> str:
    return render_to_string(
        "emails/newsletter_campaign.html",
        build_email_context(
            {
                "email_title": campaign.subject,
                "heading": campaign.subject,
                "subheading": "Latest updates from Miranda Insights.",
                "body_html": escape(campaign.rendered_body().rstrip()).replace("\n", "<br>"),
                "unsubscribe_url": build_unsubscribe_url(recipient_email),
                "unsubscribe_footer_text": UNSUBSCRIBE_FOOTER_TEXT,
                "unsubscribe_label": UNSUBSCRIBE_LABEL,
            }
        ),
    )


def _build_campaign_headers(recipient_email: str) -> dict[str, str]:
    unsubscribe_url = build_unsubscribe_url(recipient_email)
    return {
        "List-Unsubscribe": f"<{unsubscribe_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def send_campaign(campaign: NewsletterCampaign, subscribers=None):
    """Send one campaign to selected recipients and persist delivery logs."""
    sent_count = 0
    failed_count = 0

    from_email = getattr(settings, "NEWSLETTER_FROM_EMAIL", getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com"))

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
            message = EmailMultiAlternatives(
                subject=campaign.subject,
                body=_build_campaign_body(campaign, recipient_email),
                from_email=from_email,
                to=[recipient_email],
                headers=_build_campaign_headers(recipient_email),
            )
            message.attach_alternative(_build_campaign_html_body(campaign, recipient_email), "text/html")
            message.send(fail_silently=False)
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
