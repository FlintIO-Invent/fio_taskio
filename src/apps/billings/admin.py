from django.contrib import admin

from .models import Invoice, InvoiceLine


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 1


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "client",
        "status",
        "emailed_at",
        "email_send_count",
        "created_at",
        "total",
    )
    list_filter = ("status",)
    search_fields = (
        "invoice_number",
        "client__first_name",
        "client__last_name",
        "client__company_name",
        "client__email",
    )
    inlines = [InvoiceLineInline]
