from __future__ import annotations

import logging

from django.core.cache import caches
from django.db import connections
from django.http import JsonResponse
from django.views.decorators.http import require_GET


logger = logging.getLogger(__name__)


@require_GET
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
        logger.exception("Health check database probe failed")

    try:
        cache = caches["default"]
        cache.set("healthcheck:ping", "ok", timeout=30)
        checks["cache"] = cache.get("healthcheck:ping") == "ok"
    except Exception:
        logger.exception("Health check cache probe failed")

    status_code = 200 if all(checks.values()) else 503
    return JsonResponse(
        {
            "status": "ok" if status_code == 200 else "degraded",
            "checks": checks,
        },
        status=status_code,
    )