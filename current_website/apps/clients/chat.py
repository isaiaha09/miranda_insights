from datetime import timedelta

from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .forms import ProjectMessageForm
from .models import ProjectMessage


CHAT_MESSAGE_RETENTION_DAYS = 7


def prune_expired_project_messages(client):
	cutoff_date = timezone.localdate() - timedelta(days=CHAT_MESSAGE_RETENTION_DAYS - 1)
	ProjectMessage.objects.filter(project__client=client, created_at__date__lt=cutoff_date).delete()


def build_project_chat_context(request, client, *, selected_project_id=None, form=None, submit_url="", refresh_url="", is_admin=False, notice="", notice_level="info"):
	prune_expired_project_messages(client)
	projects = list(client.projects.exclude(status="cancelled").order_by("name"))
	selected_project = None
	if selected_project_id:
		selected_project = next((project for project in projects if str(project.pk) == str(selected_project_id)), None)
	if selected_project is None and projects:
		selected_project = projects[0]

	if form is None:
		initial = {"project": selected_project.pk} if selected_project else None
		form = ProjectMessageForm(client=client, initial=initial)
	elif selected_project and not form.is_bound:
		form.fields["project"].initial = selected_project.pk

	messages = []
	if selected_project is not None:
		messages = list(selected_project.messages.select_related("sender", "project").order_by("created_at"))

	return {
		"client": client,
		"chat_projects": projects,
		"chat_selected_project": selected_project,
		"chat_messages": messages,
		"chat_message_count": len(messages),
		"project_message_form": form,
		"chat_submit_url": submit_url,
		"chat_refresh_url": refresh_url,
		"chat_is_admin": is_admin,
		"chat_notice": notice,
		"chat_notice_level": notice_level,
		"chat_message_retention_days": CHAT_MESSAGE_RETENTION_DAYS,
		"chat_widget_title": "Project Chat",
		"chat_widget_subtitle": client.display_name,
	}


def render_project_chat_widget(request, client, *, selected_project_id=None, form=None, submit_url="", refresh_url="", is_admin=False, notice="", notice_level="info"):
	context = build_project_chat_context(
		request,
		client,
		selected_project_id=selected_project_id,
		form=form,
		submit_url=submit_url,
		refresh_url=refresh_url,
		is_admin=is_admin,
		notice=notice,
		notice_level=notice_level,
	)
	return render_to_string("clients/_project_chat_widget.html", context, request=request)