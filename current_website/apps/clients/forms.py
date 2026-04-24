from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from pathlib import Path

from apps.accounts.models import AccountProfile
from .models import Client, Project, ProjectMessage


User = get_user_model()

MAX_PROJECT_ATTACHMENT_BYTES = 10 * 1024 * 1024
BLOCKED_PROJECT_ATTACHMENT_EXTENSIONS = {
	".ade", ".adp", ".apk", ".appx", ".bat", ".cab", ".chm", ".cmd", ".com",
	".cpl", ".dll", ".dmg", ".exe", ".hta", ".html", ".htm", ".iso", ".jar",
	".js", ".jse", ".lnk", ".msi", ".msp", ".msix", ".msh", ".ps1", ".psm1",
	".reg", ".scr", ".sh", ".svg", ".url", ".vb", ".vbe", ".vbs", ".wsf",
	".xhtml",
}
ALLOWED_PROJECT_ATTACHMENT_EXTENSIONS = {
	".csv", ".doc", ".docx", ".pdf", ".ppt", ".pptx", ".rtf", ".txt",
	".xls", ".xlsx", ".zip",
}
ALLOWED_PROJECT_ATTACHMENT_CONTENT_TYPES = {
	"application/msword",
	"application/pdf",
	"application/rtf",
	"application/vnd.ms-excel",
	"application/vnd.ms-powerpoint",
	"application/vnd.openxmlformats-officedocument.presentationml.presentation",
	"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	"application/x-zip-compressed",
	"application/zip",
	"text/csv",
	"text/plain",
}


