from __future__ import annotations

from typing import Tuple

import requests
from django.conf import settings
from django.http import HttpRequest


MOBILE_APP_USER_AGENT_TOKEN = "InsightsMobileAppWebView"


def _is_truthy_marker(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_mobile_app_request(request: HttpRequest | None) -> bool:
    if request is None:
        return False

    if _is_truthy_marker(request.GET.get("mobile_app")):
        return True

    if _is_truthy_marker(request.POST.get("mobile_app")):
        return True

    if _is_truthy_marker(request.COOKIES.get("insights_mobile_app")):
        return True

    user_agent = request.META.get("HTTP_USER_AGENT", "")
    return MOBILE_APP_USER_AGENT_TOKEN.lower() in user_agent.lower()


def is_turnstile_enabled() -> bool:
    return bool(getattr(settings, "TURNSTILE_SITE_KEY") and getattr(settings, "TURNSTILE_SECRET_KEY"))


def is_turnstile_enabled_for_request(request: HttpRequest | None) -> bool:
    return is_turnstile_enabled() and not is_mobile_app_request(request)


def verify_turnstile(token: str, remote_ip: str | None = None) -> Tuple[bool, list[str]]:
    if not is_turnstile_enabled():
        return True, []

    if not token:
        return False, ["missing-input-response"]

    payload = {
        "secret": settings.TURNSTILE_SECRET_KEY,
        "response": token,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        response = requests.post(settings.TURNSTILE_VERIFY_URL, data=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return False, ["verification-unavailable"]

    return bool(data.get("success")), list(data.get("error-codes", []))


def verify_turnstile_for_request(request: HttpRequest | None, token: str, remote_ip: str | None = None) -> Tuple[bool, list[str]]:
    if not is_turnstile_enabled_for_request(request):
        return True, []

    return verify_turnstile(token, remote_ip)