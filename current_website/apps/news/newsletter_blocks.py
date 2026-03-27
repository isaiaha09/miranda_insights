import json

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.html import escape


BLOCK_TYPE_HEADING = "heading"
BLOCK_TYPE_PARAGRAPH = "paragraph"
BLOCK_TYPE_LIST = "list"
BLOCK_TYPE_IMAGE = "image"
BLOCK_TYPE_BUTTON = "button"
BLOCK_TYPE_QUOTE = "quote"
BLOCK_TYPE_DIVIDER = "divider"
BLOCK_TYPE_SPACER = "spacer"

BLOCK_TYPE_CHOICES = [
	(BLOCK_TYPE_HEADING, "Heading"),
	(BLOCK_TYPE_PARAGRAPH, "Paragraph"),
	(BLOCK_TYPE_LIST, "Bullet list"),
	(BLOCK_TYPE_IMAGE, "Image"),
	(BLOCK_TYPE_BUTTON, "Button"),
	(BLOCK_TYPE_QUOTE, "Quote"),
	(BLOCK_TYPE_DIVIDER, "Divider"),
	(BLOCK_TYPE_SPACER, "Spacer"),
]

ALIGNMENT_CHOICES = [("left", "Left"), ("center", "Center")]
PARAGRAPH_STYLE_CHOICES = [("body", "Body"), ("lead", "Lead"), ("small", "Small")]
BUTTON_STYLE_CHOICES = [("primary", "Primary"), ("secondary", "Secondary")]
IMAGE_WIDTH_CHOICES = [("full", "Full"), ("wide", "Wide"), ("narrow", "Narrow")]
SPACER_SIZE_CHOICES = [("sm", "Small"), ("md", "Medium"), ("lg", "Large")]


def legacy_body_to_blocks(body: str):
	body = (body or "").strip()
	if not body:
		return []

	paragraphs = [part.strip() for part in body.replace("\r", "").split("\n\n") if part.strip()]
	return [{"type": BLOCK_TYPE_PARAGRAPH, "text": paragraph} for paragraph in paragraphs]


def normalize_blocks(raw_blocks):
	if raw_blocks in (None, ""):
		return []

	if isinstance(raw_blocks, str):
		try:
			raw_blocks = json.loads(raw_blocks)
		except json.JSONDecodeError as exc:
			raise ValidationError(f"Invalid newsletter block data: {exc.msg}")

	if not isinstance(raw_blocks, list):
		raise ValidationError("Newsletter content must be a list of blocks.")

	blocks = []
	for index, raw_block in enumerate(raw_blocks, start=1):
		blocks.append(_normalize_block(raw_block, index))
	return blocks


def _normalize_block(raw_block, index: int):
	if not isinstance(raw_block, dict):
		raise ValidationError(f"Block {index} must be an object.")

	block_type = str(raw_block.get("type") or "").strip().lower()
	if block_type not in dict(BLOCK_TYPE_CHOICES):
		raise ValidationError(f"Block {index} has an unsupported type.")

	block = {"type": block_type}

	if block_type == BLOCK_TYPE_HEADING:
		block["text"] = _require_text(raw_block.get("text"), index, "heading text")
		block["level"] = _clean_choice(raw_block.get("level"), {"1", "2", "3"}, "2")
		block["align"] = _clean_choice(raw_block.get("align"), {"left", "center"}, "left")
		return block

	if block_type == BLOCK_TYPE_PARAGRAPH:
		block["text"] = _require_text(raw_block.get("text"), index, "paragraph text")
		block["style"] = _clean_choice(raw_block.get("style"), {"body", "lead", "small"}, "body")
		block["align"] = _clean_choice(raw_block.get("align"), {"left", "center"}, "left")
		return block

	if block_type == BLOCK_TYPE_LIST:
		items = raw_block.get("items")
		if isinstance(items, str):
			items = [line.strip() for line in items.replace("\r", "").split("\n") if line.strip()]
		if not isinstance(items, list):
			raise ValidationError(f"Block {index} must contain list items.")
		clean_items = [str(item).strip() for item in items if str(item).strip()]
		if not clean_items:
			raise ValidationError(f"Block {index} must contain at least one list item.")
		block["items"] = clean_items
		return block

	if block_type == BLOCK_TYPE_IMAGE:
		image_asset_id = _clean_asset_id(raw_block.get("image_asset_id"), index)
		image_url = _clean_text(raw_block.get("image_url"))
		if image_url:
			_validate_url(image_url, index, "image URL")
		if not image_asset_id and not image_url:
			raise ValidationError(f"Block {index} requires either an uploaded image or an image URL.")
		block["image_asset_id"] = image_asset_id
		block["image_url"] = image_url
		block["alt_text"] = _clean_text(raw_block.get("alt_text"))
		if not block["alt_text"] and not image_asset_id:
			raise ValidationError(f"Block {index} requires alt text when using an image URL.")
		block["caption"] = _clean_text(raw_block.get("caption"))
		block["link_url"] = _clean_optional_url(raw_block.get("link_url"), index, "image link URL")
		block["width"] = _clean_choice(raw_block.get("width"), {"full", "wide", "narrow"}, "full")
		return block

	if block_type == BLOCK_TYPE_BUTTON:
		block["text"] = _require_text(raw_block.get("text"), index, "button text")
		block["url"] = _require_url(raw_block.get("url"), index, "button URL")
		block["style"] = _clean_choice(raw_block.get("style"), {"primary", "secondary"}, "primary")
		block["align"] = _clean_choice(raw_block.get("align"), {"left", "center"}, "left")
		return block

	if block_type == BLOCK_TYPE_QUOTE:
		block["text"] = _require_text(raw_block.get("text"), index, "quote text")
		block["attribution"] = _clean_text(raw_block.get("attribution"))
		return block

	if block_type == BLOCK_TYPE_SPACER:
		block["size"] = _clean_choice(raw_block.get("size"), {"sm", "md", "lg"}, "md")
		return block

	return block


