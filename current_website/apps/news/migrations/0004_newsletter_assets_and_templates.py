from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_default_templates(apps, schema_editor):
	NewsletterBlockTemplate = apps.get_model("news", "NewsletterBlockTemplate")
	templates = [
		{
			"name": "Hero Spotlight",
			"slug": "hero-spotlight",
			"description": "A bold headline, supporting copy, and a CTA button.",
			"category": "hero",
			"is_builtin": True,
			"content_blocks": [
				{"type": "heading", "text": "Big headline for your top story", "level": "1", "align": "left"},
				{"type": "paragraph", "text": "Use this section for the most important update or announcement in the newsletter.", "style": "lead", "align": "left"},
				{"type": "button", "text": "Explore now", "url": "https://example.com", "style": "primary", "align": "left"},
			],
		},
		{
			"name": "Event Announcement",
			"slug": "event-announcement",
			"description": "Promote a webinar, live event, or workshop.",
			"category": "event",
			"is_builtin": True,
			"content_blocks": [
				{"type": "heading", "text": "Upcoming event title", "level": "2", "align": "left"},
				{"type": "paragraph", "text": "Date: Month Day, Year\nTime: 12:00 PM ET\nLocation: Online", "style": "body", "align": "left"},
				{"type": "quote", "text": "Add one short reason people should attend.", "attribution": "Why it matters"},
				{"type": "button", "text": "Reserve your seat", "url": "https://example.com", "style": "primary", "align": "left"},
			],
		},
		{
			"name": "Article Digest",
			"slug": "article-digest",
			"description": "A clean repeatable layout for multiple article links.",
			"category": "article",
			"is_builtin": True,
			"content_blocks": [
				{"type": "heading", "text": "Top reads this week", "level": "2", "align": "left"},
				{"type": "list", "items": ["Article one: one-line summary", "Article two: one-line summary", "Article three: one-line summary"]},
				{"type": "button", "text": "Read all articles", "url": "https://example.com", "style": "secondary", "align": "left"},
			],
		},
	]

	for template in templates:
		NewsletterBlockTemplate.objects.update_or_create(slug=template["slug"], defaults=template)


class Migration(migrations.Migration):

	dependencies = [
		("news", "0003_newslettercampaign_block_content"),
		migrations.swappable_dependency(settings.AUTH_USER_MODEL),
	]

	operations = [
		migrations.CreateModel(
			name="NewsletterBlockTemplate",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("name", models.CharField(max_length=140)),
				("slug", models.SlugField(unique=True)),
				("description", models.CharField(blank=True, max_length=255)),
				("category", models.CharField(choices=[("general", "General"), ("hero", "Hero"), ("event", "Event"), ("article", "Article digest")], default="general", max_length=24)),
				("content_blocks", models.JSONField(default=list)),
				("is_builtin", models.BooleanField(default=False)),
				("is_active", models.BooleanField(default=True)),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("updated_at", models.DateTimeField(auto_now=True)),
				("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="newsletter_block_templates", to=settings.AUTH_USER_MODEL)),
			],
			options={"ordering": ["category", "name"]},
		),
		migrations.CreateModel(
			name="NewsletterImageAsset",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("name", models.CharField(max_length=140)),
				("image", models.ImageField(upload_to="newsletter/images/%Y/%m")),
				("alt_text", models.CharField(blank=True, max_length=255)),
				("default_caption", models.CharField(blank=True, max_length=255)),
				("is_active", models.BooleanField(default=True)),
				("created_at", models.DateTimeField(auto_now_add=True)),
				("updated_at", models.DateTimeField(auto_now=True)),
				("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="newsletter_image_assets", to=settings.AUTH_USER_MODEL)),
			],
			options={"ordering": ["name", "-created_at"]},
		),
		migrations.RunPython(create_default_templates, migrations.RunPython.noop),
	]