from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import NewsletterSubscribeForm
from .models import NewsletterSubscriber


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