def _clean_text(value):
	return str(value or "").strip()


def _require_text(value, index: int, label: str):
	cleaned = _clean_text(value)
	if not cleaned:
		raise ValidationError(f"Block {index} requires {label}.")
	return cleaned


def _clean_choice(value, allowed, default):
	value = str(value or "").strip().lower()
	return value if value in allowed else default


def _clean_asset_id(value, index: int):
	if value in (None, ""):
		return None
	try:
		asset_id = int(value)
	except (TypeError, ValueError):
		raise ValidationError(f"Block {index} has an invalid uploaded image selection.")
	if asset_id <= 0:
		raise ValidationError(f"Block {index} has an invalid uploaded image selection.")
	return asset_id


def _require_url(value, index: int, label: str):
	url = _clean_text(value)
	if not url:
		raise ValidationError(f"Block {index} requires {label}.")
	_validate_url(url, index, label)
	return url


def _clean_optional_url(value, index: int, label: str):
	url = _clean_text(value)
	if not url:
		return ""
	_validate_url(url, index, label)
	return url


def _validate_url(url: str, index: int, label: str):
	validator = URLValidator(schemes=["http", "https"])
	try:
		validator(url)
	except ValidationError:
		raise ValidationError(f"Block {index} has an invalid {label}.")


def build_plain_text(blocks, formatter=None, image_resolver=None):
	parts = []
	for block in blocks or []:
		block_type = block.get("type")
		if block_type == BLOCK_TYPE_HEADING:
			parts.append(_format_value(block.get("text"), formatter))
		elif block_type == BLOCK_TYPE_PARAGRAPH:
			parts.append(_format_value(block.get("text"), formatter))
		elif block_type == BLOCK_TYPE_LIST:
			parts.append("\n".join(f"- {_format_value(item, formatter)}" for item in block.get("items", [])))
		elif block_type == BLOCK_TYPE_IMAGE:
			image = resolve_image_block(block, formatter=formatter, image_resolver=image_resolver)
			caption = image["caption"]
			label = image["alt_text"]
			line = f"[Image: {label}]"
			if caption:
				line = f"{line} {caption}"
			parts.append(line)
		elif block_type == BLOCK_TYPE_BUTTON:
			parts.append(f"{_format_value(block.get('text'), formatter)}: {block.get('url', '')}")
		elif block_type == BLOCK_TYPE_QUOTE:
			quote = f'"{_format_value(block.get("text"), formatter)}"'
			attribution = _format_value(block.get("attribution"), formatter)
			if attribution:
				quote = f"{quote} - {attribution}"
			parts.append(quote)
		elif block_type == BLOCK_TYPE_DIVIDER:
			parts.append("----------------------------------------")
		elif block_type == BLOCK_TYPE_SPACER:
			parts.append("")

	return "\n\n".join(part for part in parts if part is not None).strip()


def build_html(blocks, formatter=None, image_resolver=None):
	return "".join(_render_block_html(block, formatter, image_resolver=image_resolver) for block in blocks or [])


