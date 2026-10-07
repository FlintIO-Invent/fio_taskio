import json

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from .models import (
    BillingProviderWebhookEvent,
    Business,
    BusinessBookingSettings,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    SubscriptionNotification,
    UserOnboardingState,
    WeeklyAvailability,
)

admin.site.site_header = "Motionmate Administration"
admin.site.site_title = "Motionmate Admin"
admin.site.index_title = "Motionmate Administration"


class LogisticsApplicationLinkFilter(admin.SimpleListFilter):
    title = "Logistics application"
    parameter_name = "logistics_application_link"

    def lookups(self, request, model_admin):
        return (("linked", "Linked"), ("unlinked", "Unlinked"))

    def queryset(self, request, queryset):
        if self.value() in {"linked", "unlinked"}:
            return queryset.filter(logistics_application__isnull=self.value() == "unlinked")
        return queryset


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    deletion_workflow_notice = (
        "Businesses cannot be deleted in Django Admin. Use the controlled "
        "business closure and purge workflow so related records can be reviewed safely."
    )
    list_display = (
        "name",
        "slug",
        "vertical",
        "logistics_parcel_count",
        "logistics_shipment_count",
        "logistics_application_link",
        "subscription_plan",
        "subscription_status",
        "email",
        "country",
        "currency",
        "timezone",
        "is_active",
        "updated_at",
    )
    list_filter = ("vertical", LogisticsApplicationLinkFilter, "is_active", "currency", "country")
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
    readonly_fields = ("deletion_workflow_guidance", "logistics_resource_summary")

    def get_queryset(self, request):
        from apps.logistics.models import Parcel, Shipment

        def tenant_count(model):
            counts = (
                model.objects.filter(business_id=OuterRef("pk"))
                .order_by()
                .values("business_id")
                .annotate(total=Count("pk"))
                .values("total")
            )
            return Coalesce(Subquery(counts, output_field=IntegerField()), Value(0))

        return (
            super()
            .get_queryset(request)
            .select_related("subscription__plan", "logistics_application")
            .annotate(_parcel_count=tenant_count(Parcel), _shipment_count=tenant_count(Shipment))
        )

    @admin.display(description="Parcels", ordering="_parcel_count")
    def logistics_parcel_count(self, obj):
        return obj._parcel_count if obj.vertical == Business.Vertical.LOGISTICS else "—"

    @admin.display(description="Shipments", ordering="_shipment_count")
    def logistics_shipment_count(self, obj):
        return obj._shipment_count if obj.vertical == Business.Vertical.LOGISTICS else "—"

    @admin.display(description="Logistics application")
    def logistics_application_link(self, obj):
        application = getattr(obj, "logistics_application", None)
        return str(application.pk) if application else "—"

    @admin.display(description="Logistics resources (internal review only)")
    def logistics_resource_summary(self, obj=None):
        if obj is None or obj.pk is None or obj.vertical != Business.Vertical.LOGISTICS:
            return "—"
        from apps.logistics.usage import logistics_operational_summary

        return json.dumps(logistics_operational_summary(business=obj), sort_keys=True, indent=2)

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="Business closure and deletion")
    def deletion_workflow_guidance(self, obj: Business | None = None) -> str:
        return self.deletion_workflow_notice

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


class CommercialPlanAdminForm(forms.ModelForm):
    class Meta:
        model = ClarivoPlan
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("family") == ClarivoPlan.Family.LOGISTICS and cleaned.get("is_active"):
            from apps.logistics.billing import validate_offering_activation

            from .stripe_config import StripeConfigurationError

            candidate = ClarivoPlan(
                family=cleaned["family"],
                slug=cleaned.get("slug"),
                price_yearly=cleaned.get("price_yearly"),
                regional_prices=cleaned.get("regional_prices"),
            )
            try:
                validate_offering_activation(candidate)
            except StripeConfigurationError as exc:
                raise ValidationError(str(exc)) from exc
        return cleaned


@admin.register(ClarivoPlan)
class ClarivoPlanAdmin(admin.ModelAdmin):
    form = CommercialPlanAdminForm
    list_display = (
        "name",
        "slug",
        "price_monthly",
        "price_yearly",
        "is_recommended",
        "is_active",
        "allow_invoicing",
        "allow_appointments",
        "allow_public_booking",
    )
    list_filter = (
        "is_active",
        "is_recommended",
        "allow_invoicing",
        "allow_appointments",
        "allow_public_booking",
    )
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(BusinessSubscription)
class BusinessSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "plan",
        "status",
        "logistics_approval_review_required",
        "provisioning_source",
        "payment_provider",
        "billing_interval",
        "billing_currency",
        "current_period_start",
        "current_period_end",
        "cancel_at_period_end",
        "past_due_since",
        "grace_period_ends_at",
        "updated_at",
    )
    list_filter = (
        "status",
        "logistics_approval_review_required",
        "provisioning_source",
        "payment_provider",
        "billing_interval",
        "cancel_at_period_end",
        "plan",
    )
    search_fields = (
        "business__name",
        "business__slug",
        "plan__name",
        "provider_customer_id",
        "provider_subscription_id",
        "provider_checkout_session_id",
    )
    autocomplete_fields = ("business", "plan")
    list_select_related = ("business", "plan")


@admin.register(BillingProviderWebhookEvent)
class BillingProviderWebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "event_id",
        "event_type",
        "object_id",
        "status",
        "attempt_count",
        "received_at",
        "processed_at",
    )
    list_filter = ("provider", "status", "event_type", "livemode")
    search_fields = ("event_id", "event_type", "object_id", "last_error")
    readonly_fields = (
        "provider",
        "event_id",
        "event_type",
        "object_id",
        "api_version",
        "livemode",
        "attempt_count",
        "received_at",
        "processed_at",
        "payload_summary",
        "last_error",
        "created_at",
        "updated_at",
    )


@admin.register(SubscriptionNotification)
class SubscriptionNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "notification_type",
        "business",
        "subscription",
        "recipient_email",
        "status",
        "attempt_count",
        "available_at",
        "sent_at",
        "source_provider_event_id",
    )
    list_filter = ("notification_type", "status", "available_at", "sent_at")
    search_fields = (
        "business__name",
        "business__slug",
        "recipient_email",
        "deduplication_key",
        "source_provider_event_id",
        "last_error",
    )
    autocomplete_fields = ("business", "subscription", "recipient_user")
    list_select_related = ("business", "subscription", "recipient_user")
    readonly_fields = (
        "business",
        "subscription",
        "recipient_email",
        "recipient_user",
        "notification_type",
        "deduplication_key",
        "status",
        "available_at",
        "attempt_count",
        "last_attempt_at",
        "sent_at",
        "last_error",
        "source_provider_event_id",
        "context_summary",
        "created_at",
        "updated_at",
    )


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


@admin.register(UserOnboardingState)
class UserOnboardingStateAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "business",
        "selected_journey",
        "completed_welcome",
        "dismissed_at",
        "last_step_key",
        "updated_at",
    )
    list_filter = ("selected_journey", "completed_welcome", "business")
    search_fields = ("user__email", "business__name", "business__slug", "last_step_key")
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
