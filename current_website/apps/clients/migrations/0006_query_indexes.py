from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		("clients", "0005_alter_client_id_alter_client_organization_name_and_more"),
	]

	operations = [
		migrations.AddIndex(
			model_name="projectsubtask",
			index=models.Index(fields=["project", "is_completed", "due_date", "created_at"], name="clients_pro_project_2677f4_idx"),
		),
		migrations.AddIndex(
			model_name="projectnote",
			index=models.Index(fields=["project", "-created_at"], name="clients_pro_project_5d9f3e_idx"),
		),
		migrations.AddIndex(
			model_name="projectmessage",
			index=models.Index(fields=["project", "-created_at"], name="clients_pro_project_957694_idx"),
		),
	]