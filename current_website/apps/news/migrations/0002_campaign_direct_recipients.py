from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="newslettercampaign",
            name="direct_recipients",
            field=models.TextField(
                blank=True,
                help_text="Optional extra recipients (comma/newline separated emails).",
            ),
        ),
        migrations.AddField(
            model_name="newslettercampaign",
            name="include_subscribers",
            field=models.BooleanField(
                default=True,
                help_text="If enabled, send to all active newsletter subscribers.",
            ),
        ),
    ]
