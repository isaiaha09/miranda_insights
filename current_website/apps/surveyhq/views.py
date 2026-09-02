from __future__ import annotations

import csv
import hashlib
from calendar import month_name
from io import BytesIO
from uuid import UUID

import qrcode
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from apps.clients.models import Client, Project

from . import builder
from .analytics import build_survey_analytics
from .audit import record_survey_event
from .duplication import duplicate_survey
from .exports import long_csv_rows, wide_csv_rows
from .exceptions import SurveyHQError
from .forms import (
    ChoiceForm,
    ConfirmationForm,
    MatrixRowForm,
    QuestionForm,
    ReportGenerationForm,
    SurveyDuplicateForm,
    SurveyMetadataForm,
    TemplateMetadataForm,
)
from .lifecycle import (
    archive_survey,
    close_survey,
    create_draft,
    delete_eligible_draft,
    publish_survey,
    reopen_survey,
    rotate_access_code,
    update_draft_metadata,
)
from .media import mark_question_image_availability, read_verified_question_image
from .models import (
    Survey,
    SurveyAnswer,
    SurveyAnswerSelection,
    SurveyChoice,
    SurveyHQAuditEvent,
    SurveyMatrixRow,
    SurveyQuestion,
    SurveyResponse,
    SurveyReportArtifact,
    SurveyTemplate,
)
from .selectors import dashboard_counts, dashboard_surveys
from .reports import generate_survey_report
from .participant_access import (
    get_participant_access,
    participant_entry_path,
    rotate_participant_entry,
)
from .template_services import (
    archive_template,
    create_survey_from_template,
    create_template_from_survey,
    delete_eligible_template,
    duplicate_template,
    update_template_metadata,
)


def _require(request, codename):
    if not request.user.has_perm(f"surveyhq.{codename}"):
        raise PermissionDenied


def _context(request, title, **extra):
    request.current_app = admin.site.name
    return {**admin.site.each_context(request), "title": title, **extra}


def _error_text(exc):
    if isinstance(exc, ValidationError):
        return " ".join(exc.messages)
    return str(exc)


def _pagination_query(request):
    parameters = request.GET.copy()
    parameters.pop("page", None)
    encoded = parameters.urlencode()
    return f"{encoded}&" if encoded else ""


def _survey(survey_id):
    return get_object_or_404(
        Survey.objects.select_related("client", "project").prefetch_related("questions__choices", "questions__matrix_rows"),
        pk=survey_id,
    )


def _render_form(request, *, title, form, back_url, submit_label="Save", intro=""):
    return TemplateResponse(
        request,
        "admin/surveyhq/form.html",
        _context(
            request,
            title,
            form=form,
            back_url=back_url,
            submit_label=submit_label,
            intro=intro,
        ),
    )


def _confirmation(request, *, title, description, back_url, action_label, warning=""):
    return TemplateResponse(
        request,
        "admin/surveyhq/confirm.html",
        _context(
            request,
            title,
            description=description,
            warning=warning,
            back_url=back_url,
            action_label=action_label,
            form=ConfirmationForm(),
        ),
    )


def surveyhq_dashboard(request):
    _require(request, "access_surveyhq")
    page = Paginator(dashboard_surveys(request.GET), 25).get_page(request.GET.get("page"))
    context = _context(
        request,
        "SurveyHQ",
        subtitle="Survey management",
        counts=dashboard_counts(),
        survey_page=page,
        clients=Client.objects.order_by("organization_name", "contact_name"),
        years=Survey.objects.order_by("-reporting_year").values_list("reporting_year", flat=True).distinct(),
        months=[(number, month_name[number]) for number in range(1, 13)],
        categories=Survey.objects.exclude(category="").order_by("category").values_list("category", flat=True).distinct(),
        filters=request.GET,
        pagination_query=_pagination_query(request),
    )
    return TemplateResponse(request, "admin/surveyhq/dashboard.html", context)


def participant_access(request):
    _require(request, "manage_participant_access")
    access = get_participant_access()
    entry_url = request.build_absolute_uri(participant_entry_path(access))
    return TemplateResponse(
        request,
        "admin/surveyhq/participant_access.html",
        _context(request, "Participant Access", entry_url=entry_url, access=access),
    )


