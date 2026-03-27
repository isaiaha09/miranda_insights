import json

from django.forms import Widget
from django.utils.html import format_html, json_script
from django.utils.safestring import mark_safe


class NewsletterBlockEditorWidget(Widget):
	template_name = ""

	def __init__(self, attrs=None):
		super().__init__(attrs)
		self.image_assets = []
		self.block_templates = []

	class Media:
		css = {"all": ("news/admin/newsletter-block-editor.css",)}
		js = ("news/admin/newsletter-block-editor.js",)

	def render(self, name, value, attrs=None, renderer=None):
		attrs = attrs or {}
		field_id = attrs.get("id") or f"id_{name}"
		serialized = self._serialize_value(value)
		assets_script_id = f"{field_id}_assets"
		templates_script_id = f"{field_id}_templates"
		html = format_html(
			'<div class="newsletter-block-editor" data-target-id="{0}" data-assets-script-id="{3}" data-templates-script-id="{4}"></div>'
			'<textarea name="{1}" id="{0}" class="newsletter-block-editor__input" hidden>{2}</textarea>{5}{6}',
			field_id,
			name,
			serialized,
			assets_script_id,
			templates_script_id,
			json_script(self.image_assets, assets_script_id),
			json_script(self.block_templates, templates_script_id),
		)
		return mark_safe(html)

	def value_from_datadict(self, data, files, name):
		return data.get(name, "[]")

	def _serialize_value(self, value):
		if isinstance(value, str):
			return value
		return json.dumps(value or [], ensure_ascii=True)