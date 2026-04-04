from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def build_email_context(context: dict[str, Any] | None = None) -> dict[str, Any]:
    base_context = {
        "brand_name": "Insights",
        "company_name": "Miranda Insights",
        "site_url": getattr(settings, "SITE_URL", "http://localhost:8000").rstrip("/"),
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@mirandainsights.com"),
    }
    if context:
        base_context.update(context)
    return base_context


def normalize_email_subject(subject: str) -> str:
    return " ".join(str(subject or "").splitlines()).strip()


def send_email_message(
    *,
    subject: str,
    text_body: str,
    to: list[str],
    from_email: str | None = None,
    reply_to: list[str] | None = None,
    headers: dict[str, str] | None = None,
    html_body: str | None = None,
    connection=None,
) -> int:
    message = EmailMultiAlternatives(
        subject=normalize_email_subject(subject),
        body=text_body,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=to,
        reply_to=reply_to,
        headers=headers,
        connection=connection,
    )
    if html_body:
        message.attach_alternative(html_body, "text/html")
    return message.send(fail_silently=False)


def send_templated_email(
    *,
    subject: str,
    to: list[str],
    template_prefix: str,
    context: dict[str, Any] | None = None,
    from_email: str | None = None,
    reply_to: list[str] | None = None,
    headers: dict[str, str] | None = None,
    connection=None,
) -> int:
    full_context = build_email_context(context)
    text_body = render_to_string(f"emails/{template_prefix}.txt", full_context)
    html_body = render_to_string(f"emails/{template_prefix}.html", full_context)

    if getattr(settings, "OUTBOUND_DELIVERY_MODE", "sync") == "queue":
        from apps.operations.services import dispatch_raw_email

        return dispatch_raw_email(
            subject=normalize_email_subject(subject),
            text_body=text_body,
            html_body=html_body,
            to=to,
            from_email=from_email or settings.DEFAULT_FROM_EMAIL,
            reply_to=reply_to,
            headers=headers,
        )

    return send_email_message(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        from_email=from_email,
        to=to,
        reply_to=reply_to,
        headers=headers,
        connection=connection,
    )