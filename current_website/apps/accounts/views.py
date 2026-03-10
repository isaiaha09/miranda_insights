import base64
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import RedirectURLMixin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.news.models import NewsletterSubscriber
from landingpage.emailing import send_templated_email
from landingpage.turnstile import is_turnstile_enabled, verify_turnstile

from .forms import LoginForm, NewsletterPreferenceForm, SignupForm, TwoFactorChallengeForm, TwoFactorSetupForm, UsernameRecoveryForm
from .two_factor import build_totp_uri, generate_totp_secret, verify_totp


User = get_user_model()


def _build_qr_data_uri(payload: str) -> str:
	if not payload:
		return ""

	import qrcode

	buffer = BytesIO()
	image = qrcode.make(payload)
	image.save(buffer, format="PNG")
	encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
	return f"data:image/png;base64,{encoded}"


def _client_ip(request):
	x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
	if x_forwarded_for:
		return x_forwarded_for.split(",")[0].strip()
	return request.META.get("REMOTE_ADDR")


def _verify_turnstile_request(request):
	token = (request.POST.get("cf-turnstile-response") or "").strip()
	return verify_turnstile(token, _client_ip(request))


class LoginView(RedirectURLMixin, FormView):
	template_name = "registration/login.html"
	form_class = LoginForm
	redirect_authenticated_user = True

	def dispatch(self, request, *args, **kwargs):
		if self.redirect_authenticated_user and request.user.is_authenticated:
			return redirect(self.get_success_url())
		return super().dispatch(request, *args, **kwargs)

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs["request"] = self.request
		return kwargs

	def get_success_url(self):
		return self.get_redirect_url() or settings.LOGIN_REDIRECT_URL

	def form_valid(self, form):
		user = form.get_user()
		profile = getattr(user, "account_profile", None)
		if profile and profile.two_factor_enabled and profile.two_factor_secret:
			self.request.session["pending_2fa_user_id"] = user.pk
			self.request.session["pending_2fa_backend"] = getattr(user, "backend", "django.contrib.auth.backends.ModelBackend")
			return redirect("login_2fa")

		login(self.request, user)
		return redirect(self.get_success_url())


class TwoFactorChallengeView(FormView):
	template_name = "registration/login_2fa.html"
	form_class = TwoFactorChallengeForm

	def dispatch(self, request, *args, **kwargs):
		if request.user.is_authenticated:
			return redirect("dashboard")
		if not request.session.get("pending_2fa_user_id"):
			return redirect("login")
		return super().dispatch(request, *args, **kwargs)

	def form_valid(self, form):
		user_id = self.request.session.get("pending_2fa_user_id")
		backend = self.request.session.get("pending_2fa_backend")
		user = User.objects.filter(pk=user_id).select_related("account_profile").first()
		if not user or not getattr(user, "account_profile", None) or not user.account_profile.two_factor_secret:
			messages.error(self.request, "Your 2FA session expired. Please sign in again.")
			self.request.session.pop("pending_2fa_user_id", None)
			self.request.session.pop("pending_2fa_backend", None)
			return redirect("login")

		if not verify_totp(user.account_profile.two_factor_secret, form.cleaned_data["otp_code"]):
			form.add_error("otp_code", "Enter a valid authentication code.")
			return self.form_invalid(form)

		user.backend = backend or "django.contrib.auth.backends.ModelBackend"
		login(self.request, user)
		self.request.session.pop("pending_2fa_user_id", None)
		self.request.session.pop("pending_2fa_backend", None)
		messages.success(self.request, "Two-factor authentication complete.")
		return redirect(settings.LOGIN_REDIRECT_URL)


