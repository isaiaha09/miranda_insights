from django.template.loader import render_to_string
from django.urls import reverse

from .forms import AdminProjectCreateForm, AdminProjectNoteForm, AdminProjectSubtaskForm


def render_client_workspace(request, client, *, project_form=None, subtask_form=None, note_form=None, notice=None):
	projects = list(client.projects.select_related("consultant").prefetch_related("subtasks", "notes").order_by("name"))
	project_form = project_form or AdminProjectCreateForm()
	subtask_form = subtask_form or AdminProjectSubtaskForm(client=client, prefix="subtask")
	note_form = note_form or AdminProjectNoteForm(client=client, prefix="note")
	workspace_entries = [
		{
			"project": project,
			"edit_url": reverse("admin:clients_project_change", args=[project.pk]),
		}
		for project in projects
	]
	context = {
		"client": client,
		"workspace_notice": notice,
		"project_create_form": project_form,
		"subtask_form": subtask_form,
		"note_form": note_form,
		"workspace_entries": workspace_entries,
		"workspace_submit_url": reverse("admin:clients_client_workspace", args=[client.pk]),
	}
	return render_to_string("admin/clients/_client_workspace.html", context, request=request)