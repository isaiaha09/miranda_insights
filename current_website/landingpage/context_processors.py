from email.utils import parseaddr

from django.conf import settings


def site_contact(request):
    support_mailto = settings.SUPPORT_EMAIL or settings.CONTACT_RECIPIENT
    support_email = parseaddr(support_mailto or "")[1] or support_mailto

    return {
        "footer_contact_email": support_mailto,
        "footer_contact_label": support_email,
    }
