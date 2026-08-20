from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_DIMENSION = 6000
MAX_IMAGE_PIXELS = 36_000_000
FORMAT_DETAILS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}
EXTENSIONS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}


@dataclass(frozen=True)
class PreparedQuestionImage:
    content: bytes
    filename: str
    original_name: str
    content_type: str
    checksum: str
    byte_size: int
    width: int
    height: int


def require_durable_storage():
    if not settings.DEBUG and not settings.SURVEYHQ_DURABLE_STORAGE_READY:
        raise ValidationError(
            "SurveyHQ durable storage is not configured. Attach persistent storage and set "
            "SURVEYHQ_DURABLE_STORAGE_READY before uploading images or generating reports."
        )


def prepare_question_image(upload) -> PreparedQuestionImage:
    require_durable_storage()
    original_name = os.path.basename(upload.name or "question-image")[:255]
    extension = os.path.splitext(original_name)[1].lower()
    expected_format = EXTENSIONS.get(extension)
    if expected_format is None:
        raise ValidationError("Question images must be JPEG, PNG, or static WebP files.")
    if getattr(upload, "size", 0) > MAX_IMAGE_BYTES:
        raise ValidationError("Question images must not exceed 8 MB.")
    raw = upload.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValidationError("Question images must not exceed 8 MB.")
    try:
        with Image.open(BytesIO(raw)) as source:
            source.load()
            actual_format = source.format
            if actual_format != expected_format or actual_format not in FORMAT_DETAILS:
                raise ValidationError("The file extension does not match the uploaded image content.")
            if getattr(source, "is_animated", False) or getattr(source, "n_frames", 1) != 1:
                raise ValidationError("Animated question images are not supported.")
            image = ImageOps.exif_transpose(source).copy()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("Upload a valid, non-corrupt JPEG, PNG, or static WebP image.") from exc

    width, height = image.size
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
        raise ValidationError("Question images must be no larger than 6,000×6,000 pixels or 36 megapixels.")

    content_type, normalized_extension = FORMAT_DETAILS[actual_format]
    output = BytesIO()
    if actual_format == "JPEG":
        image.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
    elif actual_format == "PNG":
        image.save(output, format="PNG", optimize=True)
    else:
        image.save(output, format="WEBP", quality=92, method=6)
    content = output.getvalue()
    if len(content) > MAX_IMAGE_BYTES:
        raise ValidationError("The normalized question image exceeds 8 MB.")
    safe_stem = os.path.splitext(original_name)[0] or "question-image"
    return PreparedQuestionImage(
        content=content,
        filename=f"{safe_stem}{normalized_extension}",
        original_name=original_name,
        content_type=content_type,
        checksum=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        width=width,
        height=height,
    )


def assign_question_image(question, prepared, *, alt_text="", decorative=False):
    question.image.save(prepared.filename, ContentFile(prepared.content), save=False)
    question.image_original_name = prepared.original_name
    question.image_content_type = prepared.content_type
    question.image_checksum = prepared.checksum
    question.image_byte_size = prepared.byte_size
    question.image_width = prepared.width
    question.image_height = prepared.height
    question.image_alt_text = "" if decorative else alt_text.strip()
    question.image_is_decorative = decorative


def clear_question_image(question):
    question.image = ""
    question.image_original_name = ""
    question.image_content_type = ""
    question.image_checksum = ""
    question.image_byte_size = 0
    question.image_width = 0
    question.image_height = 0
    question.image_alt_text = ""
    question.image_is_decorative = False


def read_verified_question_image(question) -> bytes:
    if not question.image or not question.image_checksum:
        raise ValidationError("This question does not have an available image.")
    try:
        with question.image.open("rb") as source:
            content = source.read(MAX_IMAGE_BYTES + 1)
    except (FileNotFoundError, OSError) as exc:
        raise ValidationError("The retained question image is unavailable.") from exc
    if len(content) > MAX_IMAGE_BYTES or hashlib.sha256(content).hexdigest() != question.image_checksum:
        raise ValidationError("The retained question image failed integrity verification.")
    return content


def mark_question_image_availability(questions):
    for question in questions:
        question.image_available = False
        if not question.image:
            continue
        try:
            read_verified_question_image(question)
        except ValidationError:
            continue
        question.image_available = True
    return questions
