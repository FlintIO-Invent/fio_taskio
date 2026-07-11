from __future__ import annotations

from copy import deepcopy
from typing import Any

from django.db.models import Q
from django.urls import NoReverseMatch, reverse

from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.crm.models import BusinessService, Client, Lead

from .models import Business, BusinessBookingSettings, BusinessUser, UserOnboardingState
from .utils import OWNER_ADMIN_ROLES, can_use_module, membership_has_any_role

TASK_DEFINITIONS: dict[str, dict[str, Any]] = {
    "complete_business_profile": {
        "key": "complete_business_profile",
        "title": "Complete business profile",
        "description": "Add the basic contact, location, and business details for this workspace.",
        "cta_label": "Open Business Settings",
        "url_name": "business_settings",
        "prerequisites": [],
        "module_key": None,
        "target_selector": "[data-onboarding-target='business-settings']",
    },
    "add_first_service": {
        "key": "add_first_service",
        "title": "Add your first service",
        "description": "Create the first service your team can use for requests, bookings, and invoices.",
        "cta_label": "Add Service",
        "url_name": "business_service_create",
        "prerequisites": [],
        "module_key": None,
        "target_selector": "[data-onboarding-target='services']",
    },
    "set_availability": {
        "key": "set_availability",
        "title": "Set your availability",
        "description": "Add at least one weekly availability block for your workspace or team.",
        "cta_label": "Set Availability",
        "url_name": "business_booking_settings",
        "prerequisites": ["add_first_service"],
        "module_key": None,
        "future_module_key": "availability",
        "target_selector": "[data-onboarding-target='availability']",
    },
    "add_first_client": {
        "key": "add_first_client",
        "title": "Add your first client",
        "description": "Create a client record so requests, appointments, and invoices have a customer.",
        "cta_label": "Add Client",
        "url_name": "staff_client_create",
        "prerequisites": [],
        "module_key": None,
        "target_selector": "[data-onboarding-target='clients']",
    },
    "create_first_service_request": {
        "key": "create_first_service_request",
        "title": "Create your first service request",
        "description": "Capture a customer need as a service request in the current workspace.",
        "cta_label": "Create Service Request",
        "url_name": "staff_lead_create",
        "prerequisites": [],
        "module_key": None,
        "target_selector": "[data-onboarding-target='service-requests']",
    },
    "schedule_first_appointment": {
        "key": "schedule_first_appointment",
        "title": "Schedule your first appointment",
        "description": "Create an appointment so your team can track scheduled work.",
        "cta_label": "Schedule Appointment",
        "url_name": "appointment_create",
        "prerequisites": ["add_first_client", "add_first_service"],
        "module_key": "appointments",
        "target_selector": "[data-onboarding-target='appointments']",
    },
    "configure_online_booking": {
        "key": "configure_online_booking",
        "title": "Open or configure online booking",
        "description": "Enable or configure the public booking settings customers can use.",
        "cta_label": "Open Booking Settings",
        "url_name": "business_booking_settings",
        "prerequisites": ["add_first_service", "set_availability"],
        "module_key": "public_booking",
        "target_selector": "[data-onboarding-target='booking-settings']",
    },
    "create_first_invoice": {
        "key": "create_first_invoice",
        "title": "Create your first invoice",
        "description": "Create a draft invoice for a client in this workspace.",
        "cta_label": "Create Invoice",
        "url_name": "invoice_create",
        "prerequisites": ["add_first_client"],
        "module_key": "invoicing",
        "target_selector": "[data-onboarding-target='invoices']",
    },
    "send_or_download_invoice": {
        "key": "send_or_download_invoice",
        "title": "Send or download your first invoice",
        "description": "Send an invoice by email or move one into a sent or paid state.",
        "cta_label": "View Invoices",
        "url_name": "invoice_list",
        "prerequisites": ["create_first_invoice"],
        "module_key": "invoicing",
        "target_selector": "[data-onboarding-target='invoices']",
    },
}


JOURNEY_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "setup_business",
        "title": "Set Up My Business",
        "purpose": (
            "Get your workspace ready by completing your business profile, adding services, "
            "and setting availability."
        ),
        "tasks": (
            "complete_business_profile",
            "add_first_service",
            "set_availability",
        ),
    },
    {
        "key": "manage_clients",
        "title": "Start Managing Clients",
        "purpose": (
            "Learn how Motionmate helps you manage customers, service requests, "
            "and appointments."
        ),
        "tasks": (
            "add_first_client",
            "create_first_service_request",
            "schedule_first_appointment",
        ),
    },
    {
        "key": "booked_and_paid",
        "title": "Get Booked & Paid",
        "purpose": (
            "Explore online booking and invoicing so you can turn customer work into revenue."
        ),
        "tasks": (
            "configure_online_booking",
            "create_first_invoice",
            "send_or_download_invoice",
        ),
    },
)


