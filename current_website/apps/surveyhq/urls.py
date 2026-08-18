from django.contrib import admin
from django.urls import path

from . import views


urlpatterns = [
    path("", admin.site.admin_view(views.surveyhq_dashboard), name="dashboard"),
]
