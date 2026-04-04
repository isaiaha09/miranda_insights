from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.utils import timezone


class OutboundJob(models.Model):
    TYPE_EMAIL = "email_message"
    TYPE_PUSH = "push_notification"
    TYPE_NEWSLETTER_CAMPAIGN = "newsletter_campaign"
    TYPE_CHOICES = [
        (TYPE_EMAIL, "Email message"),
        (TYPE_PUSH, "Push notification"),
        (TYPE_NEWSLETTER_CAMPAIGN, "Newsletter campaign"),
    ]

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
    ]

    job_type = models.CharField(max_length=40, choices=TYPE_CHOICES)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    run_after = models.DateTimeField(default=timezone.now)
    locked_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "run_after"]),
            models.Index(fields=["job_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_job_type_display()} ({self.status})"

    def next_retry_at(self):
        delay_seconds = min(3600, 30 * (2 ** max(self.attempts - 1, 0)))
        return timezone.now() + timedelta(seconds=delay_seconds)