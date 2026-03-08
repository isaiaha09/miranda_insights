from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("contact/", views.contact_support, name="contact_support"),
    path("newsletter/subscribe/", views.subscribe, name="newsletter_subscribe"),
]
