from __future__ import annotations

import hashlib
from functools import wraps

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from landingpage.throttling import apply_retry_after, check_request_throttle

from .models import Survey, SurveyQuestion
from .media import read_verified_question_image
from .participant import (
    DuplicateParticipantSubmission,
    ParticipantAccessError,
    ParticipantSurveyForm,
    consume_participant_grant,
    get_participant_grant,
    has_completion_marker,
    issue_participant_grant,
    submit_participant_response,
    survey_accepts_new_grant,
    validate_granted_survey,
)
from .participant_access import participant_entry_token_is_active


GENERIC_UNAVAILABLE = "This survey is unavailable or the code is invalid. Please check the code provided by Miranda Insights."


def participant_security(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response["Cache-Control"] = "no-store, private, must-revalidate"
        response["Pragma"] = "no-cache"
        response["Referrer-Policy"] = "same-origin"
        return response

    return wrapped


def _unavailable(request, *, status=200, retry_after=0):
    response = render(
        request,
        "surveyhq/participant/entry.html",
        {"error": GENERIC_UNAVAILABLE, "survey_code": ""},
        status=status,
    )
    return apply_retry_after(response, retry_after)


@participant_security
@require_http_methods(["GET", "POST"])
def participant_entry_base(request):
    return HttpResponse("Not Found", status=404, content_type="text/plain")


@participant_security
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters()
@sensitive_variables()
def participant_entry(request, entry_token):
    if not participant_entry_token_is_active(entry_token):
        return HttpResponse("Not Found", status=404, content_type="text/plain")
    if request.method == "GET":
        return render(request, "surveyhq/participant/entry.html")

    code = request.POST.get("survey_code", "")
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    ip_result = check_request_throttle(
        request,
        "surveyhq-entry-ip",
        settings.SURVEYHQ_ENTRY_IP_RATE_LIMIT,
        pseudonymize_log_identity=True,
        include_request_path_in_log=False,
    )
    code_result = check_request_throttle(
        request,
        "surveyhq-entry-code",
        settings.SURVEYHQ_ENTRY_CODE_RATE_LIMIT,
        code_hash,
        pseudonymize_log_identity=True,
        include_request_path_in_log=False,
    )
    if ip_result.limited or code_result.limited:
        return _unavailable(
            request,
            status=429,
            retry_after=max(ip_result.retry_after, code_result.retry_after),
        )
    if len(code) != 6:
        return _unavailable(request)
    survey = Survey.objects.filter(access_code__exact=code).first()
    if not survey or not survey_accepts_new_grant(survey):
        return _unavailable(request)
    issue_participant_grant(request, survey)
    return redirect("surveyhq_participant:introduction")


@sensitive_variables()
def _granted_context(request):
    grant = get_participant_grant(request)
    survey = validate_granted_survey(grant)
    return grant, survey


@participant_security
@require_http_methods(["GET", "POST"])
@sensitive_variables()
def participant_introduction(request):
    try:
        _grant, survey = _granted_context(request)
    except ParticipantAccessError:
        return render(
            request,
            "surveyhq/participant/unavailable.html",
            {"message": "Participant access is unavailable."},
            status=410,
        )
    if request.method == "POST":
        return redirect("surveyhq_participant:survey")
    answerable_count = survey.questions.exclude(question_type__in=SurveyQuestion.STRUCTURAL_TYPES).count()
    return render(
        request,
        "surveyhq/participant/introduction.html",
        {"survey": survey, "answerable_count": answerable_count},
    )


@participant_security
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters()
@sensitive_variables()
def participant_survey(request):
    try:
        grant, survey = _granted_context(request)
    except ParticipantAccessError as exc:
        return render(
            request,
            "surveyhq/participant/unavailable.html",
            {"message": str(exc)},
            status=410,
        )
    form = ParticipantSurveyForm(request.POST or None, survey=survey)
    if request.method == "POST" and form.is_valid():
        try:
            submit_participant_response(grant=grant, form=form, request=request)
        except DuplicateParticipantSubmission:
            consume_participant_grant(request)
            return redirect("surveyhq_participant:thank_you")
        except ParticipantAccessError as exc:
            return render(
                request,
                "surveyhq/participant/unavailable.html",
                {"message": str(exc)},
                status=410,
            )
        consume_participant_grant(request)
        return redirect("surveyhq_participant:thank_you")
    return render(
        request,
        "surveyhq/participant/survey.html",
        {"survey": survey, "form": form, "pages": form.pages},
    )


@participant_security
@require_http_methods(["GET"])
@sensitive_variables()
def participant_question_image(request, question_id):
    try:
        grant, survey = _granted_context(request)
    except ParticipantAccessError as exc:
        raise Http404("Question image unavailable.") from exc
    question = SurveyQuestion.objects.filter(pk=question_id, survey=survey).first()
    if question is None:
        raise Http404("Question image unavailable.")
    try:
        content = read_verified_question_image(question)
    except ValidationError as exc:
        raise Http404("Question image unavailable.") from exc
    response = HttpResponse(content, content_type=question.image_content_type)
    response["X-Content-Type-Options"] = "nosniff"
    return response


@participant_security
@require_http_methods(["GET"])
def participant_thank_you(request):
    if not has_completion_marker(request):
        return HttpResponse("Not Found", status=404, content_type="text/plain")
    return render(request, "surveyhq/participant/thank_you.html")
