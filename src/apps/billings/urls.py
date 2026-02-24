from django.urls import path
from .views import invoice_create_from_lead, invoice_detail

urlpatterns = [
    path("from-lead/<int:lead_id>/", invoice_create_from_lead, name="invoice_create_from_lead"),
    path("<int:invoice_id>/", invoice_detail, name="invoice_detail"),
]