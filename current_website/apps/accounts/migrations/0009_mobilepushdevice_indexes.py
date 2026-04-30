from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		("accounts", "0008_alter_accountprofile_two_factor_secret"),
	]

	operations = [
		migrations.AddIndex(
			model_name="mobilepushdevice",
			index=models.Index(fields=["user", "is_active"], name="accounts_mo_user_id_6fc96f_idx"),
		),
		migrations.AddIndex(
			model_name="mobilepushdevice",
			index=models.Index(fields=["user", "is_active", "-last_registered_at"], name="accounts_mo_user_id_7f0b84_idx"),
		),
	]