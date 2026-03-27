"""
URL configuration for landingpage project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from landingpage import pwa

admin.site.login_template = "admin/login_portal.html"
admin.site.site_header = "Miranda Insights Admin"
admin.site.site_title = "Miranda Insights Admin"
admin.site.index_title = "Management Workspace"

urlpatterns = [
    path(f"{settings.DJANGO_ADMIN_URL}/", admin.site.urls),
    path("manifest.webmanifest", pwa.manifest, name="webmanifest"),
    path("service-worker.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
    path('', include('apps.accounts.urls')),
    path('', include('apps.clients.urls')),
    path('', include('apps.news.urls')),
]

# Serve static files during development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=str(settings.BASE_DIR / 'static'))
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
