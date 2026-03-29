import base64
import json
from io import BytesIO
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import RedirectURLMixin
from django.core import signing
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import FormView, TemplateView
from django.views.decorators.csrf import csrf_exempt

from apps.news.models import NewsletterSubscriber
from apps.clients.chat import render_project_chat_widget
from apps.clients.forms import ClientPortalProfileForm, ProjectMessageForm
from apps.clients.models import Project, ProjectMessage, ProjectNote, ProjectSubtask, get_or_create_client_for_user
from landingpage.emailing import send_templated_email
from landingpage.turnstile import is_turnstile_enabled_for_request, verify_turnstile_for_request

from .forms import DeleteAccountForm, LoginForm, NewsletterPreferenceForm, SignupForm, StyledPasswordResetForm, TwoFactorChallengeForm, TwoFactorSetupForm, UsernameRecoveryForm
from .models import AccountDeletionRequest, purge_expired_account_deletions
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
	return verify_turnstile_for_request(request, token, _client_ip(request))


def _recover_scheduled_deletion(request, user):
	deletion_request = getattr(user, "account_deletion_request", None)
	if deletion_request and deletion_request.is_recoverable:
		deletion_request.delete()
		messages.success(request, "Your scheduled account deletion has been canceled. All account data has been restored.")


def _is_pwa_login_request(request):
	value = request.POST.get("pwa_mode") or request.GET.get("pwa_mode") or request.session.get("pending_login_pwa_mode")
	return str(value).strip().lower() in {"1", "true", "yes", "on", "standalone"}


def _build_login_success_url(request, user, *, redirect_url=""):
	if redirect_url:
		return redirect_url
	if user.is_staff:
		return reverse("admin:index")
	return settings.LOGIN_REDIRECT_URL


def _serialize_last_login(user):
	if not user.last_login:
		return ""
	return timezone.localtime(user.last_login).isoformat()


def _build_mobile_session_token(user, redirect_url):
	return signing.dumps(
		{
			"user_id": user.pk,
			"password": user.password,
			"last_login": _serialize_last_login(user),
			"redirect_url": redirect_url,
		},
		salt="insights.mobile-session-login",
	)


def _build_mobile_session_url(request, user, redirect_url):
	token = _build_mobile_session_token(user, redirect_url)
	return request.build_absolute_uri(f"{reverse('mobile_session_login')}?{urlencode({'token': token})}")


def _json_error(message, *, field_errors=None, status=400, **extra):
	payload = {"ok": False, "message": message}
	if field_errors:
		payload["fieldErrors"] = field_errors
	payload.update(extra)
	return JsonResponse(payload, status=status)


@method_decorator(csrf_exempt, name="dispatch")
class MobileSignInApiView(View):
	def post(self, request, *args, **kwargs):
		try:
			payload = json.loads(request.body.decode("utf-8") or "{}")
		except json.JSONDecodeError:
			return _json_error("Invalid request payload.")

		username = str(payload.get("username", "")).strip()
		password = str(payload.get("password", ""))
		otp_code = str(payload.get("otpCode", "")).strip()
		redirect_url = str(payload.get("redirectUrl", "")).strip()

		form = LoginForm(request=request, data={"username": username, "password": password})
		if not form.is_valid():
			field_errors = {key: [str(error) for error in errors] for key, errors in form.errors.items()}
			message = form.non_field_errors()[0] if form.non_field_errors() else "Unable to sign in."
			return _json_error(message, field_errors=field_errors)

		user = form.get_user()
		success_url = _build_login_success_url(request, user, redirect_url=redirect_url)
		profile = getattr(user, "account_profile", None)
		if profile and profile.two_factor_enabled and profile.two_factor_secret:
			if not otp_code:
				return JsonResponse(
					{
						"ok": False,
						"requiresTwoFactor": True,
						"message": "Enter your authentication code to continue.",
					},
					status=200,
				)

			if not verify_totp(profile.two_factor_secret, otp_code):
				return _json_error(
					"Enter a valid authentication code.",
					field_errors={"otpCode": ["Enter a valid authentication code."]},
				)

		session_url = _build_mobile_session_url(request, user, success_url)
		return JsonResponse(
			{
				"ok": True,
				"sessionUrl": session_url,
				"redirectUrl": success_url,
				"requiresTwoFactor": False,
				"displayName": user.get_full_name().strip() or user.username,
			}
		)


