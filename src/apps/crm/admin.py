from django.contrib import admin
from .models import ServiceCategory, Lead, Client, ActivityLog

# @admin.register(ServiceCategory)
# class ServiceCategoryAdmin(admin.ModelAdmin):
#     list_display = ('first_name', 'last_name', "is_active", "created_at")
#     list_filter = ("is_active",)
#     search_fields = ('first_name')

# @admin.register(Lead)
# class LeadAdmin(admin.ModelAdmin):
#     list_display = ("created_at", "lead_type", "status", "category", "first_name", "last_name", "email")
#     list_filter = ("lead_type", "status", "category")
#     search_fields = ("first_name", "last_name", "email", "phone")
#     ordering = ("-created_at",)

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email", "phone", "is_active")
    search_fields = ("first_name", "last_name", "email", "phone")
    list_filter = ("is_active",)

# @admin.register(ActivityLog)
# class ActivityLogAdmin(admin.ModelAdmin):
#     list_display = ("created_at", "action_type", "actor", "lead", "client", "summary")
#     list_filter = ("action_type",)
#     search_fields = ("summary",)