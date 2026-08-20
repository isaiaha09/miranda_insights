import apps.surveyhq.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("surveyhq", "0004_alter_survey_options_and_more")]

    operations = [
        migrations.AddField(model_name="surveyquestion", name="image", field=models.ImageField(blank=True, max_length=500, upload_to=apps.surveyhq.models.survey_question_image_path)),
        migrations.AddField(model_name="surveyquestion", name="image_alt_text", field=models.CharField(blank=True, max_length=500)),
        migrations.AddField(model_name="surveyquestion", name="image_byte_size", field=models.PositiveBigIntegerField(default=0)),
        migrations.AddField(model_name="surveyquestion", name="image_checksum", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="surveyquestion", name="image_content_type", field=models.CharField(blank=True, max_length=40)),
        migrations.AddField(model_name="surveyquestion", name="image_height", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="surveyquestion", name="image_is_decorative", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="surveyquestion", name="image_original_name", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="surveyquestion", name="image_width", field=models.PositiveIntegerField(default=0)),
        migrations.AddConstraint(model_name="surveyquestion", constraint=models.CheckConstraint(condition=~models.Q(question_type="page_break") | models.Q(image=""), name="svhq_page_break_no_image")),
        migrations.AddConstraint(model_name="surveyquestion", constraint=models.CheckConstraint(condition=~models.Q(image_is_decorative=True) | models.Q(image_alt_text=""), name="svhq_decorative_alt_empty")),
        migrations.AddConstraint(model_name="surveyquestion", constraint=models.CheckConstraint(condition=models.Q(image="") | models.Q(image_is_decorative=True) | ~models.Q(image_alt_text=""), name="svhq_image_alt_required")),
    ]