def participant_qr(request):
    _require(request, "manage_participant_access")
    entry_url = request.build_absolute_uri(participant_entry_path())
    qr = qrcode.QRCode(version=None, box_size=12, border=4)
    qr.add_data(entry_url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#07172d", back_color="#fffdf5")
    output = BytesIO()
    image.save(output, format="PNG")
    response = HttpResponse(output.getvalue(), content_type="image/png")
    response["Content-Disposition"] = 'attachment; filename="surveyhq-entry-qr.png"'
    response["Cache-Control"] = "private, no-store"
    return response


def participant_access_rotate(request):
    _require(request, "manage_participant_access")
    if request.method == "POST":
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            rotate_participant_entry(actor=request.user)
            messages.success(request, "The Participant Entry URL was rotated successfully.")
            return redirect("surveyhq:participant_access")
    return _confirmation(
        request,
        title="Rotate Participant Entry URL",
        description=(
            "Create a new generic SurveyHQ entry address without changing Survey Codes or "
            "active participant sessions."
        ),
        warning=(
            "Rotating the Participant Entry URL immediately invalidates the previous SurveyHQ "
            "entry link and QR. Survey Codes are not changed. Generate or distribute the new "
            "entry URL and QR after rotation."
        ),
        back_url=reverse("surveyhq:participant_access"),
        action_label="Rotate Entry URL",
    )


def response_list(request):
    _require(request, "view_surveyresponse")
    responses = SurveyResponse.objects.select_related("survey").order_by("-submitted_at")
    survey_id = (request.GET.get("survey") or "").strip()
    if survey_id:
        try:
            survey_uuid = UUID(survey_id)
        except ValueError:
            survey_id = ""
        else:
            responses = responses.filter(survey_id=survey_uuid)
    sort = request.GET.get("sort")
    if sort == "oldest":
        responses = responses.order_by("submitted_at")
    else:
        sort = "newest"
    date_from = parse_date(request.GET.get("date_from") or "")
    date_to = parse_date(request.GET.get("date_to") or "")
    if date_from:
        responses = responses.filter(submitted_at__date__gte=date_from)
    if date_to:
        responses = responses.filter(submitted_at__date__lte=date_to)
    page = Paginator(responses, 50).get_page(request.GET.get("page"))
    return TemplateResponse(
        request,
        "admin/surveyhq/response_list.html",
        _context(
            request,
            "SurveyHQ Responses",
            response_page=page,
            surveys=Survey.objects.order_by("-reporting_year", "-reporting_month", "title"),
            selected_survey=survey_id or "",
            selected_sort=sort,
            selected_date_from=date_from.isoformat() if date_from else "",
            selected_date_to=date_to.isoformat() if date_to else "",
            pagination_query=_pagination_query(request),
        ),
    )


def _answer_display(answer):
    selections = list(answer.selections.all())
    if selections:
        if any(selection.rank is not None for selection in selections):
            return "; ".join(
                f"{selection.rank}. {selection.choice.label}"
                for selection in sorted(selections, key=lambda item: item.rank or 0)
            )
        return "; ".join(selection.choice.label for selection in selections)
    if answer.text_value:
        return answer.text_value
    if answer.numeric_value is not None:
        return str(answer.numeric_value.normalize())
    if answer.date_value is not None:
        return answer.date_value.isoformat()
    return "—"


def response_detail(request, response_id):
    _require(request, "view_surveyresponse")
    response = get_object_or_404(SurveyResponse.objects.select_related("survey"), pk=response_id)
    answers = SurveyAnswer.objects.filter(response=response).select_related(
        "question", "matrix_row"
    ).prefetch_related(
        Prefetch(
            "selections",
            queryset=SurveyAnswerSelection.objects.select_related("choice").order_by(
                "rank", "choice__position"
            ),
        )
    ).order_by(
        "question__position", "matrix_row__position", "id"
    )
    answer_rows = [
        {
            "question": answer.question.prompt,
            "question_key": answer.question.export_key,
            "matrix_row": answer.matrix_row.label if answer.matrix_row else "",
            "value": _answer_display(answer),
        }
        for answer in answers
    ]
    return TemplateResponse(
        request,
        "admin/surveyhq/response_detail.html",
        _context(request, f"Response {response.pk}", response=response, answer_rows=answer_rows),
    )


def survey_analytics(request, survey_id):
    _require(request, "view_live_report")
    survey = _survey(survey_id)
    analytics = build_survey_analytics(survey, include_text_values=True)
    return TemplateResponse(
        request,
        "admin/surveyhq/analytics.html",
        _context(request, f"Analytics · {survey.display_identity}", survey=survey, analytics=analytics),
    )


@require_GET
def survey_analytics_data(request, survey_id):
    _require(request, "view_live_report")
    survey = _survey(survey_id)
    response = JsonResponse({"analytics": build_survey_analytics(survey, include_text_values=False)})
    response["Cache-Control"] = "private, no-store"
    return response


class _CsvEcho:
    def write(self, value):
        return value


def _survey_csv_export(request, survey_id, *, export_format):
    _require(request, "export_survey_data")
    survey = _survey(survey_id)
    if not survey.published_at:
        raise Http404("Exports are available only for published surveys.")
    cutoff = timezone.now()
    response_count = survey.responses.filter(submitted_at__lte=cutoff).count()
    rows = wide_csv_rows(survey, cutoff) if export_format == "responses" else long_csv_rows(survey, cutoff)
    writer = csv.writer(_CsvEcho(), lineterminator="\r\n")

    def stream():
        yield "\ufeff"
        for row in rows:
            yield writer.writerow(row)

    record_survey_event(
        survey=survey,
        actor=request.user,
        event_type="survey_data_exported",
        summary=f"Downloaded {export_format} CSV for {survey.display_identity}.",
        metadata={
            "format": export_format,
            "response_cutoff_at": cutoff.isoformat(),
            "response_count": response_count,
        },
    )
    safe_title = slugify(survey.title)[:60] or "survey"
    filename = f"{safe_title}-{survey.pk}-{export_format}-{cutoff.date().isoformat()}.csv"
    response = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def survey_responses_csv(request, survey_id):
    return _survey_csv_export(request, survey_id, export_format="responses")


@require_GET
def survey_analytical_csv(request, survey_id):
    return _survey_csv_export(request, survey_id, export_format="analytical")


def project_options(request):
    if not (
        request.user.has_perm("surveyhq.add_survey") or request.user.has_perm("surveyhq.change_survey")
    ):
        raise PermissionDenied
    client_id = request.GET.get("client")
    projects = Project.objects.none()
    if client_id:
        projects = Project.objects.filter(client_id=client_id).order_by("name")
    return JsonResponse({"projects": [{"id": project.pk, "label": project.name} for project in projects]})


def survey_create(request):
    _require(request, "add_survey")
    form = SurveyMetadataForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        try:
            survey = create_draft(actor=request.user, **form.service_values())
        except (ValidationError, SurveyHQError) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, f"Created {survey.display_identity}.")
            return redirect("surveyhq:survey_builder", survey_id=survey.pk)
    return _render_form(
        request,
        title="Create Survey",
        form=form,
        back_url=reverse("surveyhq:dashboard"),
        submit_label="Create Draft",
        intro="Create the survey metadata first. The survey remains Draft until a Manager publishes it.",
    )


