from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

	dependencies = [
		("accounts", "0003_alter_accountprofile_options"),
		migrations.swappable_dependency(settings.AUTH_USER_MODEL),
	]

	operations = [
		migrations.CreateModel(
			name="AccountDeletionRequest",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("requested_at", models.DateTimeField(default=django.utils.timezone.now)),
				("scheduled_for", models.DateTimeField(db_index=True)),
				(
					"user",
					models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="account_deletion_request", to=settings.AUTH_USER_MODEL),
				),
			],
			options={
				"verbose_name": "Account Deletion Request",
				"verbose_name_plural": "Account Deletion Requests",
				"ordering": ["-requested_at"],
			},
		),
	]