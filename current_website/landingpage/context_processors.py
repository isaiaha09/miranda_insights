from django.conf import settings


def site_contact(request):
    return {
        "footer_contact_email": settings.CONTACT_RECIPIENT,
        "footer_contact_label": settings.SUPPORT_EMAIL,
    }
