from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		("clients", "0003_client_organization_description"),
	]

	operations = [
		migrations.AddField(
			model_name="project",
			name="consultant_name",
			field=models.CharField(blank=True, max_length=180),
		),
	]