def survey_detail(request, survey_id):
    _require(request, "view_survey")
    survey = _survey(survey_id)
    return TemplateResponse(
        request,
        "admin/surveyhq/survey_detail.html",
        _context(
            request,
            survey.display_identity,
            survey=survey,
            response_count=survey.responses.count(),
            report_artifacts=survey.report_artifacts.select_related("generated_by").all(),
        ),
    )


def survey_report_generate(request, survey_id):
    _require(request, "generate_survey_report")
    survey = _survey(survey_id)
    form = ReportGenerationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            artifact = generate_survey_report(
                survey,
                actor=request.user,
                palette_key=form.cleaned_data["palette"],
            )
        except (ValidationError, SurveyHQError) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(
                request,
                f"Generated official report with {artifact.response_count} responses.",
            )
            return redirect("surveyhq:survey_detail", survey_id=survey.pk)
    return TemplateResponse(
        request,
        "admin/surveyhq/report_generate.html",
        _context(request, f"Generate Report · {survey.display_identity}", survey=survey, form=form),
    )


@require_GET
def survey_report_download(request, artifact_id):
    _require(request, "view_surveyreportartifact")
    artifact = get_object_or_404(
        SurveyReportArtifact.objects.select_related("survey", "generated_by"), pk=artifact_id
    )
    try:
        with artifact.file.open("rb") as stored_file:
            content = stored_file.read()
    except (FileNotFoundError, OSError):
        raise Http404("The retained report file is unavailable.")
    if hashlib.sha256(content).hexdigest() != artifact.file_checksum:
        raise Http404("The retained report file could not be verified.")
    record_survey_event(
        survey=artifact.survey,
        actor=request.user,
        event_type="survey_report_downloaded",
        summary=f"Downloaded an official report for {artifact.survey.display_identity}.",
        metadata={"artifact_id": str(artifact.pk), "file_checksum": artifact.file_checksum},
    )
    safe_title = slugify(artifact.survey.title)[:60] or "survey"
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{safe_title}-{artifact.pk}-official-report.pdf"'
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def survey_edit(request, survey_id):
    _require(request, "change_survey")
    survey = _survey(survey_id)
    if survey.is_structure_locked:
        messages.error(request, "Published survey metadata is read-only; duplicate it into a new Draft.")
        return redirect("surveyhq:survey_detail", survey_id=survey.pk)
    form = SurveyMetadataForm(request.POST or None, request=request, survey=survey)
    if request.method == "POST" and form.is_valid():
        try:
            survey = update_draft_metadata(survey, actor=request.user, **form.service_values())
        except (ValidationError, SurveyHQError) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, "Survey information updated.")
            return redirect("surveyhq:survey_builder", survey_id=survey.pk)
    return _render_form(
        request,
        title=f"Edit · {survey.display_identity}",
        form=form,
        back_url=reverse("surveyhq:survey_builder", args=[survey.pk]),
        submit_label="Save Survey Information",
    )


