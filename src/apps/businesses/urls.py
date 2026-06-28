from django.urls import path

from .views import (
    business_booking_settings,
    business_settings,
    business_setup,
    business_subscription,
    business_team_members,
    business_weekly_availability_deactivate,
)

urlpatterns = [
    path("setup/", business_setup, name="business_setup"),
    path("settings/", business_settings, name="business_settings"),
    path("settings/booking/", business_booking_settings, name="business_booking_settings"),
    path(
        "settings/booking/availability/<int:availability_id>/deactivate/",
        business_weekly_availability_deactivate,
        name="business_weekly_availability_deactivate",
    ),
    path("subscription/", business_subscription, name="business_subscription"),
    path("team/", business_team_members, name="business_team_members"),
]
