from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from apps.businesses.utils import get_current_business

from .enrollment import issue_enrollment_link, revoke_enrollment_links
from .forms import ApplicationReviewForm
from .models import (
    LogisticsApplication,
    LogisticsApplicationDecision,
    LogisticsEnrollmentToken,
    Parcel,
    ParcelEvent,
    Shipment,
)
from .parcel_services import parcels_for_business
from .services import reevaluate_application, review_application


class DecisionHistoryInline(admin.TabularInline):
    model = LogisticsApplicationDecision
    fields = (
        "application_revision",
        "result",
        "evaluated_result",
        "reason_codes",
        "evaluated_at",
        "rule_version",
        "source",
        "actor_identifier",
        "override_reason",
    )
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("logistics.change_logisticsapplication")


class EnrollmentHistoryInline(DecisionHistoryInline):
    model = LogisticsEnrollmentToken
    fields = (
        "application_revision",
        "created_at",
        "expires_at",
        "used_at",
        "revoked_at",
        "issued_by",
    )
    readonly_fields = fields


@admin.register(LogisticsApplication)
class LogisticsApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "business_name",
        "country",
        "status",
        "revision",
        "monthly_parcel_estimate",
        "evaluated_at",
    )
    list_filter = ("status", "country", "operation_type")
    search_fields = ("business_name", "trading_name", "email", "registration_number")
    readonly_fields = LogisticsApplication.DECISION_FIELDS + (
        "normalized_email",
        "normalized_business_name",
        "normalized_registration_number",
        "created_at",
        "updated_at",
        "business",
        "enrolled_user",
        "converted_at",
        "converted_revision",
    )
    inlines = (DecisionHistoryInline, EnrollmentHistoryInline)
    change_form_template = "admin/logistics/application_change_form.html"

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None and obj.status == LogisticsApplication.Status.WITHDRAWN:
            return fields + LogisticsApplication.MATERIAL_FIELDS
        return fields

    def get_urls(self):
        return [
            path(
                "<uuid:application_id>/enrollment/",
                self.admin_site.admin_view(self.enrollment_view),
                name="logistics_logisticsapplication_enrollment",
            ),
            path(
                "<uuid:application_id>/review/",
                self.admin_site.admin_view(self.review_view),
                name="logistics_logisticsapplication_review",
            ),
        ] + super().get_urls()

    @method_decorator(never_cache)
    def enrollment_view(self, request, application_id):
        application = get_object_or_404(LogisticsApplication, pk=application_id)
        if not self.has_change_permission(request, application):
            raise PermissionDenied
        link = error = None
        if request.method == "POST":
            try:
                if request.POST.get("action") == "revoke":
                    revoke_enrollment_links(application.pk, actor=request.user)
                    self.message_user(request, "Enrollment links revoked.", messages.SUCCESS)
                else:
                    secret = issue_enrollment_link(
                        application.pk,
                        actor=request.user,
                        expected_revision=int(request.POST.get("revision", "0")),
                    )
                    link = request.build_absolute_uri(
                        reverse("logistics_application_enroll", args=[secret])
                    )
            except (ValidationError, ValueError) as exc:
                error = str(exc)
        response = TemplateResponse(
            request,
            "admin/logistics/application_enrollment.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "Logistics enrollment authorization",
                "application": application,
                "enrollment_link": link,
                "error": error,
            },
        )
        response["Referrer-Policy"] = "no-referrer"
        return response

    def review_view(self, request, application_id):
        application = get_object_or_404(LogisticsApplication, pk=application_id)
        if not self.has_change_permission(request, application):
            raise PermissionDenied
        form = ApplicationReviewForm(
            request.POST if request.method == "POST" else None,
            initial={"expected_revision": application.revision},
        )
        if request.method == "POST" and form.is_valid():
            try:
                if form.cleaned_data["action"] == "REEVALUATE":
                    reevaluate_application(
                        application.pk,
                        expected_revision=form.cleaned_data["expected_revision"],
                        actor=request.user,
                    )
                else:
                    review_application(
                        application.pk,
                        result=form.cleaned_data["action"],
                        actor=request.user,
                        reason=form.cleaned_data["reason"],
                        expected_revision=form.cleaned_data["expected_revision"],
                    )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                self.log_change(
                    request, application, f"Application decision: {form.cleaned_data['action']}"
                )
                self.message_user(request, "Application decision recorded.", messages.SUCCESS)
                return redirect(
                    reverse("admin:logistics_logisticsapplication_change", args=[application.pk])
                )
        return TemplateResponse(
            request,
            "admin/logistics/application_review.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "Review Logistics application",
                "application": application,
                "form": form,
            },
        )


@admin.register(LogisticsApplicationDecision)
class LogisticsApplicationDecisionAdmin(admin.ModelAdmin):
    list_display = (
        "application",
        "application_revision",
        "result",
        "source",
        "evaluated_at",
        "actor_identifier",
    )
    list_filter = ("result", "source")
    readonly_fields = tuple(field.name for field in LogisticsApplicationDecision._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ParcelInspectionAdmin(admin.ModelAdmin):
    """Inspection only; staff mutations must use the domain workflow."""

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        try:
            parcels = parcels_for_business(
                business=get_current_business(request), actor=request.user
            )
        except PermissionDenied:
            return super().get_queryset(request).none()
        if self.model is Parcel:
            return super().get_queryset(request).filter(pk__in=parcels.values("pk"))
        return (
            super()
            .get_queryset(request)
            .filter(
                business=get_current_business(request),
                parcel__in=parcels,
            )
        )


@admin.register(Parcel)
class ParcelAdmin(ParcelInspectionAdmin):
    list_display = (
        "tracking_code",
        "client",
        "origin",
        "destination",
        "current_status",
        "shipment",
        "created_at",
    )
    list_filter = (("business", admin.RelatedOnlyFieldListFilter), "current_status", "created_at")
    search_fields = ("tracking_code", "internal_reference")
    list_select_related = ("client", "business", "shipment")


@admin.register(ParcelEvent)
class ParcelEventAdmin(ParcelInspectionAdmin):
    list_display = ("parcel", "event_type", "status", "timestamp", "actor", "location")
    list_filter = (
        ("business", admin.RelatedOnlyFieldListFilter),
        "event_type",
        "status",
        "timestamp",
    )
    search_fields = ("parcel__tracking_code", "location")
    list_select_related = ("parcel", "actor", "business")


@admin.register(Shipment)
class ShipmentAdmin(ParcelInspectionAdmin):
    list_display = (
        "reference",
        "origin",
        "destination",
        "status",
        "departure_at",
        "estimated_arrival_at",
    )
    list_filter = (("business", admin.RelatedOnlyFieldListFilter), "status", "created_at")
    search_fields = ("reference",)

    def get_queryset(self, request):
        from .shipment_services import shipments_for_business

        try:
            shipments = shipments_for_business(
                business=get_current_business(request), actor=request.user
            )
        except PermissionDenied:
            return self.model.objects.none()
        return shipments
