"""Read-only Services projections. Booking and billing writers remain unchanged."""

from functools import wraps

from django import forms
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Case, CharField, Count, Exists, F, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Trim
from django.urls import reverse

from apps.businesses.utils import (
    business_module_required,
    can_use_module,
    can_view_module,
    get_current_business,
)
from apps.crm.models import BusinessService, Client, Lead

from .models import Appointment

PUBLIC_SOURCES = (Lead.RequestSource.PUBLIC_BOOKING, Lead.RequestSource.PUBLIC_REQUEST)
SOURCE_CHOICES = (("online", "Online"), ("internal", "Internal"), ("unknown", "Unspecified"))
STATE_CHOICES = (("needs_follow_up", "Needs follow-up"), *Appointment.Status.choices)


def navigation_context(request):
    business = get_current_business(request)
    return {
        "services_workspace_access": (
            can_view_module(business, "appointments")
            or can_view_module(business, "service_requests")
        ),
        "services_request_access": can_view_module(business, "service_requests"),
        "services_request_write_access": can_use_module(business, "service_requests"),
    }


def workspace_read_required(view):
    """Only the list shell accepts request entitlement; mutation guards stay intact."""
    appointment_read = business_module_required("appointments", access="read")(view)

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        business = request.current_business
        if can_view_module(business, "service_requests"):
            return view(request, *args, **kwargs)
        return appointment_read(request, *args, **kwargs)

    return wrapped


def unlinked_requests(queryset):
    # EXISTS avoids multiplying rows and preserves legitimate multiple appointments.
    linked = Appointment.objects.filter(
        business_id=OuterRef("business_id"), source_lead_id=OuterRef("pk")
    )
    return queryset.annotate(_workspace_linked=Exists(linked)).filter(_workspace_linked=False)


def follow_up_requests(business):
    return unlinked_requests(
        Lead.objects.filter(
            business=business,
            lead_type=Lead.LeadType.REQUEST,
            is_active=True,
            status__in=(Lead.Status.NEW, Lead.Status.CONTACTED),
        )
    )


class WorkspaceFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Search", max_length=160)
    state = forms.ChoiceField(required=False, choices=(("", "All states"), *STATE_CHOICES))
    source = forms.ChoiceField(required=False, choices=(("", "All sources"), *SOURCE_CHOICES))
    classification = forms.ChoiceField(
        required=False,
        label="Client classification",
        choices=(("", "All classifications"), *Client.ClientStatus.choices, ("unknown", "Unknown")),
    )
    staff = forms.ModelChoiceField(queryset=get_user_model().objects.none(), required=False)
    service = forms.ModelChoiceField(queryset=BusinessService.objects.none(), required=False)

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["staff"].queryset = (
            get_user_model()
            .objects.filter(business_memberships__business=business)
            .distinct()
            .order_by("first_name", "last_name", "pk")
        )
        self.fields["service"].queryset = BusinessService.objects.filter(business=business)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )


def _source_expression(field):
    return Case(
        When(**{f"{field}__in": PUBLIC_SOURCES}, then=Value("online")),
        When(**{field: Lead.RequestSource.STAFF}, then=Value("internal")),
        default=Value("unknown"),
        output_field=CharField(),
    )


def _classified_requests(queryset):
    # A request has no durable Client FK. Only display a classification when its
    # email identifies exactly one tenant Client. Never use this projection to write.
    matches = (
        Client.objects.filter(
            business_id=OuterRef("business_id"), email__iexact=Trim(OuterRef("email"))
        )
        .exclude(email="")
        .order_by("pk")
    )
    counts = matches.order_by().values("business_id").annotate(total=Count("pk"))
    return queryset.annotate(_workspace_matches=Subquery(counts.values("total")[:1])).annotate(
        _workspace_classification=Case(
            When(_workspace_matches=1, then=Subquery(matches.values("client_status")[:1])),
            default=Value(""),
            output_field=CharField(),
        ),
        _workspace_client_id=Case(
            When(_workspace_matches=1, then=Subquery(matches.values("pk")[:1])),
            default=None,
        ),
    )


