from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views import View

from .chat import render_project_chat_widget
from .forms import ProjectMessageForm
from .models import get_or_create_client_for_user


class ProjectChatWidgetView(LoginRequiredMixin, View):
	def get(self, request, *args, **kwargs):
		client = get_or_create_client_for_user(request.user)
		selected_project_id = request.GET.get("project")
		widget = render_project_chat_widget(
			request,
			client,
			selected_project_id=selected_project_id,
			submit_url=request.path,
			refresh_url=request.path,
		)
		return HttpResponse(widget)

	def post(self, request, *args, **kwargs):
		client = get_or_create_client_for_user(request.user)
		form = ProjectMessageForm(request.POST, client=client)
		selected_project_id = request.POST.get("project")
		if form.is_valid():
			project_message = form.save(commit=False)
			project_message.sender = request.user
			project_message.save()
			project_message.send_notification()
			form = ProjectMessageForm(client=client, initial={"project": project_message.project_id})
			selected_project_id = project_message.project_id
		widget = render_project_chat_widget(
			request,
			client,
			selected_project_id=selected_project_id,
			form=form,
			submit_url=request.path,
			refresh_url=request.path,
		)
		if request.headers.get("x-requested-with") == "XMLHttpRequest":
			return HttpResponse(widget)
		return redirect("dashboard")
