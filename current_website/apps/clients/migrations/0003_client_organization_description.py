from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		("clients", "0002_projectmessage_attachments"),
	]

	operations = [
		migrations.AddField(
			model_name="client",
			name="organization_description",
			field=models.TextField(blank=True, verbose_name="business/organization description"),
		),
	]