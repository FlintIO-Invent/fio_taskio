from django.contrib import admin

from .models import (
    Business,
    BusinessBookingSettings,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    WeeklyAvailability,
)

admin.site.site_header = "Motionmate Administration"
admin.site.site_title = "Motionmate Admin"
admin.site.index_title = "Motionmate Administration"


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
    search_fields = (
        "name",
        "slug",
        "email",
        "phone",
        "business_type",
        "city",
        "region",
        "postal_code",
    )
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


@admin.register(BusinessBookingSettings)
class BusinessBookingSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "booking_enabled",
        "confirmation_mode",
        "default_duration_minutes",
        "minimum_notice_hours",
        "maximum_days_ahead",
        "buffer_minutes",
        "updated_at",
    )
    list_filter = ("booking_enabled", "confirmation_mode")
    search_fields = ("business__name", "business__slug")
    autocomplete_fields = ("business",)
    list_select_related = ("business",)


@admin.register(WeeklyAvailability)
class WeeklyAvailabilityAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "staff_member",
        "day_of_week",
        "start_time",
        "end_time",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "day_of_week", "business")
    search_fields = ("business__name", "business__slug", "staff_member__email")
    autocomplete_fields = ("business", "staff_member")
    list_select_related = ("business", "staff_member")


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


@admin.register(BusinessInvitation)
class BusinessInvitationAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "business",
        "role",
        "status",
        "invited_by",
        "expires_at",
        "accepted_by",
        "updated_at",
    )
    list_filter = ("status", "role", "business")
    search_fields = ("email", "business__name", "business__slug", "token")
    autocomplete_fields = ("business", "invited_by", "accepted_by")
    list_select_related = ("business", "invited_by", "accepted_by")
