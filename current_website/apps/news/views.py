import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.core.mail import get_connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from landingpage.emailing import send_templated_email
from landingpage.turnstile import is_turnstile_enabled_for_request, verify_turnstile_for_request

from .forms import NewsletterSubscribeForm, SupportContactForm
from .models import NewsletterSubscriber
from .services import get_unsubscribe_email


logger = logging.getLogger(__name__)
NEWSLETTER_SECTION_ID = "newsletter-signup"


def _newsletter_anchor_url(params=None):
	base_path = reverse("home")
	if params:
		return f"{base_path}?{urlencode(params)}#{NEWSLETTER_SECTION_ID}"
	return f"{base_path}#{NEWSLETTER_SECTION_ID}"


def _is_ajax_request(request):
	return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _client_ip(request):
	x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
	if x_forwarded_for:
		return x_forwarded_for.split(",")[0].strip()
	return request.META.get("REMOTE_ADDR")


def _newsletter_response(request, message_text, *, level, status_code=200):
	message_handlers = {
		"success": messages.success,
		"error": messages.error,
		"info": messages.info,
	}
	message_handlers[level](request, message_text)

	if _is_ajax_request(request):
		return JsonResponse(
			{
				"message": message_text,
				"level": level,
				"sectionId": NEWSLETTER_SECTION_ID,
			},
			status=status_code,
		)

	return redirect(_newsletter_anchor_url())


def home(request):
	form = NewsletterSubscribeForm()
	return render(
		request,
		"index.html",
		{
			"subscribe_form": form,
			"newsletter_section_id": NEWSLETTER_SECTION_ID,
		},
	)


def services(request):
	return render(request, "services.html")


def about(request):
	return render(request, "about.html")


def products(request):
	return render(request, "products.html")


def faq(request):
	return render(request, "faq.html")


def subscribe(request):
	if request.method != "POST":
		return redirect(_newsletter_anchor_url())

	form = NewsletterSubscribeForm(request.POST)
	if not form.is_valid():
		return _newsletter_response(request, "Please enter a valid email address.", level="error", status_code=400)

	email = form.cleaned_data["email"].strip().lower()
	subscriber, created = NewsletterSubscriber.objects.get_or_create(
		email=email,
		defaults={"is_active": True},
	)

	if created:
		return _newsletter_response(request, "Thanks for subscribing to our newsletter.", level="success")

	if not subscriber.is_active:
		subscriber.is_active = True
		subscriber.unsubscribed_at = None
		subscriber.save(update_fields=["is_active", "unsubscribed_at"])
		return _newsletter_response(request, "Welcome back. Your subscription has been reactivated.", level="success")

	return _newsletter_response(request, "This email is already subscribed.", level="info")


@csrf_exempt
def unsubscribe(request):
	if request.method not in {"GET", "POST"}:
		return redirect(_newsletter_anchor_url())

	token = (request.POST.get("token") or request.GET.get("token") or "").strip()
	if not token:
		messages.error(request, "This unsubscribe link is invalid.")
		return redirect(_newsletter_anchor_url())

	try:
		email = get_unsubscribe_email(token).strip().lower()
	except (KeyError, signing.BadSignature, signing.SignatureExpired):
		messages.error(request, "This unsubscribe link is invalid.")
		return redirect(_newsletter_anchor_url())

	subscriber = NewsletterSubscriber.objects.filter(email=email).first()
	if subscriber:
		subscriber.delete()

	messages.success(request, "You have been unsubscribed from newsletter emails.")
	return redirect(_newsletter_anchor_url({"newsletter_status": "unsubscribed"}))


def contact_support(request):
	if request.method == "POST":
		form = SupportContactForm(request.POST)
		if form.is_valid():
			turnstile_ok, _ = verify_turnstile_for_request(request, (request.POST.get("cf-turnstile-response") or "").strip(), _client_ip(request))
			if not turnstile_ok:
				form.add_error(None, "Security verification failed. Please try again.")
				return render(request, "contact.html", {"form": form, "turnstile_enabled": is_turnstile_enabled_for_request(request), "turnstile_site_key": settings.TURNSTILE_SITE_KEY})

			name = form.cleaned_data["name"].strip()
			organization = form.cleaned_data["organization"].strip()
			email = form.cleaned_data["email"].strip().lower()
			phone = form.cleaned_data.get("phone", "").strip()
			business_location = form.cleaned_data.get("business_location", "").strip()
			subject = form.cleaned_data["subject"].strip()
			message = form.cleaned_data["message"].strip()

			phone_line = f"Phone: {phone}\n" if phone else ""
			location_line = f"Business location: {business_location}\n" if business_location else ""

			email_subject = f"[Support] {subject}"
			email_body = (
				"New support request submitted from website contact form.\n\n"
				f"Name: {name}\n"
				f"Organization: {organization}\n"
				f"Email: {email}\n"
				f"{phone_line}"
				f"{location_line}"
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
				f"Organization: {organization}\n"
				f"Subject: {subject}\n"
				f"{phone_line}"
				f"{location_line}"
				f"Message: {message}\n\n"
				"If you need to add details, reply to this email."
			)

			try:
				connection = get_connection(fail_silently=False)

				support_sent = send_templated_email(
					subject=email_subject,
					to=[settings.CONTACT_RECIPIENT],
					template_prefix="contact_support_internal",
					context={
						"email_title": email_subject,
						"heading": "New Support Request",
						"subheading": "A new contact form submission is ready for review.",
						"name": name,
						"organization": organization,
						"email": email,
						"phone": phone,
						"business_location": business_location,
						"subject": subject,
						"message": message,
					},
					from_email=settings.DEFAULT_FROM_EMAIL,
					reply_to=[email],
					connection=connection,
				)
				confirmation_sent = send_templated_email(
					subject=confirmation_subject,
					to=[email],
					template_prefix="contact_support_confirmation",
					context={
						"email_title": confirmation_subject,
						"heading": "Support Request Received",
						"subheading": "We have your message and will follow up as soon as possible.",
						"name": name,
						"organization": organization,
						"phone": phone,
						"business_location": business_location,
						"subject": subject,
						"message": message,
					},
					from_email=settings.DEFAULT_FROM_EMAIL,
					reply_to=["support@mirandainsights.com"],
					connection=connection,
				)
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
				return render(request, "contact.html", {"form": form, "turnstile_enabled": is_turnstile_enabled_for_request(request), "turnstile_site_key": settings.TURNSTILE_SITE_KEY})

			messages.success(request, "Thanks, your support request has been received. A confirmation message has been sent to your email.")
			return redirect("contact_support")
	else:
		form = SupportContactForm()

	return render(request, "contact.html", {"form": form, "turnstile_enabled": is_turnstile_enabled_for_request(request), "turnstile_site_key": settings.TURNSTILE_SITE_KEY})
