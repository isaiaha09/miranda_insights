from django.core.management.base import BaseCommand

from apps.news.services import process_due_automated_campaigns


class Command(BaseCommand):
    help = "Send all due automated newsletter campaigns"

    def handle(self, *args, **options):
        processed = process_due_automated_campaigns()
        self.stdout.write(self.style.SUCCESS(f"Processed automated campaigns: {processed}"))