def survey_builder(request, survey_id):
    _require(request, "change_survey")
    survey = _survey(survey_id)
    if survey.is_structure_locked:
        messages.info(request, "Published survey structure is read-only.")
        return redirect("surveyhq:survey_detail", survey_id=survey.pk)
    mark_question_image_availability(survey.questions.all())
    return TemplateResponse(
        request,
        "admin/surveyhq/builder.html",
        _context(request, f"Builder · {survey.display_identity}", survey=survey),
    )


def survey_preview(request, survey_id):
    _require(request, "view_survey")
    survey = _survey(survey_id)
    mark_question_image_availability(survey.questions.all())
    before = survey.responses.count()
    response = TemplateResponse(
        request,
        "admin/surveyhq/preview.html",
        _context(request, f"Preview · {survey.display_identity}", survey=survey),
    )
    response["X-SurveyHQ-Preview"] = "true"
    if survey.responses.count() != before:  # pragma: no cover - defensive invariant
        raise RuntimeError("Survey preview must never create responses.")
    return response


def question_image(request, question_id):
    _require(request, "view_survey")
    question = get_object_or_404(SurveyQuestion, pk=question_id)
    try:
        content = read_verified_question_image(question)
    except ValidationError as exc:
        raise Http404("Question image unavailable.") from exc
    response = HttpResponse(content, content_type=question.image_content_type)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def question_create(request, survey_id):
    _require(request, "add_surveyquestion")
    survey = _survey(survey_id)
    if survey.is_structure_locked:
        raise PermissionDenied
    form = QuestionForm(request.POST or None, request.FILES or None, survey=survey)
    if request.method == "POST" and form.is_valid():
        try:
            question = builder.create_question(
                survey=survey,
                actor=request.user,
                question_type=form.cleaned_data["question_type"],
                prompt=form.cleaned_data["prompt"],
                help_text=form.cleaned_data["help_text"],
                required=form.cleaned_data["required"],
                configuration=form.cleaned_data["configuration"],
                preset=form.cleaned_data.get("likert_preset", ""),
                prepared_image=form.cleaned_data.get("prepared_image"),
                image_alt_text=form.cleaned_data.get("image_alt_text", ""),
                image_is_decorative=form.cleaned_data.get("image_is_decorative", False),
            )
        except (ValidationError, SurveyHQError) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, f"Added {question.get_question_type_display()} question.")
            return redirect("surveyhq:question_edit", question_id=question.pk)
    return TemplateResponse(
        request,
        "admin/surveyhq/question_form.html",
        _context(request, "Add Question", survey=survey, form=form, question=None),
    )