class ProjectMessageForm(forms.ModelForm):
	project = forms.ModelChoiceField(queryset=Project.objects.none(), empty_label=None)

	class Meta:
		model = ProjectMessage
		fields = ("project", "body", "attachment_file", "attachment_link")
		widgets = {
			"body": forms.Textarea(
				attrs={
					"rows": 4,
					"placeholder": "Send a project update or question to the Insights team.",
				}
			),
			"attachment_link": forms.URLInput(attrs={"placeholder": "https://example.com/reference-link"}),
		}

	def __init__(self, *args, client=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.client = client
		self.fields["body"].required = False
		self.fields["attachment_file"].required = False
		self.fields["attachment_link"].required = False
		self.fields["attachment_file"].widget.attrs.update({
			"class": "project-chat-widget__file-input",
			"accept": ",".join(sorted(ALLOWED_PROJECT_ATTACHMENT_EXTENSIONS)),
		})
		self.fields["attachment_link"].widget.attrs.update({"class": "project-chat-widget__link-input", "data-link-input": "true"})
		if client is not None:
			self.fields["project"].queryset = client.projects.exclude(status=Project.STATUS_CANCELLED).order_by("name")
		self.fields["project"].label_from_instance = lambda project: f"{project.name} ({project.get_status_display()})"

	def clean_project(self):
		project = self.cleaned_data["project"]
		if self.client and project.client_id != self.client.pk:
			raise forms.ValidationError("Choose one of your own projects.")
		return project

	def clean(self):
		cleaned_data = super().clean()
		body = (cleaned_data.get("body") or "").strip()
		attachment_file = cleaned_data.get("attachment_file")
		attachment_link = (cleaned_data.get("attachment_link") or "").strip()
		if attachment_file:
			lower_name = attachment_file.name.lower()
			extension = Path(lower_name).suffix
			blocked_extension = next((ext for ext in BLOCKED_PROJECT_ATTACHMENT_EXTENSIONS if lower_name.endswith(ext)), None)
			if blocked_extension:
				raise ValidationError(f"Files ending in {blocked_extension} are not allowed for project attachments.")
			if extension not in ALLOWED_PROJECT_ATTACHMENT_EXTENSIONS:
				raise ValidationError("Upload a PDF, Office document, text file, ZIP archive, or CSV file.")
			content_type = str(getattr(attachment_file, "content_type", "") or "").split(";", 1)[0].strip().lower()
			if content_type and content_type not in ALLOWED_PROJECT_ATTACHMENT_CONTENT_TYPES:
				raise ValidationError("That file type is not allowed for project attachments.")
			if attachment_file.size > MAX_PROJECT_ATTACHMENT_BYTES:
				raise ValidationError("Project attachments must be 10 MB or smaller.")
		if not body and not attachment_file and not attachment_link:
			raise forms.ValidationError("Add a message, upload a file, or include a link before sending.")
		cleaned_data["body"] = body
		cleaned_data["attachment_link"] = attachment_link
		return cleaned_data


class ClientPortalProfileForm(forms.ModelForm):
	industry_type = forms.ChoiceField(choices=AccountProfile.INDUSTRY_CHOICES, label="Industry Type")

	class Meta:
		model = Client
		fields = ("organization_name", "organization_description")
		widgets = {
			"organization_name": forms.TextInput(attrs={"placeholder": "Business or organization name"}),
			"organization_description": forms.Textarea(attrs={"rows": 4, "placeholder": "Describe your organization, team, or the work you do with Miranda Insights."}),
		}
		labels = {
			"organization_name": "Business/Organization Name",
			"organization_description": "Business/Organization Description",
		}

	def __init__(self, *args, profile=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.profile = profile
		self.fields["industry_type"].choices = AccountProfile.INDUSTRY_CHOICES
		if profile is not None:
			self.fields["industry_type"].initial = profile.industry_type

	def save(self, commit=True):
		client = super().save(commit=commit)
		if self.profile is not None:
			self.profile.industry_type = self.cleaned_data["industry_type"]
			if commit:
				self.profile.save(update_fields=["industry_type"])
		return client


class AdminProjectCreateForm(forms.ModelForm):
	CONSULTANT_OPTION_MIRANDA_TEAM = "__miranda_team__"
	CONSULTANT_OPTION_CUSTOM_NAME = "__custom_name__"

	consultant_choice = forms.ChoiceField(required=False, label="Consultant")
	consultant_custom_name = forms.CharField(
		required=False,
		label="Custom Consultant Name",
		widget=forms.TextInput(attrs={"placeholder": "Enter the consultant name to display"}),
	)

	class Meta:
		model = Project
		fields = ("name", "status", "start_date", "end_date", "description")
		widgets = {
			"start_date": forms.DateInput(attrs={"type": "date"}),
			"end_date": forms.DateInput(attrs={"type": "date"}),
			"description": forms.Textarea(attrs={"rows": 3, "placeholder": "Project scope, milestones, or deliverable details."}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		toggle_custom_consultant_script = (
			"var field=this.form && this.form.querySelector('[data-consultant-custom-field]');"
			"if(!field){return;}"
			"var show=this.value==='" + self.CONSULTANT_OPTION_CUSTOM_NAME + "';"
			"field.style.display=show?'grid':'none';"
			"if(!show){"
			"var input=field.querySelector('[data-consultant-custom-name]');"
			"if(input){input.value='';}"
			"}"
		)
		self.fields["consultant_choice"].widget.attrs.update({
			"data-consultant-choice": "true",
			"data-custom-consultant-option": self.CONSULTANT_OPTION_CUSTOM_NAME,
			"onchange": toggle_custom_consultant_script,
		})
		self.fields["consultant_custom_name"].widget.attrs.update({"data-consultant-custom-name": "true"})
		staff_users = User.objects.filter(is_staff=True).order_by("first_name", "last_name", "username")
		choices = [("", "---------")]
		choices.extend(
			(str(user.pk), user.get_full_name().strip() or user.username)
			for user in staff_users
		)
		choices.extend(
			[
				(self.CONSULTANT_OPTION_MIRANDA_TEAM, Project.CONSULTANT_NAME_MIRANDA_INSIGHTS_TEAM),
				(self.CONSULTANT_OPTION_CUSTOM_NAME, "Custom Name"),
			]
		)
		self.fields["consultant_choice"].choices = choices

		if self.instance.pk:
			if self.instance.consultant_id:
				self.fields["consultant_choice"].initial = str(self.instance.consultant_id)
			elif self.instance.consultant_name == Project.CONSULTANT_NAME_MIRANDA_INSIGHTS_TEAM:
				self.fields["consultant_choice"].initial = self.CONSULTANT_OPTION_MIRANDA_TEAM
			elif self.instance.consultant_name:
				self.fields["consultant_choice"].initial = self.CONSULTANT_OPTION_CUSTOM_NAME
				self.fields["consultant_custom_name"].initial = self.instance.consultant_name

	def clean(self):
		cleaned_data = super().clean()
		consultant_choice = (cleaned_data.get("consultant_choice") or "").strip()
		custom_name = (cleaned_data.get("consultant_custom_name") or "").strip()

		if consultant_choice == self.CONSULTANT_OPTION_CUSTOM_NAME and not custom_name:
			self.add_error("consultant_custom_name", "Enter the custom consultant name to use for this project.")

		return cleaned_data

	def save(self, commit=True):
		project = super().save(commit=False)
		consultant_choice = (self.cleaned_data.get("consultant_choice") or "").strip()
		custom_name = (self.cleaned_data.get("consultant_custom_name") or "").strip()

		project.consultant = None
		project.consultant_name = ""

		if consultant_choice == self.CONSULTANT_OPTION_MIRANDA_TEAM:
			project.consultant_name = Project.CONSULTANT_NAME_MIRANDA_INSIGHTS_TEAM
		elif consultant_choice == self.CONSULTANT_OPTION_CUSTOM_NAME:
			project.consultant_name = custom_name
		elif consultant_choice:
			project.consultant = User.objects.filter(pk=consultant_choice, is_staff=True).first()

		if commit:
			project.save()
		return project


class AdminProjectSubtaskForm(forms.Form):
	project = forms.ModelChoiceField(queryset=Project.objects.none(), empty_label=None)
	title = forms.CharField(max_length=180)
	details = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Subtask details"}))
	due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
	is_completed = forms.BooleanField(required=False)

	def __init__(self, *args, client=None, **kwargs):
		super().__init__(*args, **kwargs)
		if client is not None:
			self.fields["project"].queryset = client.projects.exclude(status=Project.STATUS_CANCELLED).order_by("name")
		self.fields["project"].label_from_instance = lambda project: f"{project.name} ({project.get_status_display()})"


class AdminProjectNoteForm(forms.Form):
	project = forms.ModelChoiceField(queryset=Project.objects.none(), empty_label=None)
	content = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Add a project note or internal update."}))

	def __init__(self, *args, client=None, **kwargs):
		super().__init__(*args, **kwargs)
		if client is not None:
			self.fields["project"].queryset = client.projects.exclude(status=Project.STATUS_CANCELLED).order_by("name")
		self.fields["project"].label_from_instance = lambda project: f"{project.name} ({project.get_status_display()})"