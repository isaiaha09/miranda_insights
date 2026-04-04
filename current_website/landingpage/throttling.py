from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import caches


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThrottleResult:
    limited: bool
    retry_after: int
    count: int
    limit: int


def get_client_ip(request) -> str:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return str(request.META.get("REMOTE_ADDR") or "unknown")


def parse_rate(rate: str) -> tuple[int, int]:
    raw_value = str(rate or "").strip().lower()
    if not raw_value or "/" not in raw_value:
        raise ValueError(f"Invalid throttle rate: {rate!r}")

    limit_text, window_text = raw_value.split("/", 1)
    limit = int(limit_text)
    if limit <= 0:
        raise ValueError(f"Invalid throttle limit: {rate!r}")

    multiplier = 1
    if window_text.endswith("s"):
        window_value = window_text[:-1]
    elif window_text.endswith("m"):
        window_value = window_text[:-1]
        multiplier = 60
    elif window_text.endswith("h"):
        window_value = window_text[:-1]
        multiplier = 60 * 60
    elif window_text.endswith("d"):
        window_value = window_text[:-1]
        multiplier = 60 * 60 * 24
    else:
        window_value = window_text

    window = int(window_value) * multiplier
    if window <= 0:
        raise ValueError(f"Invalid throttle window: {rate!r}")
    return limit, window


def _normalized_identity_parts(request, identity_parts: tuple[object, ...]) -> list[str]:
    normalized = [get_client_ip(request)]
    for part in identity_parts:
        value = str(part or "").strip().lower()
        if value:
            normalized.append(value)
    return normalized


def apply_retry_after(response, retry_after: int):
    if retry_after > 0:
        response["Retry-After"] = str(retry_after)
    return response


def check_request_throttle(request, scope: str, rate: str, *identity_parts: object) -> ThrottleResult:
    if not getattr(settings, "THROTTLE_ENABLED", True):
        return ThrottleResult(limited=False, retry_after=0, count=0, limit=0)

    limit, window = parse_rate(rate)
    bucket = int(time.time()) // window
    retry_after = max(1, window - (int(time.time()) % window))
    identity = "|".join(_normalized_identity_parts(request, identity_parts))
    digest = hashlib.sha256(f"{scope}|{identity}".encode("utf-8")).hexdigest()
    cache_key = f"throttle:{scope}:{bucket}:{digest}"
    cache = caches[getattr(settings, "THROTTLE_CACHE_ALIAS", "default")]

    added = cache.add(cache_key, 1, timeout=window + 5)
    if added:
        count = 1
    else:
        try:
            count = cache.incr(cache_key)
        except ValueError:
            cache.set(cache_key, 1, timeout=window + 5)
            count = 1

    limited = count > limit
    if limited:
        logger.warning(
            "Rate limit exceeded",
            extra={
                "scope": scope,
                "rate": rate,
                "client_ip": get_client_ip(request),
                "path": request.path,
                "count": count,
                "limit": limit,
            },
        )
    return ThrottleResult(limited=limited, retry_after=retry_after, count=count, limit=limit)