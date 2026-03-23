from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View

from .chat import render_project_chat_widget
from .forms import ProjectMessageForm
from .models import ProjectMessage, get_or_create_client_for_user


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
		form = ProjectMessageForm(request.POST, request.FILES, client=client)
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


class ProjectMessageAttachmentDownloadView(LoginRequiredMixin, View):
	def get(self, request, message_id, *args, **kwargs):
		message = get_object_or_404(ProjectMessage.objects.select_related("project__client", "sender"), pk=message_id)
		if not message.attachment_file:
			raise Http404("Attachment not found.")

		if request.user.is_staff:
			allowed = True
		else:
			client = get_or_create_client_for_user(request.user)
			allowed = message.project.client_id == client.pk

		if not allowed:
			raise Http404("Attachment not found.")

		message.attachment_file.open("rb")
		return FileResponse(message.attachment_file, as_attachment=True, filename=message.attachment_file_name or None)
