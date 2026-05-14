from django.urls import path

from .views import business_setup, business_settings


urlpatterns = [
    path("setup/", business_setup, name="business_setup"),
    path("settings/", business_settings, name="business_settings"),
]
