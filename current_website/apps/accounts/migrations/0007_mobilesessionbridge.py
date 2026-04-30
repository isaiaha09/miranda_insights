from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

	dependencies = [
		("accounts", "0006_alter_accountdeletionrequest_id_and_more"),
	]

	operations = [
		migrations.CreateModel(
			name="MobileSessionBridge",
			fields=[
				("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("token_digest", models.CharField(max_length=64, unique=True)),
				("password_hash", models.CharField(max_length=128)),
				("redirect_url", models.TextField(blank=True)),
				("remember_me", models.BooleanField(default=False)),
				("expires_at", models.DateTimeField(db_index=True)),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("consumed_at", models.DateTimeField(blank=True, null=True)),
				("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mobile_session_bridges", to=settings.AUTH_USER_MODEL)),
			],
			options={
				"ordering": ["-created_at"],
			},
		),
		migrations.AddIndex(
			model_name="mobilesessionbridge",
			index=models.Index(fields=["user", "expires_at"], name="accounts_mo_user_id_1e9e3e_idx"),
		),
	]