from django.db import migrations


class Migration(migrations.Migration):

	dependencies = [
		("accounts", "0002_accountprofile_two_factor"),
	]

	operations = [
		migrations.AlterModelOptions(
			name="accountprofile",
			options={
				"verbose_name": "Account Profile",
				"verbose_name_plural": "Account Profiles",
			},
		),
	]