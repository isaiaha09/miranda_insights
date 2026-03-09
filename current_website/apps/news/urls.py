from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("services/", views.services, name="services"),
    path("contact/", views.contact_support, name="contact_support"),
    path("newsletter/subscribe/", views.subscribe, name="newsletter_subscribe"),
    path("newsletter/unsubscribe/", views.unsubscribe, name="newsletter_unsubscribe"),
]
