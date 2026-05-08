from __future__ import annotations

import logging

from django.core.cache import caches
from django.db import connections
from django.http import JsonResponse
from django.views.decorators.http import require_safe


logger = logging.getLogger(__name__)


class SkipHealthCheckRequestFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request = getattr(record, "request", None)
        request_path = getattr(request, "path_info", "") or getattr(request, "path", "")
        return request_path != "/health/"


def _log_probe_failure(check_name: str, message: str) -> None:
    try:
        cache = caches["default"]
        cache_key = f"healthcheck:probe-warning:{check_name}"
        if cache.add(cache_key, "1", timeout=900):
            logger.warning(message, exc_info=True)
    except Exception:
        logger.warning(message, exc_info=True)


@require_safe
def health_check(request):
    checks = {
        "database": False,
        "cache": False,
    }

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = True
    except Exception:
        _log_probe_failure("database", "Health check database probe failed")

    try:
        cache = caches["default"]
        cache.set("healthcheck:ping", "ok", timeout=30)
        checks["cache"] = cache.get("healthcheck:ping") == "ok"
    except Exception:
        _log_probe_failure("cache", "Health check cache probe failed")

    status_code = 200 if all(checks.values()) else 503
    return JsonResponse(
        {
            "status": "ok" if status_code == 200 else "degraded",
            "checks": checks,
        },
        status=status_code,
    )