from django.core.exceptions import PermissionDenied


MANAGERS_GROUP = "SurveyHQ Managers"
AUTHORS_GROUP = "SurveyHQ Authors"
ANALYSTS_GROUP = "SurveyHQ Analysts"


def require_permission(actor, codename: str):
    if actor is None or not actor.is_authenticated or not actor.has_perm(f"surveyhq.{codename}"):
        raise PermissionDenied(f"The {codename} SurveyHQ permission is required.")
