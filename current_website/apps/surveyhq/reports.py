from __future__ import annotations

import hashlib
import html
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image as PdfImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .analytics import build_survey_analytics
from .audit import record_survey_event
from .media import read_verified_question_image, require_durable_storage
from .models import Survey, SurveyQuestion, SurveyReportArtifact
from .permissions import require_permission


REPORT_PALETTES = {
    "miranda_navy_gold": {"label": "Miranda Insights Navy & Gold", "primary": "#07172d", "accent": "#b88420", "muted": "#e9edf2"},
    "neutral_professional": {"label": "Neutral Professional", "primary": "#263238", "accent": "#607d8b", "muted": "#eceff1"},
    "education": {"label": "Education", "primary": "#173b68", "accent": "#3d7f73", "muted": "#e7f0ee"},
    "high_contrast": {"label": "High Contrast", "primary": "#000000", "accent": "#005fcc", "muted": "#eeeeee"},
    "grayscale_print": {"label": "Grayscale / Print", "primary": "#111111", "accent": "#555555", "muted": "#e8e8e8"},
}


def _paragraph(value, style):
    return Paragraph(html.escape(str(value or "—")).replace("\n", "<br/>"), style)


def _table(rows, widths, palette, styles):
    data = [[_paragraph(value, styles["TableCell"]) for value in row] for row in rows]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(palette["primary"])),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#aab2ba")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#ffffff")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _bar_chart(question, palette):
    if question["kind"] == "matrix":
        return None
    rows = question.get("rows") or []
    if question["kind"] == "ranking":
        values = [row["first_choice_count"] for row in rows]
        labels = [row["label"] for row in rows]
    else:
        values = [row.get("count", 0) for row in rows]
        labels = [row.get("label", "") for row in rows]
    if not values or not any(values) or len(values) > 20:
        return None
    drawing = Drawing(470, max(125, 26 * len(values)))
    chart = HorizontalBarChart()
    chart.x = 145
    chart.y = 20
    chart.width = 295
    chart.height = max(80, 22 * len(values))
    chart.data = [values]
    chart.categoryAxis.categoryNames = [label[:32] for label in labels]
    chart.categoryAxis.labels.fontSize = 7
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueStep = max(1, int(max(values) / 5) or 1)
    chart.bars[0].fillColor = colors.HexColor(palette["accent"])
    chart.bars[0].strokeColor = colors.HexColor(palette["accent"])
    drawing.add(chart)
    return drawing


def _question_table(question, palette, styles):
    if question["kind"] == "matrix":
        rows = [["Matrix row", "Responses", "Missing", "Weighted mean", "Distribution"]]
        for row in question["matrix_rows"]:
            distribution = "; ".join(
                f"{item['label']}: {item['count']} ({item['percentage']}%)"
                for item in row["distribution"]
            )
            rows.append([row["label"], row["response_count"], row["missing_count"], row["weighted_mean"], distribution])
        return _table(rows, [1.15 * inch, .65 * inch, .65 * inch, .8 * inch, 3.15 * inch], palette, styles)
    if question["kind"] == "ranking":
        rows = [["Option", "Average rank", "First choice", "Rank distribution"]]
        for row in question["rows"]:
            distribution = "; ".join(f"{item['rank']}: {item['count']}" for item in row["distribution"])
            rows.append([row["label"], row["average_rank"], row["first_choice_count"], distribution])
        return _table(rows, [2 * inch, 1 * inch, 1 * inch, 2.4 * inch], palette, styles)
    rows = [["Value / option", "Count", "Percentage"]]
    rows.extend([[row["label"], row["count"], f"{row['percentage']}%"] for row in question.get("rows", [])])
    return _table(rows, [4.2 * inch, .8 * inch, 1.4 * inch], palette, styles)


