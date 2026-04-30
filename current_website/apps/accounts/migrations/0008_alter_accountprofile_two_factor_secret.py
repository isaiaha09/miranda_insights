from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		("accounts", "0007_mobilesessionbridge"),
	]

	operations = [
		migrations.AlterField(
			model_name="accountprofile",
			name="two_factor_secret",
			field=models.TextField(blank=True),
		),
	]