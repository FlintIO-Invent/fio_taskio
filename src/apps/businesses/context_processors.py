from .utils import (
    business_has_active_subscription,
    business_is_trialing,
    can_use_module,
    get_business_subscription,
    get_current_business,
)


def current_business(request):
    business = get_current_business(request)
    subscription = get_business_subscription(business)
    current_plan = subscription.plan if subscription is not None else None

    module_access = {
        "invoicing": can_use_module(business, "invoicing"),
        "appointments": can_use_module(business, "appointments"),
        "memberships": can_use_module(business, "memberships"),
        "public_booking": can_use_module(business, "public_booking"),
        "public_request_form": can_use_module(business, "public_request_form"),
    }

    return {
        "current_business": business,
        "current_subscription": subscription,
        "current_plan": current_plan,
        "subscription_has_access": business_has_active_subscription(business),
        "subscription_is_trialing": business_is_trialing(business),
        "module_access": module_access,
    }
