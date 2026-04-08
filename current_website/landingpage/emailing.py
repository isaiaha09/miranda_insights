from __future__ import annotations

import socket
import smtplib
import time
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


def smtp_runtime_summary(*, resolve_dns: bool = False) -> dict[str, Any]:
    host = getattr(settings, "EMAIL_HOST", "").strip()
    port = int(getattr(settings, "EMAIL_PORT", 0) or 0)
    summary: dict[str, Any] = {
        "backend": getattr(settings, "EMAIL_BACKEND", ""),
        "host": host,
        "port": port,
        "use_tls": bool(getattr(settings, "EMAIL_USE_TLS", False)),
        "use_ssl": bool(getattr(settings, "EMAIL_USE_SSL", False)),
        "timeout": int(getattr(settings, "EMAIL_TIMEOUT", 10) or 10),
        "delivery_mode": getattr(settings, "OUTBOUND_DELIVERY_MODE", "sync"),
        "default_from_email": getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        "contact_recipient": getattr(settings, "CONTACT_RECIPIENT", ""),
        "has_username": bool(getattr(settings, "EMAIL_HOST_USER", "")),
        "has_password": bool(getattr(settings, "EMAIL_HOST_PASSWORD", "")),
    }

    if resolve_dns and host and port:
        try:
            dns_start = time.perf_counter()
            addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            summary["dns_ms"] = round((time.perf_counter() - dns_start) * 1000, 2)
            summary["resolved_addresses"] = sorted({item[4][0] for item in addrinfo})
        except Exception as exc:
            summary["dns_error_type"] = type(exc).__name__
            summary["dns_error"] = str(exc)

    return summary


def smtp_diagnostics(
    *,
    host_override: str | None = None,
    port_override: int | None = None,
    use_tls_override: bool | None = None,
    use_ssl_override: bool | None = None,
) -> dict[str, Any]:
    host = (host_override or getattr(settings, "EMAIL_HOST", "")).strip()
    port = int(port_override if port_override is not None else (getattr(settings, "EMAIL_PORT", 0) or 0))
    username = getattr(settings, "EMAIL_HOST_USER", "")
    password = getattr(settings, "EMAIL_HOST_PASSWORD", "")
    use_tls = bool(getattr(settings, "EMAIL_USE_TLS", False) if use_tls_override is None else use_tls_override)
    use_ssl = bool(getattr(settings, "EMAIL_USE_SSL", False) if use_ssl_override is None else use_ssl_override)
    timeout = int(getattr(settings, "EMAIL_TIMEOUT", 10) or 10)

    result: dict[str, Any] = smtp_runtime_summary(resolve_dns=False)
    result.update(
        {
            "host": host,
            "port": port,
            "use_tls": use_tls,
            "use_ssl": use_ssl,
            "timeout": timeout,
            "has_username": bool(username),
            "has_password": bool(password),
        }
    )

    if use_tls and use_ssl:
        result.update(
            {
                "ok": False,
                "stage": "configuration",
                "error": "EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be enabled.",
            }
        )
        return result

    if not host or not port:
        result.update(
            {
                "ok": False,
                "stage": "configuration",
                "error": "EMAIL_HOST or EMAIL_PORT is not configured.",
            }
        )
        return result

    try:
        dns_start = time.perf_counter()
        addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        result["dns_ms"] = round((time.perf_counter() - dns_start) * 1000, 2)
        result["resolved_addresses"] = sorted({item[4][0] for item in addrinfo})
    except Exception as exc:
        result.update(
            {
                "ok": False,
                "stage": "dns",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        return result

    server = None
    try:
        connect_start = time.perf_counter()
        if use_ssl:
            server = smtplib.SMTP_SSL(host=host, port=port, timeout=timeout)
        else:
            server = smtplib.SMTP(host=host, port=port, timeout=timeout)
        result["connect_ms"] = round((time.perf_counter() - connect_start) * 1000, 2)

        ehlo_code, ehlo_message = server.ehlo()
        result["ehlo_code"] = ehlo_code
        result["ehlo_message"] = ehlo_message.decode("utf-8", errors="replace") if isinstance(ehlo_message, bytes) else str(ehlo_message)

        if use_tls and not use_ssl:
            tls_start = time.perf_counter()
            server.starttls()
            result["starttls_ms"] = round((time.perf_counter() - tls_start) * 1000, 2)
            post_tls_ehlo_code, _ = server.ehlo()
            result["post_starttls_ehlo_code"] = post_tls_ehlo_code

        if username:
            login_start = time.perf_counter()
            server.login(username, password)
            result["login_ms"] = round((time.perf_counter() - login_start) * 1000, 2)

        result.update({"ok": True, "stage": "complete"})
        return result
    except Exception as exc:
        result.update(
            {
                "ok": False,
                "stage": "smtp",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        return result
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


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