def build_report_pdf(survey, analytics, *, palette_key, generated_at, response_cutoff_at):
    palette = REPORT_PALETTES[palette_key]
    primary = colors.HexColor(palette["primary"])
    accent = colors.HexColor(palette["accent"])
    base = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle("ReportTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=26, leading=30, textColor=primary, alignment=TA_CENTER, spaceAfter=18),
        "H1": ParagraphStyle("ReportH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=primary, spaceBefore=12, spaceAfter=10),
        "H2": ParagraphStyle("ReportH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=primary, spaceBefore=10, spaceAfter=7),
        "Body": ParagraphStyle("ReportBody", parent=base["BodyText"], fontSize=9.5, leading=14, textColor=colors.HexColor("#263238")),
        "Meta": ParagraphStyle("ReportMeta", parent=base["BodyText"], fontSize=8, leading=11, textColor=colors.HexColor("#5f6b76")),
        "TableCell": ParagraphStyle("ReportTable", parent=base["BodyText"], fontSize=7.5, leading=10),
    }
    output = BytesIO()

    def decorate(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(accent)
        canvas.line(document.leftMargin, .55 * inch, LETTER[0] - document.rightMargin, .55 * inch)
        canvas.setFillColor(primary)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(document.leftMargin, .35 * inch, "Miranda Insights · SurveyHQ analytical work product")
        canvas.drawRightString(LETTER[0] - document.rightMargin, .35 * inch, f"Page {document.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        output,
        pagesize=LETTER,
        rightMargin=.65 * inch,
        leftMargin=.65 * inch,
        topMargin=.65 * inch,
        bottomMargin=.75 * inch,
        title=survey.display_identity,
        author="Miranda Insights LLC",
        subject="SurveyHQ generated report",
    )
    story = []
    logo_path = settings.BASE_DIR / "static" / "img" / "miranda-logo.png"
    if logo_path.exists():
        logo = PdfImage(str(logo_path), width=1.15 * inch, height=1.15 * inch)
        logo.hAlign = "CENTER"
        story.extend([logo, Spacer(1, .22 * inch)])
    story.extend(
        [
            _paragraph("Miranda Insights Survey Report", styles["Title"]),
            _paragraph(survey.title, styles["H1"]),
            _paragraph(survey.identity_client_name, styles["Body"]),
            Spacer(1, .18 * inch),
            _table(
                [
                    ["Reporting period", "Collection period", "Generated", "Responses"],
                    [
                        f"{survey.reporting_month}/{survey.reporting_year}",
                        f"{analytics['survey']['starts_at_display']} – {analytics['survey']['closed_at_display']}",
                        timezone.localtime(generated_at).strftime("%b %d, %Y %I:%M %p"),
                        analytics["summary"]["total_responses"],
                    ],
                ],
                [1.25 * inch, 2.4 * inch, 1.7 * inch, 1 * inch],
                palette,
                styles,
            ),
            PageBreak(),
            _paragraph("Executive Survey Summary", styles["H1"]),
            _paragraph(
                f"This factual snapshot contains {analytics['summary']['total_responses']} submitted responses "
                f"across {len(analytics['questions'])} answerable questions. It includes descriptive statistics "
                "only and does not provide automated interpretation or causal findings.",
                styles["Body"],
            ),
        ]
    )
    questions = {
        str(question.pk): question
        for question in survey.questions.filter(pk__in=[item["id"] for item in analytics["questions"]])
    }
    for question in analytics["questions"]:
        block = [
            _paragraph(f"Question {question['number']} · {question['question_type_label']}", styles["H2"]),
            _paragraph(question["prompt"], styles["Body"]),
            _paragraph(
                f"Survey responses: {question['total_responses']} · Question responses: "
                f"{question['response_count']} · Missing/skipped: {question['missing_count']}",
                styles["Meta"],
            ),
        ]
        model_question = questions.get(question["id"])
        if model_question and model_question.image:
            try:
                image = PdfImage(BytesIO(read_verified_question_image(model_question)), width=3.2 * inch, height=2.2 * inch, kind="proportional")
                image.hAlign = "LEFT"
                block.append(image)
            except Exception:
                pass
        if question.get("statistics"):
            statistics = "; ".join(
                f"{key.replace('_', ' ').title()}: {value}"
                for key, value in question["statistics"].items()
                if value is not None
            )
            if statistics:
                block.append(_paragraph(statistics, styles["Meta"]))
        if question["kind"] != "text":
            chart = _bar_chart(question, palette)
            if chart:
                block.append(chart)
            block.append(_question_table(question, palette, styles))
        story.extend(block + [Spacer(1, .18 * inch)])

    text_questions = [question for question in analytics["questions"] if question["kind"] == "text"]
    if text_questions:
        story.extend([PageBreak(), _paragraph("Free-Text Appendix", styles["H1"])])
        for question in text_questions:
            story.append(_paragraph(f"Question {question['number']}: {question['prompt']}", styles["H2"]))
            for index, item in enumerate(question.get("text_responses", [])[:50], start=1):
                story.append(_paragraph(f"{index}. {item['value']}", styles["Body"]))
            if question.get("text_truncated"):
                story.append(_paragraph("Only the 50 most recent entries are shown. Protected CSV contains the complete retained data.", styles["Meta"]))

    story.extend(
        [
            PageBreak(),
            _paragraph("Report Metadata", styles["H1"]),
            _table(
                [
                    ["Generated", generated_at.isoformat()],
                    ["Response cutoff", response_cutoff_at.isoformat()],
                    ["Response count", analytics["summary"]["total_responses"]],
                    ["Definition checksum", survey.definition_checksum],
                    ["Palette", palette["label"]],
                ],
                [1.55 * inch, 4.85 * inch],
                palette,
                styles,
            ),
        ]
    )
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()


@transaction.atomic
def generate_survey_report(survey, *, actor, palette_key):
    require_permission(actor, "generate_survey_report")
    require_durable_storage()
    if palette_key not in REPORT_PALETTES:
        raise ValidationError("Select a supported SurveyHQ report palette.")
    instance = Survey.objects.select_for_update(of=("self",)).select_related("client", "project").get(
        pk=survey.pk if isinstance(survey, Survey) else survey
    )
    if not instance.published_at:
        raise ValidationError("Reports are available only for published surveys.")
    cutoff = timezone.now()
    analytics = build_survey_analytics(
        instance,
        include_text_values=True,
        at=cutoff,
        response_cutoff_at=cutoff,
    )
    response_count = analytics["summary"]["total_responses"]
    if response_count < 1:
        raise ValidationError("At least one submitted response is required to generate a report.")
    content = build_report_pdf(
        instance,
        analytics,
        palette_key=palette_key,
        generated_at=cutoff,
        response_cutoff_at=cutoff,
    )
    artifact = SurveyReportArtifact(
        survey=instance,
        palette_key=palette_key,
        response_count=response_count,
        response_cutoff_at=cutoff,
        definition_checksum=instance.definition_checksum,
        file_checksum=hashlib.sha256(content).hexdigest(),
        generated_by=actor,
    )
    filename = f"{instance.pk}-{artifact.pk}.pdf"
    artifact.file.save(filename, ContentFile(content), save=False)
    try:
        artifact.save()
        record_survey_event(
            survey=instance,
            actor=actor,
            event_type="survey_report_generated",
            summary=f"Generated an official report for {instance.display_identity}.",
            metadata={
                "artifact_id": str(artifact.pk),
                "palette": palette_key,
                "response_cutoff_at": cutoff.isoformat(),
                "response_count": response_count,
                "file_checksum": artifact.file_checksum,
            },
        )
    except Exception:
        artifact.file.storage.delete(artifact.file.name)
        raise
    return artifact
