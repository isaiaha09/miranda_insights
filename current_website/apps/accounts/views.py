from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import FormView, TemplateView

from .forms import SignupForm, UsernameRecoveryForm


User = get_user_model()


class DashboardView(LoginRequiredMixin, TemplateView):
	template_name = "accounts/dashboard.html"
	login_url = "login"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context.update(
			{
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

	def form_valid(self, form):
		user = form.save()
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
			usernames = "\n".join(f"- {user.username}" for user in users)
			send_mail(
				subject="Your Insights username",
				message=(
					"We received a request to recover your username.\n\n"
					"The following username(s) are associated with this email address:\n"
					f"{usernames}\n\n"
					"If you did not request this email, you can ignore it."
				),
				from_email=settings.DEFAULT_FROM_EMAIL,
				recipient_list=[email],
				fail_silently=True,
			)

		return render(self.request, "accounts/recover_username_done.html", {"email": email})


class TermsView(TemplateView):
	template_name = "accounts/terms.html"
