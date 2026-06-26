from django.urls import path

from .views import (
    invoice_change_status,
    invoice_create_from_appointment,
    invoice_create_from_client,
    invoice_detail,
    invoice_edit,
    invoice_email_send,
    invoice_list,
    invoice_pdf_download,
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
    path("<int:invoice_id>/pdf/", invoice_pdf_download, name="invoice_pdf_download"),
    path("<int:invoice_id>/email/", invoice_email_send, name="invoice_email_send"),
    path("<int:invoice_id>/edit/", invoice_edit, name="invoice_edit"),
    path("<int:invoice_id>/change-status/", invoice_change_status, name="invoice_change_status"),
]
