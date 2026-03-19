from django import forms

from .models import Project, ProjectMessage


class ProjectMessageForm(forms.ModelForm):
	project = forms.ModelChoiceField(queryset=Project.objects.none(), empty_label=None)

	class Meta:
		model = ProjectMessage
		fields = ("project", "body")
		widgets = {
			"body": forms.Textarea(
				attrs={
					"rows": 4,
					"placeholder": "Send a project update or question to the Insights team.",
				}
			),
		}

	def __init__(self, *args, client=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.client = client
		if client is not None:
			self.fields["project"].queryset = client.projects.exclude(status=Project.STATUS_CANCELLED).order_by("name")
		self.fields["project"].label_from_instance = lambda project: f"{project.name} ({project.get_status_display()})"

	def clean_project(self):
		project = self.cleaned_data["project"]
		if self.client and project.client_id != self.client.pk:
			raise forms.ValidationError("Choose one of your own projects.")
		return project


class AdminProjectCreateForm(forms.ModelForm):
	class Meta:
		model = Project
		fields = ("name", "status", "start_date", "end_date", "consultant", "description")
		widgets = {
			"start_date": forms.DateInput(attrs={"type": "date"}),
			"end_date": forms.DateInput(attrs={"type": "date"}),
			"description": forms.Textarea(attrs={"rows": 3, "placeholder": "Project scope, milestones, or deliverable details."}),
		}


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