def question_edit(request, question_id):
    _require(request, "change_surveyquestion")
    question = get_object_or_404(
        SurveyQuestion.objects.select_related("survey").prefetch_related("choices", "matrix_rows"), pk=question_id
    )
    if question.survey.is_structure_locked:
        raise PermissionDenied
    mark_question_image_availability([question])
    form = QuestionForm(request.POST or None, request.FILES or None, question=question)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                question = builder.update_question(
                    question=question,
                    actor=request.user,
                    prompt=form.cleaned_data["prompt"],
                    help_text=form.cleaned_data["help_text"],
                    required=form.cleaned_data["required"],
                    configuration=form.cleaned_data["configuration"],
                    prepared_image=form.cleaned_data.get("prepared_image"),
                    remove_image=form.cleaned_data.get("remove_image", False),
                    image_alt_text=form.cleaned_data.get("image_alt_text", ""),
                    image_is_decorative=form.cleaned_data.get("image_is_decorative", False),
                )
                preset = form.cleaned_data.get("likert_preset")
                if preset:
                    builder.apply_likert_preset(question, actor=request.user, preset=preset)
        except (ValidationError, SurveyHQError) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, "Question updated.")
            return redirect("surveyhq:question_edit", question_id=question.pk)
    return TemplateResponse(
        request,
        "admin/surveyhq/question_form.html",
        _context(request, f"Edit {question.export_key}", survey=question.survey, question=question, form=form),
    )


@require_POST
def question_duplicate(request, question_id):
    question = get_object_or_404(SurveyQuestion, pk=question_id)
    duplicate = builder.duplicate_question(question, actor=request.user)
    messages.success(request, f"Duplicated question as {duplicate.export_key}.")
    return redirect("surveyhq:survey_builder", survey_id=duplicate.survey_id)


@require_POST
def question_delete(request, question_id):
    question = get_object_or_404(SurveyQuestion.objects.select_related("survey"), pk=question_id)
    survey_id = question.survey_id
    builder.delete_question(question, actor=request.user)
    messages.success(request, "Question deleted.")
    return redirect("surveyhq:survey_builder", survey_id=survey_id)


@require_POST
def question_move(request, question_id, direction):
    question = get_object_or_404(SurveyQuestion.objects.select_related("survey"), pk=question_id)
    builder.move_question(question, actor=request.user, direction=direction)
    messages.success(request, "Question order updated.")
    return redirect("surveyhq:survey_builder", survey_id=question.survey_id)


def choice_create(request, question_id):
    question = get_object_or_404(SurveyQuestion.objects.select_related("survey"), pk=question_id)
    _require(request, "add_surveychoice")
    form = ChoiceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            builder.add_choice(question=question, actor=request.user, **form.cleaned_data)
        except (ValidationError, SurveyHQError, PermissionDenied) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, "Option added.")
            return redirect("surveyhq:question_edit", question_id=question.pk)
    return _render_form(
        request,
        title="Add Option",
        form=form,
        back_url=reverse("surveyhq:question_edit", args=[question.pk]),
        submit_label="Add Option",
    )


def choice_edit(request, choice_id):
    choice = get_object_or_404(SurveyChoice.objects.select_related("question__survey"), pk=choice_id)
    _require(request, "change_surveychoice")
    form = ChoiceForm(request.POST or None, choice=choice)
    if request.method == "POST" and form.is_valid():
        try:
            builder.update_choice(choice=choice, actor=request.user, **form.cleaned_data)
        except (ValidationError, SurveyHQError, PermissionDenied) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, "Option updated.")
            return redirect("surveyhq:question_edit", question_id=choice.question_id)
    return _render_form(
        request,
        title="Edit Option",
        form=form,
        back_url=reverse("surveyhq:question_edit", args=[choice.question_id]),
    )


@require_POST
def choice_delete(request, choice_id):
    choice = get_object_or_404(SurveyChoice.objects.select_related("question"), pk=choice_id)
    question_id = choice.question_id
    builder.delete_choice(choice, actor=request.user)
    messages.success(request, "Option deleted.")
    return redirect("surveyhq:question_edit", question_id=question_id)


@require_POST
def choice_move(request, choice_id, direction):
    choice = get_object_or_404(SurveyChoice.objects.select_related("question"), pk=choice_id)
    builder.move_choice(choice, actor=request.user, direction=direction)
    messages.success(request, "Option order updated.")
    return redirect("surveyhq:question_edit", question_id=choice.question_id)


def matrix_row_create(request, question_id):
    question = get_object_or_404(SurveyQuestion.objects.select_related("survey"), pk=question_id)
    _require(request, "add_surveymatrixrow")
    form = MatrixRowForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            builder.add_matrix_row(question=question, actor=request.user, **form.cleaned_data)
        except (ValidationError, SurveyHQError) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, "Matrix row added.")
            return redirect("surveyhq:question_edit", question_id=question.pk)
    return _render_form(
        request,
        title="Add Matrix Row",
        form=form,
        back_url=reverse("surveyhq:question_edit", args=[question.pk]),
        submit_label="Add Row",
    )


