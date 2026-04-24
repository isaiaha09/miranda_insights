from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
def manifest(request):
    data = {
        "name": "Insights Website",
        "short_name": "Insights",
        "description": "Miranda Insights delivers analytics and collaboration tools to help teams make data-driven decisions.",
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
                "purpose": "any maskable",
            },
            {
                "src": static("pwa/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
        "shortcuts": [
            {
                "name": "Services",
                "short_name": "Services",
                "url": reverse("services"),
            },
            {
                "name": "Contact Support",
                "short_name": "Contact",
                "url": reverse("contact_support"),
            },
            {
                "name": "Client Portal",
                "short_name": "Portal",
                "url": reverse("login"),
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
            "cache_name": "insights-pwa-v3",
        },
        content_type="application/javascript; charset=utf-8",
    )
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def offline(request):
    return render(request, "offline.html", status=200)