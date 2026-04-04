from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="OutboundJob",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("job_type", models.CharField(choices=[("email_message", "Email message"), ("push_notification", "Push notification"), ("newsletter_campaign", "Newsletter campaign")], max_length=40)),
                ("payload", models.JSONField(default=dict)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("processing", "Processing"), ("succeeded", "Succeeded"), ("failed", "Failed")], default="pending", max_length=20)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("max_attempts", models.PositiveIntegerField(default=5)),
                ("run_after", models.DateTimeField(default=django.utils.timezone.now)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="outboundjob",
            index=models.Index(fields=["status", "run_after"], name="operations_o_status_8dd9f0_idx"),
        ),
        migrations.AddIndex(
            model_name="outboundjob",
            index=models.Index(fields=["job_type", "status"], name="operations_o_job_typ_8beacb_idx"),
        ),
    ]