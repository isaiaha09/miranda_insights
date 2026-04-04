from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserCreationForm
from django.template.loader import render_to_string

from apps.operations.services import dispatch_raw_email
from .models import AccountProfile


User = get_user_model()


class SignupForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    last_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autocomplete": "family-name"}))
    organization_name = forms.CharField(max_length=180, required=False, label="Business/Organization Name")
    organization_description = forms.CharField(required=False, label="Business/Organization Description", widget=forms.Textarea(attrs={"rows": 3}))
    industry_type = forms.ChoiceField(choices=AccountProfile.INDUSTRY_CHOICES)
    phone_number = forms.CharField(max_length=40, widget=forms.TextInput(attrs={"autocomplete": "tel"}))
    email = forms.EmailField(max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    subscribe_to_newsletter = forms.BooleanField(required=False, label="Subscribe to the newsletter")
    agree_to_terms = forms.BooleanField(label="I agree to the Terms & Agreement")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "organization_name", "organization_description", "industry_type", "phone_number", "email", "username")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].widget.attrs.update({"placeholder": "First name"})
        self.fields["last_name"].widget.attrs.update({"placeholder": "Last name"})
        self.fields["organization_name"].widget.attrs.update({"placeholder": "Business or organization name"})
        self.fields["organization_description"].widget.attrs.update({"placeholder": "A short description of your organization or team."})
        self.fields["industry_type"].choices = (("", "Select an industry"),) + tuple(AccountProfile.INDUSTRY_CHOICES)
        self.fields["phone_number"].widget.attrs.update({"placeholder": "Phone number"})
        self.fields["email"].widget.attrs.update({"placeholder": "Email address"})
        self.fields["username"].widget.attrs.update({"placeholder": "Username", "autocomplete": "username"})
        self.fields["password1"].widget.attrs.update({"placeholder": "Password", "autocomplete": "new-password"})
        self.fields["password2"].widget.attrs.update({"placeholder": "Confirm password", "autocomplete": "new-password"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.email = self.cleaned_data["email"].strip().lower()
        if commit:
            user.save()
            AccountProfile.objects.create(
                user=user,
                industry_type=self.cleaned_data["industry_type"],
                phone_number=self.cleaned_data["phone_number"].strip(),
            )
            from apps.clients.models import get_or_create_client_for_user

            client_record = get_or_create_client_for_user(user)
            client_record.organization_name = self.cleaned_data["organization_name"].strip()
            client_record.organization_description = self.cleaned_data["organization_description"].strip()
            client_record.save(update_fields=["organization_name", "organization_description", "updated_at"])
        return user


class NewsletterPreferenceForm(forms.Form):
    subscribe_to_newsletter = forms.BooleanField(required=False, label="Email me newsletter updates and product insights")


class DeleteAccountForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Retype your password",
                "autocomplete": "current-password",
            }
        )
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user or not self.user.check_password(password):
            raise forms.ValidationError("Enter your current password to confirm account deletion.")
        return password


class TwoFactorChallengeForm(forms.Form):
    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={"placeholder": "123456", "inputmode": "numeric", "autocomplete": "one-time-code"}),
    )


class TwoFactorSetupForm(forms.Form):
    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={"placeholder": "123456", "inputmode": "numeric", "autocomplete": "one-time-code"}),
    )


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Incorrect username or password.",
    }

    username = forms.CharField(widget=forms.TextInput(attrs={"placeholder": "Username", "autocomplete": "username"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder": "Password", "autocomplete": "current-password"}))


class UsernameRecoveryForm(forms.Form):
    email = forms.EmailField(max_length=254, widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}))


class StyledPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(max_length=254, widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}))

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        subject = "".join(render_to_string(subject_template_name, context).splitlines())
        text_body = render_to_string(email_template_name, context)
        html_body = render_to_string(html_email_template_name, context) if html_email_template_name else None
        dispatch_raw_email(
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            to=[to_email],
            from_email=from_email,
        )