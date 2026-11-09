from django.contrib import admin
from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.businesses.models import Business

from .models import Invoice, InvoiceLine, InvoicePayment
from .presentation import present_invoice


class InvoiceLifecycleFilter(admin.SimpleListFilter):
    title = "invoice status"
    parameter_name = "lifecycle"

    def lookups(self, request, model_admin):
        return (("DRAFT", "Draft"), ("ISSUED", "Issued"), ("CANCELLED", "Cancelled"))

    def queryset(self, request, queryset):
        if self.value() == "ISSUED":
            return queryset.filter(status__in=("SENT", "PAID"))
        if self.value() in ("DRAFT", "CANCELLED"):
            return queryset.filter(status=self.value())
        return queryset


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 1


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "client",
        "lifecycle",
        "payment_state",
        "email_submission",
        "created_at",
        "invoice_total",
        "balance_due",
        "refund_due",
    )
    list_filter = (InvoiceLifecycleFilter,)
    exclude = ("status",)
    readonly_fields = ("lifecycle", "payment_state", "financial_summary", "email_submission")
    search_fields = (
        "invoice_number",
        "client__first_name",
        "client__last_name",
        "client__company_name",
        "client__email",
    )
    inlines = [InvoiceLineInline]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("business", "client")
            .prefetch_related("payments")
        )

    @admin.display(description="Invoice status")
    def lifecycle(self, invoice):
        if not invoice or not invoice.pk:
            return "Draft"
        return present_invoice(invoice).lifecycle_label

    @admin.display(description="Payment / accounting")
    def payment_state(self, invoice):
        if not invoice or not invoice.pk:
            return "No payment recorded"
        financial = present_invoice(invoice)
        return "; ".join(financial.indicators) or financial.note

    @admin.display(description="Original invoice total")
    def invoice_total(self, invoice):
        financial = present_invoice(invoice)
        return f"{financial.currency} {financial.original_total:.2f}"

    @admin.display(description="Balance due")
    def balance_due(self, invoice):
        financial = present_invoice(invoice)
        return (
            "Accounting review required"
            if financial.review_required
            else f"{financial.currency} {financial.balance_due:.2f}"
        )

    @admin.display(description="Refund due")
    def refund_due(self, invoice):
        financial = present_invoice(invoice)
        return (
            "Accounting review required"
            if financial.issues
            else f"{financial.currency} {financial.balance.refund_due:.2f}"
        )

    @admin.display(description="Financial summary")
    def financial_summary(self, invoice):
        if not invoice or not invoice.pk:
            return "Save a Draft invoice first."
        financial = present_invoice(invoice)
        return "; ".join(f"{row['label']}: {row['text']}" for row in financial.amount_rows)

    @admin.display(description="Email submission")
    def email_submission(self, invoice):
        if not invoice or not invoice.pk:
            return "No email submission recorded."
        financial = present_invoice(invoice)
        return financial.email_note

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (
            obj is None
            or (
                obj.status == Invoice.Status.DRAFT
                and not obj.payments.exists()
                and not obj.lines.filter(charge_source__isnull=False).exists()
                and not obj.lines.filter(logistics_charge__isnull=False).exists()
            )
        )

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def delete_model(self, request, obj):
        # Recheck after waiting for issuance/receipt writes, using the domain lock order.
        with transaction.atomic():
            Business.objects.select_for_update().get(pk=obj.business_id)
            selected = Invoice.objects.select_for_update().get(pk=obj.pk)
            if selected.status != Invoice.Status.DRAFT:
                raise ProtectedError("Only Draft invoices can be deleted.", [selected])
            selected.delete()


@admin.register(InvoicePayment)
class InvoicePaymentAdmin(admin.ModelAdmin):
    list_display = (
        "invoice",
        "kind",
        "amount",
        "currency",
        "method",
        "reference",
        "recorded_by",
        "recorded_at",
    )
    list_filter = ("kind", "currency", "method")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