@method_decorator(csrf_exempt, name="dispatch")
class MobileUsernameRecoveryApiView(View):
	def post(self, request, *args, **kwargs):
		try:
			payload = json.loads(request.body.decode("utf-8") or "{}")
		except json.JSONDecodeError:
			return _json_error("Invalid request payload.")

		form = UsernameRecoveryForm(data={"email": str(payload.get("email", "")).strip()})
		if not form.is_valid():
			field_errors = {key: [str(error) for error in errors] for key, errors in form.errors.items()}
			return _json_error("Enter a valid email address.", field_errors=field_errors)

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

		return JsonResponse(
			{
				"ok": True,
				"message": f"If an account exists for {email}, a username reminder has been sent.",
			}
		)


@method_decorator(csrf_exempt, name="dispatch")
class MobilePasswordResetApiView(View):
	def post(self, request, *args, **kwargs):
		try:
			payload = json.loads(request.body.decode("utf-8") or "{}")
		except json.JSONDecodeError:
			return _json_error("Invalid request payload.")

		form = StyledPasswordResetForm(data={"email": str(payload.get("email", "")).strip()})
		if not form.is_valid():
			field_errors = {key: [str(error) for error in errors] for key, errors in form.errors.items()}
			return _json_error("Enter a valid email address.", field_errors=field_errors)

		form.save(
			request=request,
			use_https=request.is_secure(),
			from_email=settings.DEFAULT_FROM_EMAIL,
			email_template_name="registration/password_reset_email.txt",
			html_email_template_name="registration/password_reset_email.html",
			subject_template_name="registration/password_reset_subject.txt",
			extra_email_context={
				"brand_name": "Insights",
				"company_name": "Miranda Insights",
				"heading": "Reset Your Password",
				"support_email": settings.SUPPORT_EMAIL,
			},
		)

		email = form.cleaned_data["email"].strip().lower()
		return JsonResponse(
			{
				"ok": True,
				"message": f"If an account exists for {email}, a password reset link has been sent.",
			}
		)


class MobileSessionLoginView(View):
	def get(self, request, *args, **kwargs):
		token = (request.GET.get("token") or "").strip()
		if not token:
			messages.error(request, "Your mobile sign-in link is missing.")
			return redirect("login")

		try:
			payload = signing.loads(token, salt="insights.mobile-session-login", max_age=300)
		except signing.BadSignature:
			messages.error(request, "Your mobile sign-in link is invalid or expired.")
			return redirect("login")

		user = User.objects.filter(pk=payload.get("user_id")).first()
		if not user or user.password != payload.get("password"):
			messages.error(request, "Your mobile sign-in link is invalid or expired.")
			return redirect("login")

		if _serialize_last_login(user) != payload.get("last_login", ""):
			messages.error(request, "This mobile sign-in link has already been used. Please sign in again.")
			return redirect("login")

		user.backend = "django.contrib.auth.backends.ModelBackend"
		login(request, user)
		_recover_scheduled_deletion(request, user)
		return redirect(payload.get("redirect_url") or settings.LOGIN_REDIRECT_URL)


