from django import forms


class NewsletterSubscribeForm(forms.Form):
    email = forms.EmailField(max_length=254)


class SupportContactForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Your name", "autocomplete": "name"}),
    )
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}),
    )
    subject = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "How can we help?"}),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "Tell us about your issue..."}),
    )