def _render_block_html(block, formatter=None, image_resolver=None):
	block_type = block.get("type")
	if block_type == BLOCK_TYPE_HEADING:
		level = block.get("level", "2")
		font_size = {"1": "34px", "2": "28px", "3": "22px"}.get(level, "28px")
		return (
			f'<div style="margin:0 0 18px 0;text-align:{block.get("align", "left")};">'
			f'<div style="margin:0;font-size:{font_size};line-height:1.2;font-weight:800;color:#f8fbff;">{_escape_with_breaks(_format_value(block.get("text"), formatter))}</div>'
			"</div>"
		)

	if block_type == BLOCK_TYPE_PARAGRAPH:
		style = block.get("style", "body")
		font_size = {"lead": "19px", "body": "16px", "small": "14px"}.get(style, "16px")
		line_height = {"lead": "1.75", "body": "1.7", "small": "1.65"}.get(style, "1.7")
		color = "#c9d6e2" if style != "small" else "#aab6c4"
		return (
			f'<div style="margin:0 0 18px 0;text-align:{block.get("align", "left")};font-size:{font_size};line-height:{line_height};color:{color};">'
			f'{_escape_with_breaks(_format_value(block.get("text"), formatter))}'
			"</div>"
		)

	if block_type == BLOCK_TYPE_LIST:
		items = "".join(
			f'<li style="margin:0 0 10px 0;">{_escape_with_breaks(_format_value(item, formatter))}</li>'
			for item in block.get("items", [])
		)
		return (
			'<div style="margin:0 0 20px 0;">'
			'<ul style="margin:0;padding-left:22px;color:#d9e1ea;">'
			f"{items}"
			"</ul></div>"
		)

	if block_type == BLOCK_TYPE_IMAGE:
		image = resolve_image_block(block, formatter=formatter, image_resolver=image_resolver)
		if not image["image_url"]:
			return ""
		max_width = {"full": "100%", "wide": "84%", "narrow": "64%"}.get(block.get("width", "full"), "100%")
		image_tag = (
			f'<img src="{escape(image["image_url"])}" alt="{escape(image["alt_text"])}" '
			f'style="display:block;width:100%;max-width:{max_width};height:auto;border:0;border-radius:16px;margin:0 auto;" />'
		)
		if image["link_url"]:
			image_tag = f'<a href="{escape(image["link_url"])}" style="text-decoration:none;">{image_tag}</a>'
		caption = image["caption"]
		caption_html = ""
		if caption:
			caption_html = f'<div style="margin-top:10px;font-size:13px;line-height:1.6;color:#91a0b2;text-align:center;">{_escape_with_breaks(caption)}</div>'
		return f'<div style="margin:0 0 24px 0;">{image_tag}{caption_html}</div>'

	if block_type == BLOCK_TYPE_BUTTON:
		style = block.get("style", "primary")
		background = "#7db5ff" if style == "primary" else "transparent"
		color = "#07111f" if style == "primary" else "#d9e1ea"
		border = "none" if style == "primary" else "1px solid rgba(230,238,246,0.28)"
		return (
			f'<div style="margin:0 0 24px 0;text-align:{block.get("align", "left")};">'
			f'<a href="{escape(block.get("url", ""))}" style="display:inline-block;padding:14px 22px;border-radius:999px;background:{background};color:{color};border:{border};font-size:15px;font-weight:700;text-decoration:none;">{escape(_format_value(block.get("text"), formatter))}</a>'
			"</div>"
		)

	if block_type == BLOCK_TYPE_QUOTE:
		attribution = _format_value(block.get("attribution"), formatter)
		attribution_html = ""
		if attribution:
			attribution_html = f'<div style="margin-top:10px;font-size:13px;color:#9aa6b2;font-weight:600;">{escape(attribution)}</div>'
		return (
			'<div style="margin:0 0 22px 0;padding:18px 20px;border-left:4px solid #7db5ff;background:rgba(125,181,255,0.08);border-radius:0 14px 14px 0;">'
			f'<div style="font-size:17px;line-height:1.7;color:#e6eef6;">{_escape_with_breaks(_format_value(block.get("text"), formatter))}</div>'
			f"{attribution_html}"
			"</div>"
		)

	if block_type == BLOCK_TYPE_DIVIDER:
		return '<div style="margin:26px 0;border-top:1px solid rgba(230,238,246,0.14);"></div>'

	if block_type == BLOCK_TYPE_SPACER:
		height = {"sm": "16px", "md": "28px", "lg": "40px"}.get(block.get("size", "md"), "28px")
		return f'<div style="height:{height};line-height:{height};font-size:0;">&nbsp;</div>'

	return ""


def _format_value(value, formatter=None):
	text = str(value or "")
	return formatter(text) if formatter else text


def resolve_image_block(block, formatter=None, image_resolver=None):
	asset_data = None
	asset_id = block.get("image_asset_id")
	if asset_id and image_resolver:
		asset_data = image_resolver(asset_id)

	image_url = _format_value(block.get("image_url"), formatter)
	if not image_url and asset_data:
		image_url = asset_data.get("url", "")

	alt_text = _format_value(block.get("alt_text"), formatter)
	if not alt_text and asset_data:
		alt_text = _format_value(asset_data.get("alt_text"), formatter)

	caption = _format_value(block.get("caption"), formatter)
	if not caption and asset_data:
		caption = _format_value(asset_data.get("caption"), formatter)

	return {
		"image_url": image_url,
		"alt_text": alt_text,
		"caption": caption,
		"link_url": _format_value(block.get("link_url"), formatter),
	}


def _escape_with_breaks(value: str):
	return escape(value).replace("\n", "<br>")