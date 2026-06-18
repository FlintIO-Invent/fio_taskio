from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import SaaSUserProfile, TaskIOUser


@admin.register(TaskIOUser)
class EmployeeUserAdmin(UserAdmin):
    model = TaskIOUser
    list_display = (
        'email',
        'first_name',
        'last_name',
        'incorporation_status',
        'assigned_location',
        'is_active',
        'is_staff',
        'is_superuser',
    )
    list_filter = ('incorporation_status', 'assigned_location')
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'date_of_birth')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'incorporation_status', 'assigned_location')}),
        ('Important dates', {'fields': ('last_login',)}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'date_of_birth', 'incorporation_status', 'assigned_location', 'password1', 'password2'),
        }),
    )
    search_fields = ('email',)
    ordering = ('email',)


@admin.register(SaaSUserProfile)
class SaaSUserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "workspace_name",
        "billing_email",
        "currency_code",
        "invoice_prefix",
        "updated_at",
    )
    search_fields = ("user__email", "user__company_name", "workspace_name", "billing_email")
    list_filter = ("currency_code", "show_company_address_on_invoice", "show_tax_id_on_invoice")