def matrix_row_edit(request, row_id):
    row = get_object_or_404(SurveyMatrixRow.objects.select_related("question__survey"), pk=row_id)
    _require(request, "change_surveymatrixrow")
    form = MatrixRowForm(request.POST or None, row=row)
    if request.method == "POST" and form.is_valid():
        builder.update_matrix_row(row=row, actor=request.user, **form.cleaned_data)
        messages.success(request, "Matrix row updated.")
        return redirect("surveyhq:question_edit", question_id=row.question_id)
    return _render_form(
        request,
        title="Edit Matrix Row",
        form=form,
        back_url=reverse("surveyhq:question_edit", args=[row.question_id]),
    )


@require_POST
def matrix_row_delete(request, row_id):
    row = get_object_or_404(SurveyMatrixRow.objects.select_related("question"), pk=row_id)
    question_id = row.question_id
    builder.delete_matrix_row(row, actor=request.user)
    messages.success(request, "Matrix row deleted.")
    return redirect("surveyhq:question_edit", question_id=question_id)


@require_POST
def matrix_row_move(request, row_id, direction):
    row = get_object_or_404(SurveyMatrixRow.objects.select_related("question"), pk=row_id)
    builder.move_matrix_row(row, actor=request.user, direction=direction)
    messages.success(request, "Matrix row order updated.")
    return redirect("surveyhq:question_edit", question_id=row.question_id)


def survey_publish(request, survey_id):
    _require(request, "publish_survey")
    survey = _survey(survey_id)
    if request.method == "POST":
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            try:
                survey = publish_survey(survey, actor=request.user)
            except (ValidationError, SurveyHQError) as exc:
                messages.error(request, _error_text(exc))
                return redirect("surveyhq:survey_builder", survey_id=survey.pk)
            messages.success(request, f"Published {survey.display_identity}.")
            return redirect("surveyhq:survey_detail", survey_id=survey.pk)
    return _confirmation(
        request,
        title="Publish Survey",
        description="Publishing locks questions, choices, stable keys, matrix rows, and analytical configuration.",
        warning="Structural changes after publication require duplication into a new Draft. Availability determines whether the survey opens immediately or becomes Scheduled.",
        back_url=reverse("surveyhq:survey_builder", args=[survey.pk]),
        action_label="Publish Survey",
    )


def survey_duplicate(request, survey_id):
    _require(request, "duplicate_survey")
    source = _survey(survey_id)
    form = SurveyDuplicateForm(request.POST or None, request=request, source=source)
    if request.method == "POST" and form.is_valid():
        values = form.cleaned_data
        try:
            duplicate = duplicate_survey(
                source,
                actor=request.user,
                title=values["title"],
                copy_client=values["copy_client"],
                target_client=None if values["copy_client"] else values["client"],
                copy_project=values["copy_project"],
                target_project=None if values["copy_project"] else values["project"],
                copy_reporting_period=values["copy_reporting_period"],
                reporting_month=values["reporting_month"],
                reporting_year=values["reporting_year"],
                copy_schedule=values["copy_availability"],
                collection_mode=values["collection_mode"],
            )
        except (ValidationError, SurveyHQError) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, f"Created duplicate {duplicate.display_identity}.")
            return redirect("surveyhq:survey_builder", survey_id=duplicate.pk)
    return _render_form(
        request,
        title="Duplicate Survey",
        form=form,
        back_url=reverse("surveyhq:survey_detail", args=[source.pk]),
        submit_label="Create Draft Duplicate",
    )


def _lifecycle_confirmation(request, survey, *, permission, service, title, description, warning, label, kwargs=None):
    _require(request, permission)
    if request.method == "POST":
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            try:
                result = service(survey, actor=request.user, **(kwargs or {}))
            except (ValidationError, SurveyHQError) as exc:
                messages.error(request, _error_text(exc))
            else:
                messages.success(request, f"{title} completed for {result.display_identity}.")
            return redirect("surveyhq:survey_detail", survey_id=survey.pk)
    return _confirmation(
        request,
        title=title,
        description=description,
        warning=warning,
        back_url=reverse("surveyhq:survey_detail", args=[survey.pk]),
        action_label=label,
    )


