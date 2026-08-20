from __future__ import annotations

import secrets

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from .audit import record_participant_access_event
from .models import SurveyHQParticipantAccess, generate_participant_entry_token
from .permissions import require_permission


def get_participant_access():
    try:
        return SurveyHQParticipantAccess.objects.get(
            singleton_key=SurveyHQParticipantAccess.SINGLETON_KEY
        )
    except SurveyHQParticipantAccess.DoesNotExist:
        try:
            return SurveyHQParticipantAccess.objects.create()
        except IntegrityError:
            return SurveyHQParticipantAccess.objects.get(
                singleton_key=SurveyHQParticipantAccess.SINGLETON_KEY
            )


def participant_entry_path(access=None):
    access = access or get_participant_access()
    return reverse(
        "surveyhq_participant:entry",
        kwargs={"entry_token": access.active_entry_token},
    )


def participant_entry_token_is_active(candidate):
    if not candidate:
        return False
    access = get_participant_access()
    return secrets.compare_digest(candidate, access.active_entry_token)


@transaction.atomic
def rotate_participant_entry(*, actor):
    require_permission(actor, "manage_participant_access")
    access = SurveyHQParticipantAccess.objects.select_for_update().get(
        singleton_key=SurveyHQParticipantAccess.SINGLETON_KEY
    )
    previous_token = access.active_entry_token
    for _attempt in range(20):
        token = generate_participant_entry_token()
        if token != previous_token and not SurveyHQParticipantAccess.objects.filter(
            active_entry_token=token
        ).exists():
            break
    else:  # pragma: no cover - cryptographically implausible
        raise RuntimeError("Unable to generate a distinct participant-entry token.")
    access.active_entry_token = token
    access.rotated_at = timezone.now()
    access.rotated_by = actor
    access.save(update_fields=["active_entry_token", "rotated_at", "rotated_by"])
    record_participant_access_event(
        access=access,
        actor=actor,
        event_type="participant_entry_rotated",
        summary="Rotated the SurveyHQ Participant Entry URL.",
        metadata={"configuration_id": str(access.pk)},
    )
    return access
