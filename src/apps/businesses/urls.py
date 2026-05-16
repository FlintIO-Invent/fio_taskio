from django.urls import path

from .views import business_setup, business_settings, business_subscription


urlpatterns = [
    path("setup/", business_setup, name="business_setup"),
    path("settings/", business_settings, name="business_settings"),
    path("subscription/", business_subscription, name="business_subscription"),
]
