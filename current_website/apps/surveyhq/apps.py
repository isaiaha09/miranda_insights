from django.apps import AppConfig


class SurveyHqConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.surveyhq"
    verbose_name = "SurveyHQ"

    def ready(self):
        from . import checks  # noqa: F401