def get_journey_definitions() -> list[dict[str, Any]]:
    return deepcopy(list(JOURNEY_DEFINITIONS))


def get_task_definitions() -> dict[str, dict[str, Any]]:
    return deepcopy(TASK_DEFINITIONS)


def user_can_view_onboarding(user, business: Business | None) -> bool:
    if business is None or not getattr(user, "is_authenticated", False):
        return False

    membership = (
        BusinessUser.objects.filter(
            user=user,
            business=business,
            is_active=True,
            business__is_active=True,
        )
        .select_related("business", "user")
        .first()
    )
    return membership_has_any_role(membership, OWNER_ADMIN_ROLES)


def get_or_create_user_onboarding_state(
    *,
    user,
    business: Business,
) -> tuple[UserOnboardingState, bool]:
    return UserOnboardingState.objects.get_or_create(user=user, business=business)


def add_skipped_onboarding_step(
    *,
    state: UserOnboardingState,
    task_key: str,
) -> UserOnboardingState:
    skipped_steps = deepcopy(state.skipped_steps or [])
    if isinstance(skipped_steps, dict):
        skipped_steps[task_key] = True
    elif isinstance(skipped_steps, list):
        if task_key not in skipped_steps:
            skipped_steps.append(task_key)
    else:
        skipped_steps = [task_key]

    state.skipped_steps = skipped_steps
    return state


def _has_business_profile(business: Business) -> bool:
    has_contact = bool((business.email or "").strip() or (business.phone or "").strip())
    has_location = bool(business.formatted_address_lines or (business.country or "").strip())
    required_fields = (
        business.name,
        business.timezone,
        business.currency,
        business.invoice_prefix,
    )
    return all(bool((value or "").strip()) for value in required_fields) and has_contact and has_location


def _has_active_service(business: Business) -> bool:
    return BusinessService.objects.filter(business=business, is_active=True).exists()


def _has_active_availability(business: Business) -> bool:
    return business.weekly_availability.filter(is_active=True).exists()


def _has_active_client(business: Business) -> bool:
    return (
        Client.objects.filter(business=business, is_active=True)
        .exclude(
            client_status__in=(
                Client.ClientStatus.INACTIVE,
                Client.ClientStatus.ARCHIVED,
            )
        )
        .exists()
    )


def _has_service_request(business: Business) -> bool:
    return Lead.objects.filter(business=business, lead_type=Lead.LeadType.REQUEST).exists()


def _has_appointment(business: Business) -> bool:
    return Appointment.objects.filter(business=business).exists()


def _has_configured_online_booking(business: Business) -> bool:
    try:
        settings = business.booking_settings
    except BusinessBookingSettings.DoesNotExist:
        return False

    has_public_text = any(
        (
            (settings.public_booking_instructions or "").strip(),
            (settings.cancellation_policy_text or "").strip(),
            (settings.reschedule_policy_text or "").strip(),
        )
    )
    has_non_default_rules = any(
        (
            settings.default_duration_minutes != 60,
            settings.minimum_notice_hours != 24,
            settings.maximum_days_ahead != 30,
            settings.buffer_minutes != 0,
            settings.confirmation_mode != BusinessBookingSettings.ConfirmationMode.REQUEST_ONLY,
        )
    )
    return bool(settings.booking_enabled or has_public_text or has_non_default_rules)


def _has_invoice(business: Business) -> bool:
    return Invoice.objects.filter(business=business).exists()


def _has_sent_or_downloaded_invoice(business: Business) -> bool:
    return Invoice.objects.filter(business=business).filter(
        Q(status__in=(Invoice.Status.SENT, Invoice.Status.PAID))
        | Q(email_send_count__gt=0)
        | Q(emailed_at__isnull=False)
    ).exists()


COMPLETION_CHECKS = {
    "complete_business_profile": _has_business_profile,
    "add_first_service": _has_active_service,
    "set_availability": _has_active_availability,
    "add_first_client": _has_active_client,
    "create_first_service_request": _has_service_request,
    "schedule_first_appointment": _has_appointment,
    "configure_online_booking": _has_configured_online_booking,
    "create_first_invoice": _has_invoice,
    "send_or_download_invoice": _has_sent_or_downloaded_invoice,
}


