from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		("clients", "0001_initial"),
	]

	operations = [
		migrations.AddField(
			model_name="projectmessage",
			name="attachment_file",
			field=models.FileField(blank=True, upload_to="project-message-attachments/%Y/%m/%d/"),
		),
		migrations.AddField(
			model_name="projectmessage",
			name="attachment_link",
			field=models.URLField(blank=True),
		),
		migrations.AlterField(
			model_name="projectmessage",
			name="body",
			field=models.TextField(blank=True),
		),
	]