class DashboardView(LoginRequiredMixin, TemplateView):
	template_name = "accounts/dashboard.html"
	login_url = "login"

	def _get_account_profile(self):
		return getattr(self.request.user, "account_profile", None)

	def _get_newsletter_initial(self):
		return {"subscribe_to_newsletter": NewsletterSubscriber.objects.filter(email__iexact=self.request.user.email, is_active=True).exists()}

	def post(self, request, *args, **kwargs):
		action = (request.POST.get("settings_action") or "newsletter").strip()

		if action == "newsletter":
			form = NewsletterPreferenceForm(request.POST)
			if form.is_valid():
				email = (request.user.email or "").strip().lower()
				wants_newsletter = form.cleaned_data["subscribe_to_newsletter"]

				if email:
					if wants_newsletter:
						NewsletterSubscriber.objects.update_or_create(
							email=email,
							defaults={"is_active": True, "unsubscribed_at": None},
						)
						messages.success(request, "Your newsletter preference has been updated.")
					else:
						NewsletterSubscriber.objects.filter(email=email).delete()
						messages.success(request, "You have been unsubscribed from newsletter updates.")
				else:
					messages.error(request, "Add an email address to your account before managing newsletter preferences.")

				return redirect("dashboard")

			context = self.get_context_data(newsletter_form=form)
			return self.render_to_response(context)

		profile = self._get_account_profile()
		if profile is None:
			messages.error(request, "Your account profile is incomplete. Please contact support for assistance.")
			return redirect("dashboard")

		if action == "start_2fa_setup":
			pending_secret = generate_totp_secret()
			request.session["pending_2fa_secret"] = pending_secret
			messages.info(request, "Add the setup key to your authenticator app, then enter the current 6-digit code to confirm.")
			return redirect("dashboard")

		if action == "confirm_2fa_setup":
			form = TwoFactorSetupForm(request.POST)
			pending_secret = request.session.get("pending_2fa_secret", "")
			if not pending_secret:
				messages.error(request, "Start 2FA setup again before confirming.")
				return redirect("dashboard")
			if form.is_valid() and verify_totp(pending_secret, form.cleaned_data["otp_code"]):
				profile.two_factor_secret = pending_secret
				profile.two_factor_enabled = True
				profile.save(update_fields=["two_factor_secret", "two_factor_enabled"])
				request.session.pop("pending_2fa_secret", None)
				messages.success(request, "Two-factor authentication has been enabled.")
				return redirect("dashboard")

			if form.is_valid():
				form.add_error("otp_code", "Enter a valid authentication code.")
			context = self.get_context_data(two_factor_setup_form=form)
			return self.render_to_response(context)

		if action == "disable_2fa":
			profile.two_factor_enabled = False
			profile.two_factor_secret = ""
			profile.save(update_fields=["two_factor_enabled", "two_factor_secret"])
			request.session.pop("pending_2fa_secret", None)
			messages.success(request, "Two-factor authentication has been disabled.")
			return redirect("dashboard")

		messages.error(request, "Unsupported settings action.")
		return redirect("dashboard")

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		pending_secret = self.request.session.get("pending_2fa_secret", "")
		profile = self._get_account_profile()
		context["newsletter_form"] = kwargs.get("newsletter_form") or NewsletterPreferenceForm(initial=self._get_newsletter_initial())
		context["two_factor_setup_form"] = kwargs.get("two_factor_setup_form") or TwoFactorSetupForm()
		context.update(
			{
				"turnstile_enabled": is_turnstile_enabled(),
				"turnstile_site_key": settings.TURNSTILE_SITE_KEY,
				"two_factor_enabled": bool(profile and profile.two_factor_enabled),
				"two_factor_pending": bool(pending_secret),
				"two_factor_setup_key": pending_secret,
				"two_factor_otpauth_uri": build_totp_uri(pending_secret, self.request.user.username) if pending_secret else "",
				"two_factor_qr_data_uri": _build_qr_data_uri(build_totp_uri(pending_secret, self.request.user.username)) if pending_secret else "",
				"active_projects": [
					{
						"name": "District Performance Dashboard",
						"client": "North Valley School District",
						"progress": 72,
						"status": "In progress",
						"next_step": "Dashboard review with stakeholder team",
					},
					{
						"name": "Grant Outcomes Evaluation",
						"client": "State Education Agency",
						"progress": 54,
						"status": "Data analysis",
						"next_step": "Drafting interim findings summary",
					},
				],
				"completed_projects": [
					{
						"name": "Community Needs Assessment",
						"client": "Regional Nonprofit Coalition",
						"completed_on": "February 2026",
					},
					{
						"name": "Program Evaluation Summary",
						"client": "Metro Youth Services",
						"completed_on": "December 2025",
					},
				],
				"progress_updates": [
					"New attendance trend files were received and validated for the district dashboard project.",
					"Interim visual mockups are ready for the next stakeholder review meeting.",
					"Final narrative edits are underway for the grant outcomes evaluation report.",
				],
				"reports": [
					{"title": "Project Status Summary", "description": "Weekly project snapshot and milestone overview.", "href": "#"},
					{"title": "Latest Deliverables", "description": "Download the most recent report package and presentation files.", "href": "#"},
					{"title": "Data Export", "description": "Access the latest approved export for your internal review.", "href": "#"},
				],
			}
		)
		return context


class SignupView(FormView):
	template_name = "accounts/signup.html"
	form_class = SignupForm

	def dispatch(self, request, *args, **kwargs):
		if request.user.is_authenticated:
			return redirect("home")
		return super().dispatch(request, *args, **kwargs)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["turnstile_enabled"] = is_turnstile_enabled()
		context["turnstile_site_key"] = settings.TURNSTILE_SITE_KEY
		return context

	def form_valid(self, form):
		turnstile_ok, _ = _verify_turnstile_request(self.request)
		if not turnstile_ok:
			form.add_error(None, "Security verification failed. Please try again.")
			return self.form_invalid(form)

		user = form.save()
		if form.cleaned_data.get("subscribe_to_newsletter"):
			NewsletterSubscriber.objects.update_or_create(
				email=user.email,
				defaults={"is_active": True, "unsubscribed_at": None},
			)
		login(self.request, user)
		messages.success(self.request, "Your account has been created successfully.")
		return redirect("dashboard")


class UsernameRecoveryView(FormView):
	template_name = "accounts/recover_username.html"
	form_class = UsernameRecoveryForm

	def form_valid(self, form):
		email = form.cleaned_data["email"].strip().lower()
		users = User.objects.filter(email__iexact=email).order_by("username")

		if users.exists():
			send_templated_email(
				subject="Your Insights username",
				to=[email],
				template_prefix="username_recovery",
				context={
					"email_title": "Username Recovery",
					"heading": "Username Recovery",
					"subheading": "Here are the usernames connected to your email address.",
					"usernames": [user.username for user in users],
				},
				from_email=settings.DEFAULT_FROM_EMAIL,
			)

		return render(self.request, "accounts/recover_username_done.html", {"email": email})


class TermsView(TemplateView):
	template_name = "accounts/terms.html"
