from django.db import migrations


APP_LABEL = "surveyhq"
MANAGERS_GROUP = "SurveyHQ Managers"
AUTHORS_GROUP = "SurveyHQ Authors"
ANALYSTS_GROUP = "SurveyHQ Analysts"

MODELS = {
    "survey": "survey",
    "surveyquestion": "survey question",
    "surveychoice": "survey choice",
    "surveymatrixrow": "survey matrix row",
    "surveyresponse": "survey response",
    "surveyanswer": "survey answer",
    "surveyanswerselection": "survey answer selection",
    "surveytemplate": "survey template",
    "surveyreportartifact": "survey report artifact",
    "surveyhqauditevent": "SurveyHQ audit event",
}

CUSTOM_PERMISSIONS = {
    "access_surveyhq": "Can access SurveyHQ",
    "publish_survey": "Can publish SurveyHQ surveys",
    "close_survey": "Can close SurveyHQ surveys",
    "reopen_survey": "Can reopen SurveyHQ surveys",
    "archive_survey": "Can archive SurveyHQ surveys",
    "duplicate_survey": "Can duplicate SurveyHQ surveys",
    "delete_eligible_survey": "Can delete eligible draft SurveyHQ surveys",
    "view_live_report": "Can view live SurveyHQ reports",
    "export_survey_data": "Can export SurveyHQ data",
    "generate_survey_report": "Can generate official SurveyHQ reports",
    "manage_survey_templates": "Can manage SurveyHQ templates",
    "view_surveyhq_audit": "Can view SurveyHQ audit history",
}


def seed_groups(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")

    permissions = {}
    for model_name, verbose_name in MODELS.items():
        content_type, _ = ContentType.objects.get_or_create(app_label=APP_LABEL, model=model_name)
        for action in ("add", "change", "delete", "view"):
            codename = f"{action}_{model_name}"
            permission, _ = Permission.objects.get_or_create(
                content_type=content_type,
                codename=codename,
                defaults={"name": f"Can {action} {verbose_name}"},
            )
            permissions[codename] = permission

    survey_content_type = ContentType.objects.get(app_label=APP_LABEL, model="survey")
    for codename, name in CUSTOM_PERMISSIONS.items():
        permission, _ = Permission.objects.get_or_create(
            content_type=survey_content_type,
            codename=codename,
            defaults={"name": name},
        )
        permissions[codename] = permission

    managers, _ = Group.objects.get_or_create(name=MANAGERS_GROUP)
    managers.permissions.set(Permission.objects.filter(content_type__app_label=APP_LABEL))

    authors, _ = Group.objects.get_or_create(name=AUTHORS_GROUP)
    author_codenames = {
        "access_surveyhq",
        "duplicate_survey",
        "add_survey",
        "change_survey",
        "view_survey",
        "add_surveyquestion",
        "change_surveyquestion",
        "delete_surveyquestion",
        "view_surveyquestion",
        "add_surveychoice",
        "change_surveychoice",
        "delete_surveychoice",
        "view_surveychoice",
        "add_surveymatrixrow",
        "change_surveymatrixrow",
        "delete_surveymatrixrow",
        "view_surveymatrixrow",
        "view_surveytemplate",
    }
    authors.permissions.set([permissions[codename] for codename in author_codenames])

    analysts, _ = Group.objects.get_or_create(name=ANALYSTS_GROUP)
    analyst_codenames = {
        "access_surveyhq",
        "view_live_report",
        "export_survey_data",
        "view_survey",
        "view_surveyquestion",
        "view_surveychoice",
        "view_surveymatrixrow",
        "view_surveyresponse",
        "view_surveyanswer",
        "view_surveyanswerselection",
        "view_surveyreportartifact",
    }
    analysts.permissions.set([permissions[codename] for codename in analyst_codenames])


def remove_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=[MANAGERS_GROUP, AUTHORS_GROUP, ANALYSTS_GROUP]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("surveyhq", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_groups, remove_groups),
    ]
