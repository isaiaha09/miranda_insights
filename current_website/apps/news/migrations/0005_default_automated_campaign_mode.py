from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0004_newsletter_assets_and_templates"),
    ]

    operations = [
        migrations.AlterField(
            model_name="newslettercampaign",
            name="mode",
            field=models.CharField(
                choices=[("automated", "Automated"), ("custom", "Custom")],
                default="automated",
                max_length=20,
            ),
        ),
    ]