class PortalContextMixin:
	def _get_client_record(self):
		return get_or_create_client_for_user(self.request.user)

	def _get_account_profile(self):
		return getattr(self.request.user, "account_profile", None)

	def _get_newsletter_initial(self):
		return {"subscribe_to_newsletter": NewsletterSubscriber.objects.filter(email__iexact=self.request.user.email, is_active=True).exists()}

	def _build_portal_snapshot(self):
		client = self._get_client_record()
		projects = client.projects.select_related("consultant").prefetch_related("subtasks", "notes")
		active_projects = []
		completed_projects = []
		reports = []

		for project in projects:
			next_subtask = project.subtasks.filter(is_completed=False).order_by("due_date", "created_at").first()
			latest_note = project.latest_note
			project_notes = list(project.notes.order_by("-created_at")[:6])
			latest_note_entry = project_notes[0] if project_notes else None
			past_note_entries = project_notes[1:]
			subtask_items = [
				{
					"title": subtask.title,
					"details": subtask.details or "No details shared yet.",
					"is_completed": subtask.is_completed,
					"due_date": subtask.due_date.strftime("%B %d, %Y") if subtask.due_date else "No due date",
				}
				for subtask in project.subtasks.order_by("is_completed", "due_date", "created_at")[:4]
			]
			project_payload = {
				"name": project.name,
				"client": client.organization_name or client.contact_name,
				"consultant": project.consultant_display,
				"progress": project.progress_percentage,
				"status": project.get_status_display(),
				"next_step": next_subtask.title if next_subtask else ("Awaiting next update" if project.status != Project.STATUS_COMPLETED else "Project wrapped"),
				"next_step_details": next_subtask.details if next_subtask and next_subtask.details else "No additional details shared yet.",
				"subtasks": subtask_items,
			}
			if project.status == Project.STATUS_COMPLETED:
				completed_projects.append(
					{
						"name": project.name,
						"client": client.organization_name or client.contact_name,
						"completed_on": project.end_date.strftime("%B %Y") if project.end_date else "Completed",
					}
				)
			elif project.status != Project.STATUS_CANCELLED:
				active_projects.append(project_payload)

			reports.append(
				{
					"title": project.name,
					"description": (latest_note_entry.content[:120] + "...") if latest_note_entry and len(latest_note_entry.content) > 120 else (latest_note_entry.content if latest_note_entry else (project.description or "No deliverable summary yet.")),
					"latest_note": {
						"content": latest_note_entry.content,
						"created_at": latest_note_entry.created_at,
					} if latest_note_entry else None,
					"past_notes": [
						{
							"content": note.content,
							"created_at": note.created_at,
						}
						for note in past_note_entries
					],
					"href": "#",
				}
			)

		progress_updates = []
		for subtask in ProjectSubtask.objects.filter(project__client=client, is_completed=True).select_related("project", "completed_by"):
			progress_updates.append(
				{
					"kind": "subtask",
					"label": "Completed subtask",
					"project_name": subtask.project.name,
					"title": subtask.title,
					"body": subtask.details or "Marked complete.",
					"summary": f"Completed subtask for {subtask.project.name}: {subtask.title}",
					"timestamp": subtask.completed_at or subtask.created_at,
				}
			)

		progress_updates.sort(key=lambda update: update["timestamp"], reverse=True)
		progress_updates = progress_updates[:6]

		message_logs = [
			{
				"project_name": message.project.name,
				"sender": message.sender_label,
				"body": message.body,
				"logged_at": message.created_at,
				"is_staff_message": message.is_staff_message,
			}
			for message in ProjectMessage.objects.filter(project__client=client).select_related("project", "sender").order_by("-created_at")[:8]
		]

		return {
			"active_projects": active_projects,
			"completed_projects": completed_projects,
			"progress_updates": progress_updates,
			"reports": reports[:5],
			"message_logs": message_logs,
			"client_record": client,
		}

	def _get_delete_account_rundown(self):
		profile = self._get_account_profile()
		snapshot = self._build_portal_snapshot()
		items = [
			{
				"title": "Portal access and sign-in history",
				"description": "Your account login, dashboard access, and saved portal activity will be permanently removed after the 7-day recovery window.",
			},
			{
				"title": "Project records and progress history",
				"description": f"The {len(snapshot['active_projects'])} active projects, {len(snapshot['completed_projects'])} completed project records, and their stored progress details will be erased.",
			},
			{
				"title": "Portal updates and message logs",
				"description": f"The {len(snapshot['progress_updates'])} progress updates and {len(snapshot['message_logs'])} message log entries currently shown in your portal will be erased.",
			},
			{
				"title": "Reports and deliverable access",
				"description": "Your access to report packages, deliverables, and portal download links will be removed with the account.",
			},
		]

		if profile:
			items.append(
				{
					"title": "Profile settings and security setup",
					"description": "Your saved contact information, profile preferences, and authenticator setup tied to this portal account will be erased.",
				}
			)

		return items

	def _get_deletion_context(self):
		deletion_request = getattr(self.request.user, "account_deletion_request", None)
		newsletter_active = NewsletterSubscriber.objects.filter(email__iexact=self.request.user.email, is_active=True).exists()
		snapshot = self._build_portal_snapshot()
		context = {
			"delete_account_rundown": self._get_delete_account_rundown(),
			"newsletter_subscription_active": newsletter_active,
			"deletion_request": deletion_request,
		}
		context.update(snapshot)
		return context


