from django.urls import path

from .views import (
    appointment_change_status,
    appointment_create,
    appointment_create_from_request,
    appointment_detail,
    appointment_list,
    appointment_update,
)

urlpatterns = [
    path("", appointment_list, name="appointment_list"),
    path("create/", appointment_create, name="appointment_create"),
    path(
        "create/from-request/<int:lead_id>/",
        appointment_create_from_request,
        name="appointment_create_from_request",
    ),
    path("<int:appointment_id>/", appointment_detail, name="appointment_detail"),
    path("<int:appointment_id>/edit/", appointment_update, name="appointment_update"),
    path(
        "<int:appointment_id>/change-status/",
        appointment_change_status,
        name="appointment_change_status",
    ),
]
