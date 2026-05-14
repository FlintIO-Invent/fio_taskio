from django.urls import path

from .views import business_setup


urlpatterns = [
    path("setup/", business_setup, name="business_setup"),
]
