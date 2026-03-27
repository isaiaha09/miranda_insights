from django.db import migrations, models


def migrate_legacy_bodies(apps, schema_editor):
	NewsletterCampaign = apps.get_model("news", "NewsletterCampaign")
	for campaign in NewsletterCampaign.objects.all():
		if campaign.content_blocks:
			continue
		body = (campaign.body or "").strip()
		if not body:
			continue
		paragraphs = [part.strip() for part in body.replace("\r", "").split("\n\n") if part.strip()]
		campaign.content_blocks = [{"type": "paragraph", "text": paragraph} for paragraph in paragraphs]
		campaign.save(update_fields=["content_blocks"])


class Migration(migrations.Migration):

	dependencies = [
		("news", "0002_campaign_direct_recipients"),
	]

	operations = [
		migrations.AddField(
			model_name="newslettercampaign",
			name="content_blocks",
			field=models.JSONField(blank=True, default=list, help_text="Structured content blocks used to compose the newsletter email."),
		),
		migrations.AddField(
			model_name="newslettercampaign",
			name="preheader",
			field=models.CharField(blank=True, help_text="Optional preview text shown in supporting email clients.", max_length=255),
		),
		migrations.AlterField(
			model_name="newslettercampaign",
			name="body",
			field=models.TextField(blank=True, help_text="Legacy plain text fallback. Optional placeholder: {date}"),
		),
		migrations.RunPython(migrate_legacy_bodies, migrations.RunPython.noop),
	]