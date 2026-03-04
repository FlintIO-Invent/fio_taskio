from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import TaskIOUser

@admin.register(TaskIOUser)
class EmployeeUserAdmin(UserAdmin):
    model = TaskIOUser
    list_display = ('email', 'first_name', 'last_name', 'incorporation_status', 'assigned_location', 'is_active', 'is_staff', 'is_superuser' )
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
