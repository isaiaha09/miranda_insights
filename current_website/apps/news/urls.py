from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("services/", views.services, name="services"),
    path("products/", views.products, name="products"),
    path("faq/", views.faq, name="faq"),
    path("contact/", views.contact_support, name="contact_support"),
    path("newsletter/subscribe/", views.subscribe, name="newsletter_subscribe"),
    path("newsletter/unsubscribe/", views.unsubscribe, name="newsletter_unsubscribe"),
]
