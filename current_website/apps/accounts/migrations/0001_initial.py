from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("industry_type", models.CharField(choices=[("law_firm", "Law Firm"), ("financial_institution", "Financial Institution"), ("government_agency", "Government Agency"), ("healthcare", "Healthcare"), ("educational_institution", "Educational Institution"), ("counseling_services", "Counseling Services"), ("individual", "Individual"), ("other", "Other")], max_length=64)),
                ("phone_number", models.CharField(max_length=40)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="account_profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]