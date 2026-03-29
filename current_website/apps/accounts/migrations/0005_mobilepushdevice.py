from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

	dependencies = [
		("accounts", "0004_accountdeletionrequest"),
	]

	operations = [
		migrations.CreateModel(
			name="MobilePushDevice",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("token", models.CharField(max_length=255, unique=True)),
				("platform", models.CharField(choices=[("ios", "iOS"), ("android", "Android"), ("unknown", "Unknown")], default="unknown", max_length=24)),
				("device_name", models.CharField(blank=True, max_length=120)),
				("is_active", models.BooleanField(default=True)),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("updated_at", models.DateTimeField(auto_now=True)),
				("last_registered_at", models.DateTimeField(default=django.utils.timezone.now)),
				("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mobile_push_devices", to=settings.AUTH_USER_MODEL)),
			],
			options={
				"verbose_name": "Mobile Push Device",
				"verbose_name_plural": "Mobile Push Devices",
				"ordering": ["-last_registered_at", "-updated_at"],
			},
		),
	]