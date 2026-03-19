from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.html import format_html, format_html_join
from django.urls import reverse
from django.urls import path
from unfold.admin import ModelAdmin as UnfoldModelAdmin

from .chat import render_project_chat_widget
from .forms import AdminProjectCreateForm, AdminProjectNoteForm, AdminProjectSubtaskForm, ProjectMessageForm
from .models import Client, Project, ProjectMessage, ProjectNote, ProjectSubtask
from .workspace import render_client_workspace


class ProjectSubtaskInline(admin.TabularInline):
	model = ProjectSubtask
	extra = 0
	fields = ("title", "details", "due_date", "is_completed", "completed_by", "completed_at")
	readonly_fields = ("completed_at",)
	verbose_name = "Project subtask"
	verbose_name_plural = "Project subtasks"


class ProjectNoteInline(admin.TabularInline):
	model = ProjectNote
	extra = 0
	fields = ("content", "created_by", "created_at")
	readonly_fields = ("created_at",)
	verbose_name = "Project note"
	verbose_name_plural = "Project notes"


class ProjectMessageInline(admin.StackedInline):
	model = ProjectMessage
	extra = 0
	fields = ("sender", "body", "created_at")
	readonly_fields = ("created_at",)
	verbose_name = "Project message"
	verbose_name_plural = "Project chat replies"


def _render_admin_chat(messages_queryset):
	items = []
	for message in messages_queryset:
		is_staff = message.is_staff_message
		align = "flex-end" if is_staff else "flex-start"
		background = "linear-gradient(135deg, rgba(88,166,255,0.28), rgba(124,156,255,0.22))" if is_staff else "rgba(255,255,255,0.05)"
		border = "rgba(88,166,255,0.45)" if is_staff else "rgba(230,238,246,0.14)"
		items.append(
			(
				align,
				background,
				border,
				message.sender_label,
				message.project.name,
				message.created_at.strftime("%b %d, %Y %I:%M %p"),
				message.body,
			)
		)

	if not items:
		return format_html(
			'<div style="padding:16px;border:1px dashed rgba(230,238,246,0.18);border-radius:16px;color:#6b7280;">{}</div>',
			"No project messages yet.",
		)

	return format_html(
		'<div style="display:grid;gap:12px;max-height:420px;overflow:auto;padding:4px 2px;">{}</div>',
		format_html_join(
			"",
			(
				'<div style="display:flex;justify-content:{};">'
				'<div style="max-width:70%;padding:12px 14px;border-radius:18px;border:1px solid {};background:{};box-shadow:0 10px 24px rgba(15,23,42,0.08);">'
				'<div style="font-weight:700;color:#111827;">{}</div>'
				'<div style="font-size:12px;color:#6b7280;margin-top:2px;">{} | {}</div>'
				'<div style="margin-top:10px;white-space:pre-wrap;color:#1f2937;line-height:1.6;">{}</div>'
				'</div>'
				'</div>'
			),
			items,
		),
	)


class HiddenClientModelAdmin(UnfoldModelAdmin):
	def get_model_perms(self, request):
		return {}