COMPLETION_SOURCES = {
    "complete_business_profile": "business_profile_fields",
    "add_first_service": "active_business_service_exists",
    "set_availability": "active_weekly_availability_exists",
    "add_first_client": "active_non_archived_client_exists",
    "create_first_service_request": "service_request_lead_exists",
    "schedule_first_appointment": "appointment_exists",
    "configure_online_booking": "booking_settings_configured_or_enabled",
    "create_first_invoice": "invoice_exists",
    "send_or_download_invoice": "sent_paid_or_emailed_invoice_exists",
}


def _is_step_skipped(skipped_steps, task_key: str) -> bool:
    if isinstance(skipped_steps, dict):
        return bool(skipped_steps.get(task_key))
    if isinstance(skipped_steps, (list, tuple, set)):
        return task_key in skipped_steps
    return False


def _task_status(
    *,
    task_key: str,
    business: Business,
    skipped_steps,
) -> dict[str, Any]:
    definition = deepcopy(TASK_DEFINITIONS[task_key])
    completion_check = COMPLETION_CHECKS[task_key]
    module_key = definition.get("module_key")
    module_allowed = can_use_module(business, module_key) if module_key else True
    locked = bool(module_key and not module_allowed)
    cta_url = ""
    url_name = definition.get("url_name")
    if url_name:
        try:
            cta_url = reverse(url_name)
        except NoReverseMatch:
            cta_url = ""

    return {
        **definition,
        "cta_url": cta_url,
        "effective_cta_label": definition["cta_label"],
        "effective_cta_url": cta_url,
        "completed": completion_check(business),
        "completion_source": COMPLETION_SOURCES[task_key],
        "skipped": _is_step_skipped(skipped_steps, task_key),
        "locked": locked,
        "module_allowed": module_allowed,
        "effective_target_selector": "" if locked else definition.get("target_selector", ""),
        "has_missing_prerequisites": False,
        "prerequisite_message": "",
        "prerequisite_cta_label": "",
        "prerequisite_cta_url": "",
        "recommended_previous_task_key": None,
    }


DEPENDENCY_MESSAGES = {
    "set_availability": "Add a service first so your availability can be connected to what you offer.",
    "schedule_first_appointment": (
        "Appointments work best after you have at least one client and service."
    ),
    "configure_online_booking": (
        "Online booking works best after you add services and set your availability."
    ),
    "create_first_invoice": "Invoices work best after you add a client.",
    "send_or_download_invoice": "Create an invoice first, then you can send or download it.",
}


def _prerequisite_fallback_task_key(
    *,
    task_key: str,
    flat_task_statuses: dict[str, dict[str, Any]],
) -> str | None:
    if task_key == "set_availability":
        return "add_first_service" if not flat_task_statuses["add_first_service"]["completed"] else None

    if task_key == "schedule_first_appointment":
        if not flat_task_statuses["add_first_client"]["completed"]:
            return "add_first_client"
        if not flat_task_statuses["add_first_service"]["completed"]:
            return "add_first_service"
        return None

    if task_key == "configure_online_booking":
        if not flat_task_statuses["add_first_service"]["completed"]:
            return "add_first_service"
        if not flat_task_statuses["set_availability"]["completed"]:
            return "set_availability"
        return None

    if task_key == "create_first_invoice":
        return "add_first_client" if not flat_task_statuses["add_first_client"]["completed"] else None

    if task_key == "send_or_download_invoice":
        return (
            "create_first_invoice"
            if not flat_task_statuses["create_first_invoice"]["completed"]
            else None
        )

    return None


def _apply_dependency_context(flat_task_statuses: dict[str, dict[str, Any]]) -> None:
    for task_key, task in flat_task_statuses.items():
        if task["completed"] or task["locked"]:
            continue

        fallback_task_key = _prerequisite_fallback_task_key(
            task_key=task_key,
            flat_task_statuses=flat_task_statuses,
        )
        if fallback_task_key is None:
            continue

        fallback_task = flat_task_statuses[fallback_task_key]
        task["has_missing_prerequisites"] = True
        task["prerequisite_message"] = DEPENDENCY_MESSAGES[task_key]
        task["prerequisite_cta_label"] = fallback_task["cta_label"]
        task["prerequisite_cta_url"] = fallback_task["cta_url"]
        task["recommended_previous_task_key"] = fallback_task_key
        task["effective_cta_label"] = fallback_task["cta_label"]
        task["effective_cta_url"] = fallback_task["cta_url"]
        task["effective_target_selector"] = fallback_task["target_selector"]


