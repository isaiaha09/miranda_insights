from django.contrib import admin

from .models import OutboundJob


@admin.register(OutboundJob)
class OutboundJobAdmin(admin.ModelAdmin):
    list_display = ("job_type", "status", "attempts", "run_after", "created_at", "completed_at")
    list_filter = ("job_type", "status", "created_at")
    search_fields = ("job_type", "last_error")
    readonly_fields = (
        "job_type",
        "payload",
        "status",
        "attempts",
        "max_attempts",
        "run_after",
        "locked_at",
        "completed_at",
        "last_error",
        "created_at",
        "updated_at",
    )