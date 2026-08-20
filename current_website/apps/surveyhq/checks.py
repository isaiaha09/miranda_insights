from django.conf import settings
from django.core.checks import Warning, register


@register()
def surveyhq_durable_storage_check(app_configs, **kwargs):
    if settings.DEBUG or settings.SURVEYHQ_DURABLE_STORAGE_READY:
        return []
    return [
        Warning(
            "SurveyHQ durable media writes are disabled until persistent storage is confirmed.",
            hint=(
                "Configure Supabase S3 storage or a Render persistent disk, verify restart/deployment "
                "persistence, then set SURVEYHQ_DURABLE_STORAGE_READY=true."
            ),
            id="surveyhq.W001",
        )
    ]
