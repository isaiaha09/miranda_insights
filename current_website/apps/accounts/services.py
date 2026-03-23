from django.conf import settings
from django.db import transaction
from django.db.models import Q

from apps.clients.models import Client
from apps.news.models import NewsletterSubscriber
from landingpage.emailing import send_templated_email


def normalize_account_email(value):
	return (value or "").strip().lower()


def has_active_newsletter_subscription(email):
	normalized_email = normalize_account_email(email)
	if not normalized_email:
		return False
	return NewsletterSubscriber.objects.filter(email__iexact=normalized_email, is_active=True).exists()


def send_account_deleted_email(email):
	normalized_email = normalize_account_email(email)
	if not normalized_email:
		return 0
	return send_templated_email(
		subject="Your Miranda Insights account has been successfully deleted",
		to=[normalized_email],
		template_prefix="account_deleted",
		context={
			"email_title": "Account Deleted",
			"heading": "Your account has been deleted",
			"subheading": "Your Miranda Insights account has been successfully deleted.",
		},
		from_email=settings.DEFAULT_FROM_EMAIL,
	)


def delete_account_for_user(user, *, send_confirmation_email=True):
	if user is None:
		return False

	normalized_email = normalize_account_email(getattr(user, "email", ""))
	preserve_newsletter = has_active_newsletter_subscription(normalized_email)

	with transaction.atomic():
		# Only delete the client record explicitly linked to this user. Matching on email
		# would allow one account deletion to remove unrelated client rows that happen
		# to share the same contact address.
		Client.objects.filter(user=user).delete()
		if normalized_email and not preserve_newsletter:
			NewsletterSubscriber.objects.filter(email__iexact=normalized_email).delete()
		user.delete()
		if send_confirmation_email and normalized_email:
			send_account_deleted_email(normalized_email)

	return True