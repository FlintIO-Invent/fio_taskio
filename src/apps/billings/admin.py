from django.contrib import admin
from .models import Invoice, InvoiceLine

class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 1

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "client", "status", "created_at", "total")
    list_filter = ("status",)
    search_fields = ("invoice_number", "client__name", "client__email")
    inlines = [InvoiceLineInline]