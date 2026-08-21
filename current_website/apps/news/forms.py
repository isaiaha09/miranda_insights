from datetime import time

from django import forms

from .models import NewsletterBlockTemplate, NewsletterCampaign, NewsletterImageAsset
from .newsletter_blocks import build_plain_text, legacy_body_to_blocks, normalize_blocks
from .widgets import NewsletterBlockEditorWidget


class NewsletterSubscribeForm(forms.Form):
    email = forms.EmailField(max_length=254)


HOUR_CHOICES = [(str(hour), str(hour)) for hour in range(1, 13)]
MINUTE_CHOICES = [(str(minute), f"{minute:02d}") for minute in range(60)]
MERIDIEM_CHOICES = (("AM", "AM"), ("PM", "PM"))
WEEKDAY_CHOICES = [
    (str(index), day)
    for index, day in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))
]


class NewsletterCampaignAdminForm(forms.ModelForm):
    content_blocks = forms.JSONField(required=False, widget=NewsletterBlockEditorWidget)
    frequency = forms.ChoiceField(
        choices=NewsletterCampaign.FREQUENCY_CHOICES,
        label="Frequency",
        help_text="Daily, weekly, monthly, or every N days.",
    )
    mode = forms.ChoiceField(
        choices=NewsletterCampaign.MODE_CHOICES,
        label="Delivery mode",
        help_text="Automated campaigns follow the schedule below. Custom campaigns are sent only when you use Send now.",
    )
    include_subscribers = forms.BooleanField(
        required=False,
        initial=True,
        label="Send to all active subscribers",
        help_text="Leave this unchecked to send only to the specific email addresses below.",
    )
    direct_recipients = forms.CharField(
        required=False,
        label="Specific recipient emails",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "person@example.com\nanother@example.com",
            }
        ),
        help_text="Enter addresses separated by commas or new lines. These are added to all subscribers when the option above is checked.",
    )
    send_hour = forms.TypedChoiceField(
        choices=HOUR_CHOICES,
        coerce=int,
        label="Hour",
    )
    send_minute = forms.TypedChoiceField(
        choices=MINUTE_CHOICES,
        coerce=int,
        label="Minute",
    )
    send_meridiem = forms.ChoiceField(
        choices=MERIDIEM_CHOICES,
        label="AM or PM",
        help_text="Uses the newsletter time zone configured for this site.",
    )
    weekday = forms.TypedChoiceField(
        required=False,
        choices=WEEKDAY_CHOICES,
        coerce=int,
        label="Weekday",
    )

    class Meta:
        model = NewsletterCampaign
        exclude = ("body", "send_time")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.is_bound:
            self.initial.setdefault("mode", NewsletterCampaign.MODE_AUTOMATED)
        if not self.is_bound:
            send_time = self.instance.send_time or time(9, 0)
            self.initial.setdefault("send_hour", str(send_time.hour % 12 or 12))
            self.initial.setdefault("send_minute", str(send_time.minute))
            self.initial.setdefault("send_meridiem", "PM" if send_time.hour >= 12 else "AM")
        widget = self.fields["content_blocks"].widget
        widget.image_assets = [asset.to_editor_payload() for asset in NewsletterImageAsset.objects.filter(is_active=True)]
        widget.block_templates = [template.to_editor_payload() for template in NewsletterBlockTemplate.objects.filter(is_active=True)]
        if self.instance and self.instance.pk and not self.initial.get("content_blocks") and self.instance.body:
            self.initial["content_blocks"] = legacy_body_to_blocks(self.instance.body)

    def clean_content_blocks(self):
        return normalize_blocks(self.cleaned_data.get("content_blocks"))

    def clean(self):
        cleaned_data = super().clean()
        blocks = cleaned_data.get("content_blocks") or []

        if not blocks:
            self.add_error("content_blocks", "Add at least one content block before saving the newsletter campaign.")

        if not cleaned_data.get("include_subscribers") and not (cleaned_data.get("direct_recipients") or "").strip():
            self.add_error(
                "direct_recipients",
                "Choose all active subscribers or enter at least one specific recipient email.",
            )

        hour = cleaned_data.get("send_hour")
        minute = cleaned_data.get("send_minute")
        meridiem = cleaned_data.get("send_meridiem")
        if hour is not None and minute is not None and meridiem:
            hour = hour % 12
            if meridiem == "PM":
                hour += 12
            cleaned_data["send_time"] = time(hour=hour, minute=minute)

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.send_time = self.cleaned_data["send_time"]
        instance.body = build_plain_text(instance.content_blocks)
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class NewsletterBlockTemplateAdminForm(forms.ModelForm):
    content_blocks = forms.JSONField(required=False, widget=NewsletterBlockEditorWidget)

    class Meta:
        model = NewsletterBlockTemplate
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        widget = self.fields["content_blocks"].widget
        widget.image_assets = [asset.to_editor_payload() for asset in NewsletterImageAsset.objects.filter(is_active=True)]
        widget.block_templates = [template.to_editor_payload() for template in NewsletterBlockTemplate.objects.filter(is_active=True)]

    def clean_content_blocks(self):
        return normalize_blocks(self.cleaned_data.get("content_blocks"))

    def clean(self):
        cleaned_data = super().clean()
        blocks = cleaned_data.get("content_blocks") or []

        if not blocks:
            self.add_error("content_blocks", "Add at least one content block before saving the reusable template.")

        return cleaned_data


class SupportContactForm(forms.Form):
    SUBJECT_CHOICES = (
        ("consulting", "Consulting"),
        ("product", "Product"),
        ("general", "General"),
        ("support", "Support"),
        ("partnership", "Partnership"),
        ("other", "Other"),
    )

    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Your name", "autocomplete": "name"}),
    )
    organization = forms.CharField(
        max_length=160,
        widget=forms.TextInput(attrs={"placeholder": "Your organization", "autocomplete": "organization"}),
    )
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}),
    )
    phone = forms.CharField(
        max_length=40,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "(555) 123-4567", "autocomplete": "tel"}),
    )
    business_location = forms.CharField(
        max_length=160,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "City, State or Region", "autocomplete": "address-level2"}),
    )
    subject_choice = forms.ChoiceField(
        choices=(("", "Select a subject"),) + SUBJECT_CHOICES,
        widget=forms.Select(),
    )
    subject_other = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Enter your subject"}),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "Tell us about your issue..."}),
    )

    def clean(self):
        cleaned_data = super().clean()
        subject_choice = (cleaned_data.get("subject_choice") or "").strip()
        subject_other = (cleaned_data.get("subject_other") or "").strip()

        if not subject_choice:
            self.add_error("subject_choice", "Please select a subject.")
            return cleaned_data

        if subject_choice == "other":
            if not subject_other:
                self.add_error("subject_other", "Please enter your subject.")
                return cleaned_data
            cleaned_data["subject"] = subject_other
            return cleaned_data

        choices_map = dict(self.SUBJECT_CHOICES)
        cleaned_data["subject"] = choices_map.get(subject_choice, subject_choice.title())
        return cleaned_data
