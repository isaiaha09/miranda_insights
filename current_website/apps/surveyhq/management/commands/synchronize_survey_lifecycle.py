from django.core.management.base import BaseCommand

from apps.surveyhq.lifecycle import synchronize_due_surveys


class Command(BaseCommand):
    help = "Open and close SurveyHQ surveys whose scheduled transition time has arrived."

    def handle(self, *args, **options):
        result = synchronize_due_surveys()
        self.stdout.write(
            self.style.SUCCESS(
                f"SurveyHQ lifecycle synchronized: {result['opened']} opened, {result['closed']} closed."
            )
        )
