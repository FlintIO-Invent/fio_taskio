from django.contrib import admin

from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "business",
        "client",
        "service_name",
        "staff_member",
        "start_time",
        "end_time",
        "status",
    )
    list_filter = ("business", "status", "start_time")
    search_fields = (
        "title",
        "service_name",
        "location",
        "client__first_name",
        "client__last_name",
        "client__company_name",
        "staff_member__email",
        "business__name",
    )
    autocomplete_fields = ("business", "client", "service", "staff_member")
    list_select_related = ("business", "client", "service", "staff_member")

