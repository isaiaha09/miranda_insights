from django.contrib import admin
from django.template.response import TemplateResponse


def surveyhq_dashboard(request):
    context = {
        **admin.site.each_context(request),
        "title": "SurveyHQ",
        "subtitle": "Survey management foundation",
    }
    request.current_app = admin.site.name
    return TemplateResponse(request, "admin/surveyhq/dashboard.html", context)
