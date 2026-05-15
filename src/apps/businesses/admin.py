from django.contrib import admin

from .models import Business, BusinessSubscription, BusinessUser, ClarivoPlan


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "subscription_plan",
        "subscription_status",
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

    @admin.display(description="Plan")
    def subscription_plan(self, obj: Business) -> str:
        subscription = getattr(obj, "subscription", None)
        if subscription is None:
            return "-"
        return subscription.plan.name

    @admin.display(description="Subscription")
    def subscription_status(self, obj: Business) -> str:
        subscription = getattr(obj, "subscription", None)
        if subscription is None:
            return "-"
        return subscription.get_status_display()


@admin.register(ClarivoPlan)
class ClarivoPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "price_monthly",
        "price_yearly",
        "is_active",
        "allow_invoicing",
        "allow_appointments",
        "allow_memberships",
    )
    list_filter = (
        "is_active",
        "allow_invoicing",
        "allow_appointments",
        "allow_memberships",
        "allow_public_booking",
        "allow_public_request_form",
    )
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(BusinessSubscription)
class BusinessSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "plan",
        "status",
        "current_period_start",
        "current_period_end",
        "cancel_at_period_end",
        "updated_at",
    )
    list_filter = ("status", "cancel_at_period_end", "plan")
    search_fields = ("business__name", "business__slug", "plan__name")
    autocomplete_fields = ("business", "plan")
    list_select_related = ("business", "plan")


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
