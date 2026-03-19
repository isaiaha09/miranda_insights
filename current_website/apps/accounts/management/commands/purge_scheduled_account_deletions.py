from django.core.management.base import BaseCommand

from apps.accounts.models import purge_expired_account_deletions


class Command(BaseCommand):
	help = "Permanently delete accounts whose scheduled deletion window has expired."

	def handle(self, *args, **options):
		deleted_count = purge_expired_account_deletions()
		self.stdout.write(self.style.SUCCESS(f"Purged {deleted_count} expired account deletion request(s)."))