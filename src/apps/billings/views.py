from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.crm.models import Lead
from .models import Invoice
from .services import create_invoice_from_lead


@login_required
def invoice_create_from_lead(request, lead_id: int):
    lead = get_object_or_404(Lead, pk=lead_id)

    if request.method == "POST":
        inv = create_invoice_from_lead(actor=request.user, lead=lead)
        return redirect("invoice_detail", invoice_id=inv.id)

    return render(request, "staff/invoice_create.html", {"lead": lead})


@login_required
def invoice_detail(request, invoice_id: int):
    invoice = get_object_or_404(Invoice.objects.select_related("client", "lead"), pk=invoice_id)
    return render(request, "staff/invoice_detail.html", {"invoice": invoice})