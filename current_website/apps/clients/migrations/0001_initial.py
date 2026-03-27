from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

	initial = True

	dependencies = [
		migrations.swappable_dependency(settings.AUTH_USER_MODEL),
	]

	operations = [
		migrations.CreateModel(
			name="Client",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("organization_name", models.CharField(blank=True, max_length=180)),
				("contact_name", models.CharField(max_length=180)),
				("contact_email", models.EmailField(max_length=254)),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("updated_at", models.DateTimeField(auto_now=True)),
				(
					"user",
					models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="client_record", to=settings.AUTH_USER_MODEL),
				),
			],
			options={"ordering": ["contact_name", "organization_name"]},
		),
		migrations.CreateModel(
			name="Project",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("name", models.CharField(max_length=180)),
				("description", models.TextField(blank=True)),
				("status", models.CharField(choices=[("pending", "Pending"), ("in_progress", "In Progress"), ("cancelled", "Cancelled"), ("completed", "Completed")], default="pending", max_length=24)),
				("start_date", models.DateField(blank=True, null=True)),
				("end_date", models.DateField(blank=True, null=True)),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("updated_at", models.DateTimeField(auto_now=True)),
				("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="projects", to="clients.client")),
				("consultant", models.ForeignKey(blank=True, limit_choices_to={"is_staff": True}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="client_projects", to=settings.AUTH_USER_MODEL)),
			],
			options={"ordering": ["name"]},
		),
		migrations.CreateModel(
			name="ProjectMessage",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("body", models.TextField()),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="clients.project")),
				("sender", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="project_messages", to=settings.AUTH_USER_MODEL)),
			],
			options={"ordering": ["created_at"]},
		),
		migrations.CreateModel(
			name="ProjectNote",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("content", models.TextField()),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("created_by", models.ForeignKey(blank=True, limit_choices_to={"is_staff": True}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="project_notes", to=settings.AUTH_USER_MODEL)),
				("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notes", to="clients.project")),
			],
			options={"ordering": ["-created_at"]},
		),
		migrations.CreateModel(
			name="ProjectSubtask",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("title", models.CharField(max_length=180)),
				("details", models.TextField(blank=True)),
				("is_completed", models.BooleanField(default=False)),
				("completed_at", models.DateTimeField(blank=True, null=True)),
				("due_date", models.DateField(blank=True, null=True)),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("completed_by", models.ForeignKey(blank=True, limit_choices_to={"is_staff": True}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="completed_project_subtasks", to=settings.AUTH_USER_MODEL)),
				("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="subtasks", to="clients.project")),
			],
			options={"ordering": ["is_completed", "created_at"]},
		),
	]