def survey_close(request, survey_id):
    return _lifecycle_confirmation(
        request,
        _survey(survey_id),
        permission="close_survey",
        service=close_survey,
        title="Close Survey",
        description="Stop new participant access when Phase 3 is enabled.",
        warning="Already-issued participant sessions will follow the approved closing grace policy in Phase 3.",
        label="Close Survey",
    )


def survey_reopen(request, survey_id):
    return _lifecycle_confirmation(
        request,
        _survey(survey_id),
        permission="reopen_survey",
        service=reopen_survey,
        title="Reopen Survey",
        description="Reopening continues collecting responses into the existing survey dataset.",
        warning="For a new measurement period, duplicate this survey instead.",
        label="Exceptionally Reopen Survey",
        kwargs={"confirmation": True, "clear_expired_end": True},
    )


def survey_archive(request, survey_id):
    return _lifecycle_confirmation(
        request,
        _survey(survey_id),
        permission="archive_survey",
        service=archive_survey,
        title="Archive Survey",
        description="Archive this closed survey while preserving its complete historical record.",
        warning="Archiving is not deletion.",
        label="Archive Survey",
    )


def survey_rotate_code(request, survey_id):
    return _lifecycle_confirmation(
        request,
        _survey(survey_id),
        permission="rotate_survey_code",
        service=rotate_access_code,
        title="Rotate Survey Code",
        description="Generate a new six-character participant code.",
        warning="The previous code stops working immediately. The generic QR will never contain this code.",
        label="Rotate Code",
    )


def survey_delete(request, survey_id):
    _require(request, "delete_eligible_survey")
    survey = _survey(survey_id)
    if request.method == "POST":
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            try:
                delete_eligible_draft(survey, actor=request.user)
            except (ValidationError, SurveyHQError) as exc:
                messages.error(request, _error_text(exc))
                return redirect("surveyhq:survey_detail", survey_id=survey.pk)
            messages.success(request, "Draft survey permanently deleted.")
            return redirect("surveyhq:dashboard")
    return _confirmation(
        request,
        title="Delete Draft Survey",
        description=f"Permanently delete {survey.display_identity}.",
        warning="This action cannot be undone. Published surveys cannot be deleted.",
        back_url=reverse("surveyhq:survey_detail", args=[survey.pk]),
        action_label="Permanently Delete Draft",
    )


def survey_audit(request, survey_id):
    _require(request, "view_surveyhq_audit")
    survey = _survey(survey_id)
    page = Paginator(survey.audit_events.select_related("actor"), 50).get_page(request.GET.get("page"))
    return TemplateResponse(
        request,
        "admin/surveyhq/audit.html",
        _context(request, f"Audit · {survey.display_identity}", event_page=page, survey=survey),
    )


def audit_log(request):
    _require(request, "view_surveyhq_audit")
    events = SurveyHQAuditEvent.objects.select_related("actor", "survey", "template")
    event_type = (request.GET.get("event") or "").strip()
    entity_type = (request.GET.get("entity") or "").strip()
    if event_type:
        events = events.filter(event_type=event_type)
    if entity_type:
        events = events.filter(entity_type=entity_type)
    page = Paginator(events, 50).get_page(request.GET.get("page"))
    return TemplateResponse(
        request,
        "admin/surveyhq/audit.html",
        _context(
            request,
            "SurveyHQ Audit Log",
            event_page=page,
            event_types=SurveyHQAuditEvent.objects.order_by("event_type").values_list("event_type", flat=True).distinct(),
            entity_types=SurveyHQAuditEvent.EntityType.choices,
            selected_event=event_type,
            selected_entity=entity_type,
            pagination_query=_pagination_query(request),
        ),
    )


def template_list(request):
    _require(request, "view_surveytemplate")
    templates = SurveyTemplate.objects.select_related("source_survey").order_by("status", "name")
    return TemplateResponse(
        request,
        "admin/surveyhq/template_list.html",
        _context(request, "SurveyHQ Templates", templates=templates),
    )


def template_detail(request, template_id):
    _require(request, "view_surveytemplate")
    template = get_object_or_404(SurveyTemplate.objects.select_related("source_survey"), pk=template_id)
    return TemplateResponse(
        request,
        "admin/surveyhq/template_detail.html",
        _context(request, template.name, template=template, questions=template.definition.get("questions", [])),
    )


