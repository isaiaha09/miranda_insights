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

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=to,
        reply_to=reply_to,
        headers=headers,
        connection=connection,
    )
    message.attach_alternative(html_body, "text/html")
    return message.send(fail_silently=False)