from django import forms


class NewsletterSubscribeForm(forms.Form):
    email = forms.EmailField(max_length=254)


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
