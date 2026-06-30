from .utils import (
    APPOINTMENT_MANAGE_ROLES,
    APPOINTMENT_VIEW_ROLES,
    BILLING_MANAGE_ROLES,
    BILLING_VIEW_ROLES,
    BOOKING_AVAILABILITY_MANAGE_ROLES,
    CLIENT_MANAGE_ROLES,
    LEAD_MANAGE_ROLES,
    OWNER_ADMIN_ROLES,
    business_has_active_subscription,
    business_is_trialing,
    can_use_module,
    get_business_subscription,
    get_current_business,
    get_current_business_membership,
    membership_has_any_role,
)


def current_business(request):
    business = get_current_business(request)
    membership = get_current_business_membership(request)
    subscription = get_business_subscription(business)
    current_plan = subscription.plan if subscription is not None else None

    module_access = {
        "invoicing": can_use_module(business, "invoicing"),
        "appointments": can_use_module(business, "appointments"),
        "public_booking": can_use_module(business, "public_booking"),
        "public_request_form": can_use_module(business, "public_booking"),
    }
    role_access = {
        "can_manage_business_settings": membership_has_any_role(membership, OWNER_ADMIN_ROLES),
        "can_manage_team": membership_has_any_role(membership, OWNER_ADMIN_ROLES),
        "can_manage_subscription": membership_has_any_role(membership, ("owner",)),
        "can_manage_clients": membership_has_any_role(membership, CLIENT_MANAGE_ROLES),
        "can_manage_leads": membership_has_any_role(membership, LEAD_MANAGE_ROLES),
        "can_view_appointments": membership_has_any_role(membership, APPOINTMENT_VIEW_ROLES),
        "can_manage_appointments": membership_has_any_role(membership, APPOINTMENT_MANAGE_ROLES),
        "can_manage_booking_availability": membership_has_any_role(
            membership,
            BOOKING_AVAILABILITY_MANAGE_ROLES,
        ),
        "can_view_invoices": membership_has_any_role(membership, BILLING_VIEW_ROLES),
        "can_manage_invoices": membership_has_any_role(membership, BILLING_MANAGE_ROLES),
        "can_manage_services": membership_has_any_role(membership, OWNER_ADMIN_ROLES),
    }

    return {
        "current_business": business,
        "current_business_membership": membership,
        "current_subscription": subscription,
        "current_plan": current_plan,
        "subscription_has_access": business_has_active_subscription(business),
        "subscription_is_trialing": business_is_trialing(business),
        "module_access": module_access,
        "role_access": role_access,
    }
