from django.http import JsonResponse
from django.conf import settings
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
def manifest(request):
    data = {
        "name": "Miranda Insights",
        "short_name": "Miranda Insights",
        "description": "Miranda Insights helps people and organizations understand problems, organize systems, build digital solutions, and move forward through project-based and ongoing support.",
        "start_url": reverse("home"),
        "scope": "/",
        "display": "standalone",
        "background_color": "#070b12",
        "theme_color": "#0c111b",
        "lang": "en-US",
        "prefer_related_applications": False,
        "icons": [
            {
                "src": static("pwa/icon-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": static("pwa/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": static("pwa/icon-maskable-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "maskable",
            },
            {
                "src": static("pwa/icon-maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
        "shortcuts": [
            {
                "name": "Services",
                "short_name": "Services",
                "url": reverse("services"),
            },
            {
                "name": "Individual Support",
                "short_name": "Support",
                "url": reverse("individual_services"),
            },
            {
                "name": "Resources",
                "short_name": "Resources",
                "url": reverse("contact_support"),
            },
            {
                "name": "Client Portal",
                "short_name": "Portal",
                "url": reverse("dashboard"),
            },
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json")


@require_GET
@never_cache
def service_worker(request):
    response = render(
        request,
        "service-worker.js",
        {
            "cache_name": "insights-pwa-v5",
            "debug_mode": settings.DEBUG,
        },
        content_type="application/javascript; charset=utf-8",
    )
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def offline(request):
    return render(request, "offline.html", status=200)
