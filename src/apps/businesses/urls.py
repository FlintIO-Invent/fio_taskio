from django.urls import path

from .views import (
    business_setup,
    business_settings,
    business_subscription,
    business_team_members,
)


urlpatterns = [
    path("setup/", business_setup, name="business_setup"),
    path("settings/", business_settings, name="business_settings"),
    path("subscription/", business_subscription, name="business_subscription"),
    path("team/", business_team_members, name="business_team_members"),
]
