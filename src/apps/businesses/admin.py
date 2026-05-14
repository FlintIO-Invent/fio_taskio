from django.contrib import admin

from .models import Business, BusinessUser


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "email",
        "country",
        "currency",
        "timezone",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "currency", "country")
    search_fields = ("name", "slug", "email", "phone")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(BusinessUser)
class BusinessUserAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "business",
        "role",
        "is_active",
        "updated_at",
    )
    list_filter = ("role", "is_active", "business")
    search_fields = ("user__email", "business__name", "business__slug")
    autocomplete_fields = ("user", "business")
    list_select_related = ("user", "business")
