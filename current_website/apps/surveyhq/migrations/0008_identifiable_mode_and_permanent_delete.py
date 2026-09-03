from django.db import migrations, models


PERMISSION_CODENAME = "permanently_delete_survey"
PERMISSION_NAME = "Can permanently delete published SurveyHQ surveys"
MANAGERS_GROUP = "SurveyHQ Managers"


def grant_permanent_delete_permission(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    content_type = ContentType.objects.get(app_label="surveyhq", model="survey")
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename=PERMISSION_CODENAME,
        defaults={"name": PERMISSION_NAME},
    )
    manager, _ = Group.objects.get_or_create(name=MANAGERS_GROUP)
    manager.permissions.add(permission)


def revoke_permanent_delete_permission(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    permission = Permission.objects.filter(
        content_type__app_label="surveyhq",
        codename=PERMISSION_CODENAME,
    ).first()
    if permission:
        for group in Group.objects.filter(name=MANAGERS_GROUP):
            group.permissions.remove(permission)
        permission.delete()


class Migration(migrations.Migration):
    dependencies = [("surveyhq", "0007_survey_collection_mode")]

    operations = [
        migrations.AlterField(
            model_name="survey",
            name="collection_mode",
            field=models.CharField(
                blank=True,
                choices=[("anonymous", "Anonymous"), ("identifiable", "Identifiable")],
                default="anonymous",
                max_length=24,
                null=True,
            ),
        ),
        migrations.AlterModelOptions(
            name="survey",
            options={
                "ordering": ["-reporting_year", "-reporting_month", "title"],
                "permissions": [
                    ("access_surveyhq", "Can access SurveyHQ"),
                    ("publish_survey", "Can publish SurveyHQ surveys"),
                    ("close_survey", "Can close SurveyHQ surveys"),
                    ("reopen_survey", "Can reopen SurveyHQ surveys"),
                    ("archive_survey", "Can archive SurveyHQ surveys"),
                    ("duplicate_survey", "Can duplicate SurveyHQ surveys"),
                    ("delete_eligible_survey", "Can delete eligible draft SurveyHQ surveys"),
                    ("permanently_delete_survey", "Can permanently delete published SurveyHQ surveys"),
                    ("view_live_report", "Can view live SurveyHQ reports"),
                    ("export_survey_data", "Can export SurveyHQ data"),
                    ("generate_survey_report", "Can generate official SurveyHQ reports"),
                    ("rotate_survey_code", "Can rotate SurveyHQ survey codes"),
                    ("manage_participant_access", "Can manage SurveyHQ participant access resources"),
                    ("manage_survey_templates", "Can manage SurveyHQ templates"),
                    ("view_surveyhq_audit", "Can view SurveyHQ audit history"),
                ],
            },
        ),
        migrations.RunPython(grant_permanent_delete_permission, revoke_permanent_delete_permission),
    ]
