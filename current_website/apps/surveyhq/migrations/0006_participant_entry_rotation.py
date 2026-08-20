import secrets
import uuid

import apps.surveyhq.models
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def seed_participant_access(apps, schema_editor):
    ParticipantAccess = apps.get_model("surveyhq", "SurveyHQParticipantAccess")
    ParticipantAccess.objects.get_or_create(
        singleton_key="global",
        defaults={"active_entry_token": secrets.token_urlsafe(32)},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("surveyhq", "0005_surveyquestion_images"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SurveyHQParticipantAccess",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("singleton_key", models.CharField(default="global", editable=False, max_length=16, unique=True)),
                ("active_entry_token", models.CharField(default=apps.surveyhq.models.generate_participant_entry_token, editable=False, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("rotated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("rotated_by", models.ForeignKey(blank=True, limit_choices_to={"is_staff": True}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="surveyhq_participant_access_rotations", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "SurveyHQ participant access",
                "constraints": [models.CheckConstraint(condition=models.Q(("singleton_key", "global")), name="svhq_participant_access_global_ck")],
            },
        ),
        migrations.AlterField(
            model_name="surveyhqauditevent",
            name="entity_type",
            field=models.CharField(
                choices=[
                    ("survey", "Survey"),
                    ("template", "Template"),
                    ("participant_access", "Participant Access"),
                ],
                max_length=24,
            ),
        ),
        migrations.RunPython(seed_participant_access, migrations.RunPython.noop),
    ]