def _progress_for_tasks(tasks: list[dict[str, Any]]) -> dict[str, int]:
    total = len(tasks)
    progress_count = sum(1 for task in tasks if task["completed"])
    percent_complete = round((progress_count / total) * 100) if total else 0
    return {
        "progress_count": progress_count,
        "total_task_count": total,
        "percent_complete": percent_complete,
    }


def _selected_journey_step_context(
    *,
    selected_journey: dict[str, Any] | None,
    last_step_key: str | None,
) -> dict[str, Any]:
    if selected_journey is None:
        return {
            "current_task": None,
            "current_step_key": None,
            "current_step_index": None,
            "current_step_number": 0,
            "current_step_percent": 0,
            "selected_journey_task_count": 0,
            "previous_step_key": None,
            "next_step_key": None,
            "selected_journey_complete": False,
        }

    tasks = selected_journey["tasks"]
    total = len(tasks)
    selected_journey_complete = bool(total and all(task["completed"] for task in tasks))
    if selected_journey_complete:
        return {
            "current_task": None,
            "current_step_key": None,
            "current_step_index": None,
            "current_step_number": total,
            "current_step_percent": 100,
            "selected_journey_task_count": total,
            "previous_step_key": tasks[-1]["key"] if tasks else None,
            "next_step_key": None,
            "selected_journey_complete": True,
        }

    task_keys = [task["key"] for task in tasks]
    current_step_index = 0
    if last_step_key in task_keys:
        current_step_index = task_keys.index(last_step_key)
    else:
        for index, task in enumerate(tasks):
            if not task["completed"] and not task["skipped"]:
                current_step_index = index
                break

    current_task = tasks[current_step_index] if tasks else None
    current_step_number = current_step_index + 1 if current_task else 0
    return {
        "current_task": current_task,
        "current_step_key": current_task["key"] if current_task else None,
        "current_step_index": current_step_index if current_task else None,
        "current_step_number": current_step_number,
        "current_step_percent": round((current_step_number / total) * 100) if total else 0,
        "selected_journey_task_count": total,
        "previous_step_key": tasks[current_step_index - 1]["key"] if current_step_index > 0 else None,
        "next_step_key": (
            tasks[current_step_index + 1]["key"] if current_step_index + 1 < total else None
        ),
        "selected_journey_complete": False,
    }


def get_onboarding_status(
    *,
    user,
    business: Business,
    state: UserOnboardingState | None = None,
) -> dict[str, Any]:
    if state is None:
        state = UserOnboardingState.objects.filter(user=user, business=business).first()

    selected_journey_key = state.selected_journey if state else None
    skipped_steps = state.skipped_steps if state else []
    flat_task_statuses = {
        task_key: _task_status(
            task_key=task_key,
            business=business,
            skipped_steps=skipped_steps,
        )
        for task_key in TASK_DEFINITIONS
    }
    _apply_dependency_context(flat_task_statuses)

    available_journeys: list[dict[str, Any]] = []
    selected_journey = None
    for journey_definition in JOURNEY_DEFINITIONS:
        tasks = [deepcopy(flat_task_statuses[task_key]) for task_key in journey_definition["tasks"]]
        journey_status = {
            **deepcopy(journey_definition),
            "tasks": tasks,
            **_progress_for_tasks(tasks),
        }
        available_journeys.append(journey_status)
        if journey_status["key"] == selected_journey_key:
            selected_journey = journey_status

    all_tasks = list(flat_task_statuses.values())
    step_context = _selected_journey_step_context(
        selected_journey=selected_journey,
        last_step_key=state.last_step_key if state else None,
    )
    visible = user_can_view_onboarding(user, business)
    completed_welcome = bool(state and state.completed_welcome)
    dismissed_at = state.dismissed_at if state else None
    should_auto_show_welcome = (
        visible
        and not selected_journey_key
        and not completed_welcome
        and dismissed_at is None
    )
    return {
        "state": state,
        "available_journeys": available_journeys,
        "selected_journey": selected_journey,
        "selected_journey_key": selected_journey_key,
        "selected_journey_missing": bool(selected_journey_key and selected_journey is None),
        "tasks": all_tasks,
        "visible": visible,
        "completed_welcome": completed_welcome,
        "dismissed_at": dismissed_at,
        "should_auto_show_welcome": should_auto_show_welcome,
        "auto_show_welcome": should_auto_show_welcome,
        "last_step_key": state.last_step_key if state else None,
        **step_context,
        **_progress_for_tasks(all_tasks),
    }