class LoginView(RedirectURLMixin, FormView):
	template_name = "registration/login.html"
	form_class = LoginForm
	redirect_authenticated_user = True

	def dispatch(self, request, *args, **kwargs):
		purge_expired_account_deletions()
		if self.redirect_authenticated_user and request.user.is_authenticated:
			return redirect(self.get_success_url())
		return super().dispatch(request, *args, **kwargs)

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs["request"] = self.request
		return kwargs

	def get_success_url(self):
		if not self.request.user.is_authenticated:
			return self.get_redirect_url() or settings.LOGIN_REDIRECT_URL
		return _build_login_success_url(self.request, self.request.user, redirect_url=self.get_redirect_url())

	def form_valid(self, form):
		user = form.get_user()
		success_url = _build_login_success_url(self.request, user, redirect_url=self.get_redirect_url())
		profile = getattr(user, "account_profile", None)
		if profile and profile.two_factor_enabled and profile.two_factor_secret:
			self.request.session["pending_2fa_user_id"] = user.pk
			self.request.session["pending_2fa_backend"] = getattr(user, "backend", "django.contrib.auth.backends.ModelBackend")
			self.request.session["pending_2fa_success_url"] = success_url
			self.request.session["pending_login_pwa_mode"] = "1" if _is_pwa_login_request(self.request) else "0"
			return redirect("login_2fa")

		login(self.request, user)
		_recover_scheduled_deletion(self.request, user)
		self.request.session.pop("pending_login_pwa_mode", None)
		return redirect(success_url)


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
		success_url = self.request.session.get("pending_2fa_success_url") or settings.LOGIN_REDIRECT_URL
		user = User.objects.filter(pk=user_id).select_related("account_profile").first()
		if not user or not getattr(user, "account_profile", None) or not user.account_profile.two_factor_secret:
			messages.error(self.request, "Your 2FA session expired. Please sign in again.")
			self.request.session.pop("pending_2fa_user_id", None)
			self.request.session.pop("pending_2fa_backend", None)
			self.request.session.pop("pending_2fa_success_url", None)
			self.request.session.pop("pending_login_pwa_mode", None)
			return redirect("login")

		if not verify_totp(user.account_profile.two_factor_secret, form.cleaned_data["otp_code"]):
			form.add_error("otp_code", "Enter a valid authentication code.")
			return self.form_invalid(form)

		user.backend = backend or "django.contrib.auth.backends.ModelBackend"
		login(self.request, user)
		_recover_scheduled_deletion(self.request, user)
		self.request.session.pop("pending_2fa_user_id", None)
		self.request.session.pop("pending_2fa_backend", None)
		self.request.session.pop("pending_2fa_success_url", None)
		self.request.session.pop("pending_login_pwa_mode", None)
		messages.success(self.request, "Two-factor authentication complete.")
		return redirect(success_url)


