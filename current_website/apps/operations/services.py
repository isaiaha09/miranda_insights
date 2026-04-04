from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.accounts.push_notifications import send_mobile_push_notification_to_user
from apps.news.models import NewsletterCampaign
from apps.news.services import send_campaign
from landingpage.emailing import send_email_message

from .models import OutboundJob


logger = logging.getLogger(__name__)
User = get_user_model()


def should_queue_outbound_delivery() -> bool:
    return getattr(settings, "OUTBOUND_DELIVERY_MODE", "sync") == "queue"


def _create_job(*, job_type: str, payload: dict[str, Any], max_attempts: int = 5) -> int:
    OutboundJob.objects.create(
        job_type=job_type,
        payload=payload,
        max_attempts=max_attempts,
    )
    return 1


def dispatch_raw_email(
    *,
    subject: str,
    text_body: str,
    to: list[str],
    from_email: str | None = None,
    reply_to: list[str] | None = None,
    headers: dict[str, str] | None = None,
    html_body: str | None = None,
) -> int:
    if should_queue_outbound_delivery():
        return _create_job(
            job_type=OutboundJob.TYPE_EMAIL,
            payload={
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body,
                "to": list(to),
                "from_email": from_email,
                "reply_to": list(reply_to or []),
                "headers": headers or {},
            },
        )

    return send_email_message(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        to=to,
        from_email=from_email,
        reply_to=reply_to,
        headers=headers,
    )


def dispatch_push_notification_to_user(user, *, title: str, body: str, data: dict | None = None) -> int:
    if user is None:
        return 0

    if should_queue_outbound_delivery():
        return _create_job(
            job_type=OutboundJob.TYPE_PUSH,
            payload={
                "user_id": user.pk,
                "title": title,
                "body": body,
                "data": data or {},
            },
        )

    return send_mobile_push_notification_to_user(user, title=title, body=body, data=data)


def dispatch_newsletter_campaign(campaign: NewsletterCampaign) -> tuple[bool, int, int]:
    if should_queue_outbound_delivery():
        _create_job(
            job_type=OutboundJob.TYPE_NEWSLETTER_CAMPAIGN,
            payload={"campaign_id": campaign.pk},
            max_attempts=3,
        )
        return True, 0, 0

    sent, failed = send_campaign(campaign)
    return False, sent, failed


def _claim_jobs(batch_size: int) -> list[OutboundJob]:
    now = timezone.now()
    lock_timeout = now - timedelta(minutes=10)
    from django.db import transaction

    with transaction.atomic():
        jobs = list(
            OutboundJob.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status=OutboundJob.STATUS_PENDING, run_after__lte=now)
                | Q(status=OutboundJob.STATUS_PROCESSING, locked_at__lt=lock_timeout)
            )
            .order_by("created_at")[:batch_size]
        )
        for job in jobs:
            job.status = OutboundJob.STATUS_PROCESSING
            job.locked_at = now
            job.attempts += 1
            job.last_error = ""
            job.save(update_fields=["status", "locked_at", "attempts", "last_error", "updated_at"])
    return jobs


def _process_email_job(job: OutboundJob) -> int:
    payload = job.payload
    return send_email_message(
        subject=payload["subject"],
        text_body=payload["text_body"],
        html_body=payload.get("html_body"),
        to=payload["to"],
        from_email=payload.get("from_email"),
        reply_to=payload.get("reply_to") or None,
        headers=payload.get("headers") or None,
    )


def _process_push_job(job: OutboundJob) -> int:
    payload = job.payload
    user = User.objects.filter(pk=payload.get("user_id")).first()
    if user is None:
        raise ValueError("Push notification target user no longer exists.")
    return send_mobile_push_notification_to_user(
        user,
        title=payload.get("title", ""),
        body=payload.get("body", ""),
        data=payload.get("data") or {},
    )


def _process_newsletter_campaign_job(job: OutboundJob) -> tuple[int, int]:
    campaign = NewsletterCampaign.objects.filter(pk=job.payload.get("campaign_id")).first()
    if campaign is None:
        raise ValueError("Newsletter campaign no longer exists.")
    return send_campaign(campaign)


def process_pending_jobs(batch_size: int = 25) -> dict[str, int]:
    jobs = _claim_jobs(batch_size)
    summary = {
        "claimed": len(jobs),
        "succeeded": 0,
        "failed": 0,
        "retried": 0,
    }

    processors = {
        OutboundJob.TYPE_EMAIL: _process_email_job,
        OutboundJob.TYPE_PUSH: _process_push_job,
        OutboundJob.TYPE_NEWSLETTER_CAMPAIGN: _process_newsletter_campaign_job,
    }

    for job in jobs:
        processor = processors.get(job.job_type)
        if processor is None:
            job.status = OutboundJob.STATUS_FAILED
            job.completed_at = timezone.now()
            job.last_error = f"No processor registered for {job.job_type}."
            job.locked_at = None
            job.save(update_fields=["status", "completed_at", "last_error", "locked_at", "updated_at"])
            summary["failed"] += 1
            continue

        try:
            processor(job)
        except Exception as exc:
            logger.exception("Outbound job failed", extra={"job_id": job.pk, "job_type": job.job_type})
            job.last_error = str(exc)
            job.locked_at = None
            if job.attempts >= job.max_attempts:
                job.status = OutboundJob.STATUS_FAILED
                job.completed_at = timezone.now()
                summary["failed"] += 1
                job.save(update_fields=["status", "completed_at", "last_error", "locked_at", "updated_at"])
            else:
                job.status = OutboundJob.STATUS_PENDING
                job.run_after = job.next_retry_at()
                summary["retried"] += 1
                job.save(update_fields=["status", "run_after", "last_error", "locked_at", "updated_at"])
            continue

        job.status = OutboundJob.STATUS_SUCCEEDED
        job.completed_at = timezone.now()
        job.locked_at = None
        job.save(update_fields=["status", "completed_at", "locked_at", "updated_at"])
        summary["succeeded"] += 1

    return summary