@admin.register(Client)
class ClientAdmin(UnfoldModelAdmin):
	change_form_template = "admin/clients/client/change_form.html"
	list_display = ("contact_name", "contact_email", "project_count", "active_project_count", "created_at")
	search_fields = ("contact_name", "organization_name", "contact_email", "user__username", "user__email")
	inlines = []
	readonly_fields = ("industry_type_display", "projects_workspace")
	fields = ("user", "organization_name", "organization_description", "industry_type_display", "contact_name", "contact_email", "projects_workspace")

	class Media:
		css = {"all": ("css/project-chat.css",)}
		js = ("js/project-chat.js",)

	def get_urls(self):
		urls = super().get_urls()
		custom_urls = [
			path("<path:object_id>/workspace/", self.admin_site.admin_view(self.workspace_view), name="clients_client_workspace"),
			path("<path:object_id>/chat-widget/", self.admin_site.admin_view(self.chat_widget_view), name="clients_client_chat_widget"),
		]
		return custom_urls + urls

	def workspace_view(self, request, object_id, *args, **kwargs):
		client = get_object_or_404(Client, pk=object_id)
		project_form = None
		subtask_form = None
		note_form = None
		notice = None
		client_updated = False

		if request.method == "POST":
			action = request.POST.get("workspace_action")
			project_id = request.POST.get("project_id")

			if action == "create_project":
				project_form = AdminProjectCreateForm(request.POST)
				if project_form.is_valid():
					project = project_form.save(commit=False)
					project.client = client
					project.save()
					client_updated = True
					notice = f"Created project '{project.name}'."
					messages.success(request, notice)
					project_form = AdminProjectCreateForm()
				else:
					messages.error(request, "Please correct the project details before creating it.")
			elif action == "add_subtask":
				form = AdminProjectSubtaskForm(request.POST, client=client, prefix="subtask")
				subtask_form = form
				if form.is_valid():
					project = form.cleaned_data["project"]
					ProjectSubtask.objects.create(
						project=project,
						title=form.cleaned_data["title"],
						details=form.cleaned_data["details"],
						due_date=form.cleaned_data["due_date"],
						is_completed=form.cleaned_data["is_completed"],
						completed_by=request.user if form.cleaned_data["is_completed"] else None,
					)
					client_updated = True
					notice = f"Added a subtask to '{project.name}'."
					messages.success(request, notice)
					subtask_form = AdminProjectSubtaskForm(client=client, prefix="subtask")
				else:
					messages.error(request, "Please correct the subtask details before saving.")
			elif action == "add_note":
				form = AdminProjectNoteForm(request.POST, client=client, prefix="note")
				note_form = form
				if form.is_valid():
					project = form.cleaned_data["project"]
					ProjectNote.objects.create(project=project, content=form.cleaned_data["content"], created_by=request.user)
					client_updated = True
					notice = f"Added a note to '{project.name}'."
					messages.success(request, notice)
					note_form = AdminProjectNoteForm(client=client, prefix="note")
				else:
					messages.error(request, "Please correct the note before saving.")

		if client_updated:
			client = Client.objects.get(pk=client.pk)

		workspace_html = render_client_workspace(
			request,
			client,
			project_form=project_form,
			subtask_form=subtask_form,
			note_form=note_form,
			notice=notice,
		)
		if request.headers.get("x-requested-with") == "XMLHttpRequest":
			return HttpResponse(workspace_html)
		return redirect(reverse("admin:clients_client_change", args=[client.pk]))

	def chat_widget_view(self, request, object_id, *args, **kwargs):
		client = get_object_or_404(Client, pk=object_id)
		selected_project_id = request.GET.get("project") or request.POST.get("project")
		if request.method == "POST":
			form = ProjectMessageForm(request.POST, request.FILES, client=client)
			if form.is_valid():
				project_message = form.save(commit=False)
				project_message.sender = request.user
				project_message.save()
				project_message.send_notification()
				form = ProjectMessageForm(client=client, initial={"project": project_message.project_id})
				selected_project_id = project_message.project_id
		else:
			form = None
		widget = render_project_chat_widget(
			request,
			client,
			selected_project_id=selected_project_id,
			form=form,
			submit_url=reverse("admin:clients_client_chat_widget", args=[client.pk]),
			refresh_url=reverse("admin:clients_client_chat_widget", args=[client.pk]),
			is_admin=True,
		)
		if request.headers.get("x-requested-with") == "XMLHttpRequest":
			return HttpResponse(widget)
		return redirect(reverse("admin:clients_client_change", args=[client.pk]))

	@admin.display(description="Projects")
	def project_count(self, obj):
		return obj.projects.count()

	@admin.display(description="Industry type")
	def industry_type_display(self, obj):
		profile = getattr(getattr(obj, "user", None), "account_profile", None)
		if not profile:
			return "-"
		return profile.get_industry_type_display()

	@admin.display(description="Client chat log")
	def client_chat_preview(self, obj):
		messages_queryset = ProjectMessage.objects.filter(project__client=obj).select_related("project", "sender")
		return _render_admin_chat(messages_queryset)

	@admin.display(description="Client project workspace")
	def projects_workspace(self, obj):
		return render_client_workspace(getattr(self, "_workspace_request", None), obj)

	def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
		self._workspace_request = request
		try:
			if obj is not None:
				primary_project = obj.projects.order_by("name").first()
				context["client_primary_project_edit_url"] = reverse("admin:clients_project_change", args=[primary_project.pk]) if primary_project else ""
				context["project_chat_widget_html"] = render_project_chat_widget(
					request,
					obj,
					submit_url=reverse("admin:clients_client_chat_widget", args=[obj.pk]),
					refresh_url=reverse("admin:clients_client_chat_widget", args=[obj.pk]),
					is_admin=True,
				)
			return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)
		finally:
			self._workspace_request = None


