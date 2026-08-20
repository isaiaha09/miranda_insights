from django.conf import settings
from django.core.files import File
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.management.base import BaseCommand, CommandError

from apps.clients.models import ProjectMessage
from apps.news.models import NewsletterImageAsset

from ...models import SurveyQuestion, SurveyReportArtifact


MEDIA_FIELDS = (
    (SurveyQuestion, "image"),
    (SurveyReportArtifact, "file"),
    (ProjectMessage, "attachment_file"),
    (NewsletterImageAsset, "image"),
)


class Command(BaseCommand):
    help = "Copy existing MEDIA_ROOT files to the configured Supabase storage backend."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report files that would be copied without uploading anything.",
        )

    def handle(self, *args, **options):
        if not settings.SUPABASE_STORAGE_ENABLED:
            raise CommandError("Enable SUPABASE_STORAGE_ENABLED before migrating media.")
        if settings.STORAGES["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage":
            raise CommandError("The default storage backend is still local; Supabase storage is not active.")

        source_storage = FileSystemStorage(location=settings.MEDIA_ROOT)
        dry_run = options["dry_run"]
        copied = 0
        skipped = 0
        missing = 0

        for model, field_name in MEDIA_FIELDS:
            for instance in model._default_manager.iterator():
                field_file = getattr(instance, field_name)
                name = getattr(field_file, "name", "")
                if not name:
                    continue

                if default_storage.exists(name):
                    skipped += 1
                    continue
                if not source_storage.exists(name):
                    missing += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Missing local file for {model._meta.label}.{field_name}: {name}"
                        )
                    )
                    continue
                if dry_run:
                    copied += 1
                    continue

                with source_storage.open(name, "rb") as source:
                    saved_name = default_storage.save(name, File(source, name=name))
                if saved_name != name:
                    default_storage.delete(saved_name)
                    raise CommandError(
                        f"Storage changed the path for {model._meta.label}.{field_name}: "
                        f"expected {name}, received {saved_name}."
                    )
                copied += 1

        action = "would copy" if dry_run else "copied"
        self.stdout.write(
            self.style.SUCCESS(
                f"Media migration complete: {action} {copied}, skipped {skipped}, missing {missing}."
            )
        )