class DashboardView(LoginRequiredMixin, PortalContextMixin, TemplateView):
	template_name = "accounts/dashboard.html"
	login_url = "login"

	def dispatch(self, request, *args, **kwargs):
		if request.user.is_authenticated and request.user.is_staff:
			return redirect("admin:index")
		return super().dispatch(request, *args, **kwargs)

	def post(self, request, *args, **kwargs):
		action = (request.POST.get("settings_action") or "newsletter").strip()
		client = self._get_client_record()
		profile = self._get_account_profile()

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

		if action == "client_profile":
			form = ClientPortalProfileForm(request.POST, instance=client, profile=profile)
			if form.is_valid():
				form.save()
				messages.success(request, "Your business profile has been updated.")
				return redirect("dashboard")

			context = self.get_context_data(client_profile_form=form)
			return self.render_to_response(context)

		if action == "project_message":
			form = ProjectMessageForm(request.POST, request.FILES, client=client)
			if form.is_valid():
				project_message = form.save(commit=False)
				project_message.sender = request.user
				project_message.save()
				project_message.send_notification()
				messages.success(request, "Your project message has been sent.")
				return redirect("dashboard")

			context = self.get_context_data(project_message_form=form)
			return self.render_to_response(context)

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
		client = self._get_client_record()
		context["newsletter_form"] = kwargs.get("newsletter_form") or NewsletterPreferenceForm(initial=self._get_newsletter_initial())
		context["client_profile_form"] = kwargs.get("client_profile_form") or ClientPortalProfileForm(instance=client, profile=profile)
		context["two_factor_setup_form"] = kwargs.get("two_factor_setup_form") or TwoFactorSetupForm()
		context["project_chat_widget_html"] = render_project_chat_widget(
			self.request,
			client,
			form=kwargs.get("project_message_form"),
			submit_url=reverse("project_chat_widget"),
			refresh_url=reverse("project_chat_widget"),
		)
		context.update(
			{
				"turnstile_enabled": is_turnstile_enabled_for_request(self.request),
				"turnstile_site_key": settings.TURNSTILE_SITE_KEY,
				"two_factor_enabled": bool(profile and profile.two_factor_enabled),
				"two_factor_pending": bool(pending_secret),
				"two_factor_setup_key": pending_secret,
				"two_factor_otpauth_uri": build_totp_uri(pending_secret, self.request.user.username) if pending_secret else "",
				"two_factor_qr_data_uri": _build_qr_data_uri(build_totp_uri(pending_secret, self.request.user.username)) if pending_secret else "",
			}
		)
		context.update(self._build_portal_snapshot())
		return context


class DeleteAccountView(LoginRequiredMixin, PortalContextMixin, FormView):
	template_name = "accounts/delete_account.html"
	form_class = DeleteAccountForm
	login_url = "login"

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs["user"] = self.request.user
		return kwargs

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context.update(self._get_deletion_context())
		return context

	def form_valid(self, form):
		deletion_request = AccountDeletionRequest.schedule_for_user(self.request.user)
		if self.request.user.email:
			send_templated_email(
				subject="Your Insights account deletion request",
				to=[self.request.user.email],
				template_prefix="account_deletion_scheduled",
				context={
					"email_title": "Account Deletion Scheduled",
					"heading": "Your account deletion has been scheduled",
					"subheading": "You have 7 days to recover your account by logging back in.",
					"scheduled_for": deletion_request.scheduled_for,
					"login_url": f"{getattr(settings, 'SITE_URL', 'http://localhost:8000').rstrip('/')}{reverse('login')}",
				},
				from_email=settings.DEFAULT_FROM_EMAIL,
			)
		self.request.session.pop("pending_2fa_secret", None)
		self.request.session.pop("pending_2fa_user_id", None)
		self.request.session.pop("pending_2fa_backend", None)
		logout(self.request)
		messages.success(
			self.request,
			"Your account is scheduled for deletion in 7 days. Log back in before then to cancel the deletion and restore full access.",
		)
		return redirect("login")


class SignupView(FormView):
	template_name = "accounts/signup.html"
	form_class = SignupForm

	def dispatch(self, request, *args, **kwargs):
		if request.user.is_authenticated:
			return redirect("home")
		return super().dispatch(request, *args, **kwargs)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["turnstile_enabled"] = is_turnstile_enabled_for_request(self.request)
		context["turnstile_site_key"] = settings.TURNSTILE_SITE_KEY
		return context

	def form_valid(self, form):
		turnstile_ok, _ = _verify_turnstile_request(self.request)
		if not turnstile_ok:
			form.add_error(None, "Security verification failed. Please try again.")
			return self.form_invalid(form)

		user = form.save()
		get_or_create_client_for_user(user)
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


class PrivacyView(TemplateView):
	template_name = "accounts/privacy.html"