@admin.register(Project)
class ProjectAdmin(HiddenClientModelAdmin):
	list_display = (
		"name",
		"client",
		"status",
		"start_date",
		"end_date",
		"consultant_display",
		"progress_display",
	)
	list_filter = ("status", "start_date", "end_date", "consultant")
	search_fields = ("name", "client__contact_name", "client__organization_name", "client__contact_email", "consultant_name")
	inlines = [ProjectSubtaskInline, ProjectNoteInline]
	fields = (
		"client",
		"name",
		"description",
		"status",
		"start_date",
		"end_date",
		"consultant",
		"consultant_name",
	)

	@admin.display(description="Progress")
	def progress_display(self, obj):
		return f"{obj.progress_percentage}%"

	@admin.display(description="Consultant")
	def consultant_display(self, obj):
		return obj.consultant_display

	def save_formset(self, request, form, formset, change):
		instances = formset.save(commit=False)
		for deleted_obj in formset.deleted_objects:
			deleted_obj.delete()
		for instance in instances:
			if isinstance(instance, ProjectNote) and instance.created_by_id is None:
				instance.created_by = request.user
			if isinstance(instance, ProjectSubtask) and instance.is_completed and instance.completed_by_id is None:
				instance.completed_by = request.user
			is_new_message = isinstance(instance, ProjectMessage) and instance.pk is None
			instance.save()
			if is_new_message:
				instance.send_notification()
		formset.save_m2m()


@admin.register(ProjectMessage)
class ProjectMessageAdmin(HiddenClientModelAdmin):
	list_display = ("project", "sender", "recipient_display", "has_attachment_display", "created_at")
	list_filter = ("project__status", "project__consultant", "created_at")
	search_fields = ("project__name", "project__client__contact_name", "body", "sender__username", "sender__email")
	readonly_fields = ("created_at",)
	fields = ("project", "sender", "body", "attachment_file", "attachment_link", "created_at")

	@admin.display(description="Recipient")
	def recipient_display(self, obj):
		return obj.recipient_email

	@admin.display(description="Attachment")
	def has_attachment_display(self, obj):
		return "Yes" if obj.has_attachment else "No"

	def save_model(self, request, obj, form, change):
		is_new = obj.pk is None
		super().save_model(request, obj, form, change)
		if is_new:
			obj.send_notification()


@admin.register(ProjectNote)
class ProjectNoteAdmin(HiddenClientModelAdmin):
	list_display = ("project", "created_by", "created_at")
	list_filter = ("project__status", "project__consultant", "created_at")
	search_fields = ("project__name", "content", "created_by__username", "created_by__email")


@admin.register(ProjectSubtask)
class ProjectSubtaskAdmin(HiddenClientModelAdmin):
	list_display = ("title", "project", "is_completed", "due_date", "completed_by", "completed_at")
	list_filter = ("is_completed", "project__status", "project__consultant", "due_date")
	search_fields = ("title", "project__name", "details")
