# Generated manually for newsletter feature bootstrap.

import datetime
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='NewsletterCampaign',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('subject', models.CharField(max_length=200)),
                ('body', models.TextField(help_text='Use plain text. Optional placeholder: {date}')),
                ('mode', models.CharField(choices=[('custom', 'Custom'), ('automated', 'Automated')], default='custom', max_length=20)),
                ('is_active', models.BooleanField(default=True)),
                ('frequency', models.CharField(choices=[('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly'), ('interval', 'Every N days')], default='weekly', max_length=20)),
                ('interval_days', models.PositiveIntegerField(default=7)),
                ('weekday', models.PositiveSmallIntegerField(blank=True, help_text='0=Monday ... 6=Sunday (for weekly automation)', null=True)),
                ('day_of_month', models.PositiveSmallIntegerField(blank=True, help_text='1-28 (for monthly automation)', null=True)),
                ('send_time', models.TimeField(default=datetime.time(9, 0))),
                ('last_sent_at', models.DateTimeField(blank=True, null=True)),
                ('next_send_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='newsletter_campaigns', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='NewsletterSubscriber',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('subscribed_at', models.DateTimeField(auto_now_add=True)),
                ('unsubscribed_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'ordering': ['-subscribed_at'],
            },
        ),
        migrations.CreateModel(
            name='NewsletterSendLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('recipient_email', models.EmailField(max_length=254)),
                ('status', models.CharField(choices=[('sent', 'Sent'), ('failed', 'Failed')], max_length=12)),
                ('error_message', models.TextField(blank=True)),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('campaign', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='send_logs', to='news.newslettercampaign')),
            ],
            options={
                'ordering': ['-sent_at'],
            },
        ),
    ]
