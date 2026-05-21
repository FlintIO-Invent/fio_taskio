from django.contrib import admin

from .models import ActivityLog, Client, Lead, ServiceCategory


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "code", "is_active", "created_at")
    list_filter = ("is_active", "business")
    search_fields = ("name", "code", "business__name")
    ordering = ("business__name", "name", "pk")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "business",
        "lead_type",
        "status",
        "category",
        "first_name",
        "last_name",
        "email",
    )
    list_filter = ("business", "lead_type", "status", "category")
    search_fields = ("first_name", "last_name", "email", "phone", "company_name")
    ordering = ("-created_at",)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "business", "email", "phone", "is_active")
    search_fields = ("first_name", "last_name", "email", "phone", "company_name")
    list_filter = ("business", "is_active")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "business", "action_type", "actor", "lead", "client", "summary")
    list_filter = ("business", "action_type")
    search_fields = ("summary",)