def template_from_survey(request, survey_id):
    _require(request, "manage_survey_templates")
    survey = _survey(survey_id)
    form = TemplateMetadataForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            template = create_template_from_survey(survey=survey, actor=request.user, **form.cleaned_data)
        except (ValidationError, SurveyHQError) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, f"Created template {template.name}.")
            return redirect("surveyhq:template_detail", template_id=template.pk)
    return _render_form(
        request,
        title="Save Survey as Template",
        form=form,
        back_url=reverse("surveyhq:survey_detail", args=[survey.pk]),
        submit_label="Save Template",
    )


def template_edit(request, template_id):
    _require(request, "manage_survey_templates")
    template = get_object_or_404(SurveyTemplate, pk=template_id)
    form = TemplateMetadataForm(request.POST or None, template=template)
    if request.method == "POST" and form.is_valid():
        try:
            template = update_template_metadata(template, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, f"Updated template {template.name}.")
            return redirect("surveyhq:template_detail", template_id=template.pk)
    return _render_form(
        request,
        title="Edit Template",
        form=form,
        back_url=reverse("surveyhq:template_detail", args=[template.pk]),
    )


def template_duplicate(request, template_id):
    _require(request, "manage_survey_templates")
    template = get_object_or_404(SurveyTemplate, pk=template_id)
    form = TemplateMetadataForm(request.POST or None, initial={"name": f"{template.name} Copy"})
    if request.method == "POST" and form.is_valid():
        try:
            duplicate = duplicate_template(template, actor=request.user, name=form.cleaned_data["name"])
        except ValidationError as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, f"Duplicated template as {duplicate.name}.")
            return redirect("surveyhq:template_detail", template_id=duplicate.pk)
    return _render_form(
        request,
        title="Duplicate Template",
        form=form,
        back_url=reverse("surveyhq:template_detail", args=[template.pk]),
        submit_label="Duplicate Template",
    )


def template_archive(request, template_id):
    _require(request, "manage_survey_templates")
    template = get_object_or_404(SurveyTemplate, pk=template_id)
    if request.method == "POST" and ConfirmationForm(request.POST).is_valid():
        archive_template(template, actor=request.user)
        messages.success(request, f"Archived template {template.name}.")
        return redirect("surveyhq:template_detail", template_id=template.pk)
    return _confirmation(
        request,
        title="Archive Template",
        description=f"Archive {template.name} while preserving its history.",
        warning="Archived templates cannot create new surveys.",
        back_url=reverse("surveyhq:template_detail", args=[template.pk]),
        action_label="Archive Template",
    )


def template_delete(request, template_id):
    _require(request, "manage_survey_templates")
    template = get_object_or_404(SurveyTemplate, pk=template_id)
    if request.method == "POST" and ConfirmationForm(request.POST).is_valid():
        try:
            delete_eligible_template(template, actor=request.user)
        except ValidationError as exc:
            messages.error(request, _error_text(exc))
            return redirect("surveyhq:template_detail", template_id=template.pk)
        messages.success(request, f"Deleted template {template.name}.")
        return redirect("surveyhq:template_list")
    return _confirmation(
        request,
        title="Delete Template",
        description=f"Permanently delete unused template {template.name}.",
        warning="Templates already used by surveys must be archived instead.",
        back_url=reverse("surveyhq:template_detail", args=[template.pk]),
        action_label="Permanently Delete Template",
    )


def survey_from_template(request, template_id):
    _require(request, "view_surveytemplate")
    _require(request, "add_survey")
    template = get_object_or_404(SurveyTemplate, pk=template_id, status=SurveyTemplate.Status.ACTIVE)
    form = SurveyMetadataForm(request.POST or None, request=request, initial={"category": template.category})
    if request.method == "POST" and form.is_valid():
        try:
            survey = create_survey_from_template(template=template, actor=request.user, **form.service_values())
        except (ValidationError, SurveyHQError) as exc:
            form.add_error(None, _error_text(exc))
        else:
            messages.success(request, f"Created {survey.display_identity} from {template.name}.")
            return redirect("surveyhq:survey_builder", survey_id=survey.pk)
    return _render_form(
        request,
        title=f"Create Survey from {template.name}",
        form=form,
        back_url=reverse("surveyhq:template_detail", args=[template.pk]),
        submit_label="Create Draft from Template",
    )
