from django.apps import AppConfig


class ClientsConfig(AppConfig):
    name = 'apps.clients'

    def ready(self):
        from . import signals  # noqa: F401