def _request_service_label(lead):
    if lead.requested_service_id and lead.requested_service.business_id == lead.business_id:
        return lead.requested_service.name
    if lead.category_id and lead.category.business_id in (None, lead.business_id):
        return lead.category.name
    return "Not set"


def workspace_context(request, appointments):
    business = request.current_business
    data = request.GET.copy()
    if "state" not in data and data.get("status"):
        data["state"] = data["status"]  # Existing bookmarked status filters.
    form = WorkspaceFilterForm(data, business=business)
    appointment_access = can_view_module(business, "appointments")
    appointments = appointments if appointment_access else appointments.none()
    requests = follow_up_requests(business).select_related("category", "requested_service")
    if not can_view_module(business, "service_requests"):
        requests = requests.none()
    appointments = appointments.annotate(
        _workspace_source=_source_expression("source_lead__request_source"),
        _workspace_classification=F("client__client_status"),
    )
    requests = _classified_requests(requests).annotate(
        _workspace_source=_source_expression("request_source")
    )
    if form.is_valid():
        filters = form.cleaned_data
        if state := filters["state"]:
            if state == "needs_follow_up":
                appointments = appointments.none()
            else:
                appointments = appointments.filter(status=state)
                requests = requests.none()
        if source := filters["source"]:
            appointments = appointments.filter(_workspace_source=source)
            requests = requests.filter(_workspace_source=source)
        if classification := filters["classification"]:
            classification = "" if classification == "unknown" else classification
            appointments = appointments.filter(_workspace_classification=classification)
            requests = requests.filter(_workspace_classification=classification)
        if staff := filters["staff"]:
            appointments = appointments.filter(staff_member=staff)
            requests = requests.none()  # Preferred staff is only free text on requests.
        if service := filters["service"]:
            appointments = appointments.filter(service=service)
            requests = requests.filter(requested_service=service)
        if query := filters["q"]:
            appointments = appointments.filter(
                Q(title__icontains=query)
                | Q(service_name__icontains=query)
                | Q(client__first_name__icontains=query)
                | Q(client__last_name__icontains=query)
                | Q(client__company_name__icontains=query)
                | Q(client__email__icontains=query)
            )
            requests = requests.filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(company_name__icontains=query)
                | Q(email__icontains=query)
                | Q(phone__icontains=query)
                | Q(requested_service__business=business, requested_service__name__icontains=query)
            )
    else:
        appointments, requests = appointments.none(), requests.none()

    classifications = dict(Client.ClientStatus.choices)
    sources = dict(SOURCE_CHOICES)
    rows = []
    for appointment in appointments:
        rows.append(
            {
                "kind": "appointment",
                "pk": appointment.pk,
                "title": appointment.title,
                "url": reverse("appointment_detail", args=[appointment.pk]),
                "client_name": str(appointment.client),
                "client_id": appointment.client_id,
                "classification": classifications.get(
                    appointment._workspace_classification, "Unknown"
                ),
                "source": sources[appointment._workspace_source],
                "service": appointment.service_name or "Not set",
                "staff": appointment.staff_member,
                "start": appointment.start_time,
                "end": appointment.end_time,
                "state": appointment.get_status_display(),
                "badge": appointment.status_badge_class,
                "sort": (1, appointment.start_time, appointment.pk),
            }
        )
    for lead in requests:
        rows.append(
            {
                "kind": "request",
                "pk": lead.pk,
                "title": str(lead),
                "url": reverse("staff_lead_detail", args=[lead.pk]),
                "client_name": lead.company_name or str(lead),
                "client_id": lead._workspace_client_id,
                "classification": classifications.get(lead._workspace_classification, "Unknown"),
                "source": sources[lead._workspace_source],
                "service": _request_service_label(lead),
                "preferred_start": lead.preferred_start_time,
                "state": "Needs follow-up",
                "request_status": lead.get_status_display(),
                "badge": "badge-phoenix-warning",
                "sort": (0, lead.created_at, lead.pk),
            }
        )
    rows.sort(key=lambda row: row["sort"])
    params = request.GET.copy()
    params.pop("page", None)
    return {
        "workspace_form": form,
        "workspace_page": Paginator(rows, 50).get_page(request.GET.get("page")),
        "workspace_query": params.urlencode(),
        "workspace_appointment_access": appointment_access,
    }
