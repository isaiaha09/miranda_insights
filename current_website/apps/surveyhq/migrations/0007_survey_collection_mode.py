from django.db import migrations, models


def classify_existing_drafts(apps, schema_editor):
    Survey = apps.get_model("surveyhq", "Survey")
    Survey.objects.filter(status="draft", published_at__isnull=True).update(
        collection_mode="anonymous"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("surveyhq", "0006_participant_entry_rotation"),
    ]

    operations = [
        migrations.AddField(
            model_name="survey",
            name="collection_mode",
            field=models.CharField(
                blank=True,
                choices=[("anonymous", "Anonymous")],
                max_length=24,
                null=True,
            ),
        ),
        migrations.RunPython(classify_existing_drafts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="survey",
            name="collection_mode",
            field=models.CharField(
                blank=True,
                choices=[("anonymous", "Anonymous")],
                default="anonymous",
                max_length=24,
                null=True,
            ),
        ),
    ]
