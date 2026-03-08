import logging

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage, get_connection
from django.shortcuts import redirect, render

from .forms import NewsletterSubscribeForm, SupportContactForm
from .models import NewsletterSubscriber


logger = logging.getLogger(__name__)


def home(request):
	form = NewsletterSubscribeForm()
	return render(request, "index.html", {"subscribe_form": form})


def subscribe(request):
	if request.method != "POST":
		return redirect("home")

	form = NewsletterSubscribeForm(request.POST)
	if not form.is_valid():
		messages.error(request, "Please enter a valid email address.")
		return redirect("home")

	email = form.cleaned_data["email"].strip().lower()
	subscriber, created = NewsletterSubscriber.objects.get_or_create(
		email=email,
		defaults={"is_active": True},
	)

	if created:
		messages.success(request, "Thanks for subscribing to our newsletter.")
		return redirect("home")

	if not subscriber.is_active:
		subscriber.is_active = True
		subscriber.unsubscribed_at = None
		subscriber.save(update_fields=["is_active", "unsubscribed_at"])
		messages.success(request, "Welcome back. Your subscription has been reactivated.")
		return redirect("home")

	messages.info(request, "This email is already subscribed.")
	return redirect("home")


def contact_support(request):
	if request.method == "POST":
		form = SupportContactForm(request.POST)
		if form.is_valid():
			name = form.cleaned_data["name"].strip()
			email = form.cleaned_data["email"].strip().lower()
			subject = form.cleaned_data["subject"].strip()
			message = form.cleaned_data["message"].strip()

			email_subject = f"[Support] {subject}"
			email_body = (
				"New support request submitted from website contact form.\n\n"
				f"Name: {name}\n"
				f"Email: {email}\n"
				f"Subject: {subject}\n\n"
				"Message:\n"
				f"{message}\n"
			)

			confirmation_subject = "We received your support request"
			confirmation_body = (
				f"Hi {name},\n\n"
				"Thanks for contacting Miranda Insights support. "
				"We received your message and will respond as soon as possible.\n\n"
				"Summary of your request:\n"
				f"Subject: {subject}\n"
				f"Message: {message}\n\n"
				"If you need to add details, reply to this email."
			)

			try:
				connection = get_connection(fail_silently=False)

				support_email = EmailMessage(
					subject=email_subject,
					body=email_body,
					from_email=settings.DEFAULT_FROM_EMAIL,
					to=[settings.CONTACT_RECIPIENT],
					reply_to=[email],
					connection=connection,
				)
				confirmation_email = EmailMessage(
					subject=confirmation_subject,
					body=confirmation_body,
					from_email=settings.DEFAULT_FROM_EMAIL,
					to=[email],
					reply_to=["support@mirandainsights.com"],
					connection=connection,
				)

				support_sent = support_email.send(fail_silently=False)
				confirmation_sent = confirmation_email.send(fail_silently=False)
				if support_sent != 1 or confirmation_sent != 1:
					raise RuntimeError(
						f"Unexpected send result (support={support_sent}, confirmation={confirmation_sent})"
					)
			except Exception as exc:
				logger.exception("Failed to send contact support email")
				error_message = "Your message could not be sent right now. Please try again shortly."
				if settings.DEBUG:
					error_message = f"{error_message} (Reason: {exc})"
				messages.error(request, error_message)
				return render(request, "contact.html", {"form": form})

			messages.success(request, "Thanks, your support request has been received.")
			return redirect("contact_support")
	else:
		form = SupportContactForm()

	return render(request, "contact.html", {"form": form})
