from __future__ import annotations

from .models import Survey, SurveyHQAuditEvent, SurveyHQParticipantAccess, SurveyTemplate


def record_survey_event(*, survey: Survey, event_type: str, summary: str, actor=None, metadata=None):
    return SurveyHQAuditEvent.objects.create(
        entity_type=SurveyHQAuditEvent.EntityType.SURVEY,
        entity_id=survey.pk,
        survey=survey,
        event_type=event_type,
        actor=actor,
        display_identity=survey.display_identity,
        summary=summary,
        metadata=metadata or {},
    )


def record_template_event(
    *, template: SurveyTemplate, event_type: str, summary: str, actor=None, metadata=None
):
    return SurveyHQAuditEvent.objects.create(
        entity_type=SurveyHQAuditEvent.EntityType.TEMPLATE,
        entity_id=template.pk,
        template=template,
        event_type=event_type,
        actor=actor,
        display_identity=template.name,
        summary=summary,
        metadata=metadata or {},
    )


def record_participant_access_event(
    *, access: SurveyHQParticipantAccess, event_type: str, summary: str, actor=None, metadata=None
):
    return SurveyHQAuditEvent.objects.create(
        entity_type=SurveyHQAuditEvent.EntityType.PARTICIPANT_ACCESS,
        entity_id=access.pk,
        event_type=event_type,
        actor=actor,
        display_identity="SurveyHQ Participant Access",
        summary=summary,
        metadata=metadata or {},
    )
