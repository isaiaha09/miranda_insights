import time

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.operations.services import process_pending_jobs


class Command(BaseCommand):
    help = "Process queued outbound email, push, and newsletter jobs"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=25)
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--sleep", type=float, default=getattr(settings, "OUTBOUND_WORKER_SLEEP_SECONDS", 5))

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        loop = options["loop"]
        sleep_seconds = options["sleep"]

        while True:
            summary = process_pending_jobs(batch_size=batch_size)
            self.stdout.write(
                self.style.SUCCESS(
                    "Outbound jobs processed "
                    f"claimed={summary['claimed']} succeeded={summary['succeeded']} retried={summary['retried']} failed={summary['failed']}"
                )
            )
            if not loop:
                break
            time.sleep(sleep_seconds)