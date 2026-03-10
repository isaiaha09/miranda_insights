from __future__ import annotations

from typing import Tuple

import requests
from django.conf import settings


def is_turnstile_enabled() -> bool:
    return bool(getattr(settings, "TURNSTILE_SITE_KEY") and getattr(settings, "TURNSTILE_SECRET_KEY"))


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