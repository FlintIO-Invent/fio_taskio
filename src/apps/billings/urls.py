from django.urls import path
from .views import (
    invoice_create_from_appointment,
    invoice_create_from_client,
    invoice_change_status,
    invoice_detail,
    invoice_edit,
    invoice_list,
)

urlpatterns = [
    path("", invoice_list, name="invoice_list"),
    path(
        "from-appointment/<int:appointment_id>/",
        invoice_create_from_appointment,
        name="invoice_create_from_appointment",
    ),
    path("from-client/<int:client_id>/", invoice_create_from_client, name="invoice_create_from_client"),
    path("<int:invoice_id>/", invoice_detail, name="invoice_detail"),
    path("<int:invoice_id>/edit/", invoice_edit, name="invoice_edit"),
    path("<int:invoice_id>/change-status/", invoice_change_status, name="invoice_change_status"),
]
