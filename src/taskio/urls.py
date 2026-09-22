"""taskio URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.http import HttpRequest
from django.shortcuts import render
from django.urls import include, path
from django.views.generic import RedirectView

from apps.businesses.models import ClarivoPlan
from apps.businesses.plan_catalog import (
    PUBLIC_PRICING_CURRENCIES,
    PUBLIC_PRICING_CURRENCY_QUERY_PARAM,
    PUBLIC_PRICING_CURRENCY_SESSION_KEY,
    normalize_public_pricing_currency,
    public_pricing_currency_display,
    public_pricing_currency_label,
    public_pricing_currency_or_default,
)
from apps.businesses.views import (
    billing_checkout_cancelled,
    billing_checkout_resume,
    billing_checkout_success,
    billing_customer_portal,
    billing_payment_recovery,
    stripe_billing_webhook,
)
from apps.crm.views import public_booking, public_booking_thank_you


def _selected_public_pricing_currency(request: HttpRequest) -> str:
    query_currency = normalize_public_pricing_currency(
        request.GET.get(PUBLIC_PRICING_CURRENCY_QUERY_PARAM),
    )
    if query_currency is not None:
        request.session[PUBLIC_PRICING_CURRENCY_SESSION_KEY] = query_currency
        return query_currency

    return public_pricing_currency_or_default(
        request.session.get(PUBLIC_PRICING_CURRENCY_SESSION_KEY),
    )


def motionmate_pricing_context(request: HttpRequest):
    selected_pricing_currency = _selected_public_pricing_currency(request)
    pricing_plans = list(ClarivoPlan.motionmate_plans())
    ClarivoPlan.attach_display_pricing(pricing_plans, region=selected_pricing_currency)
    pricing_currency_options = [
        {
            "value": currency,
            "label": public_pricing_currency_label(currency),
            "display": public_pricing_currency_display(currency),
            "is_active": currency == selected_pricing_currency,
        }
        for currency in PUBLIC_PRICING_CURRENCIES
    ]
    return {
        "pricing_plans": pricing_plans,
        "selected_pricing_currency": selected_pricing_currency,
        "selected_pricing_region_label": public_pricing_currency_label(
            selected_pricing_currency,
        ),
        "selected_pricing_currency_display": public_pricing_currency_display(
            selected_pricing_currency,
        ),
        "pricing_currency_options": pricing_currency_options,
    }


def landing(request):
    return render(request, "public_site/home.html", motionmate_pricing_context(request))


def site_preview(request):
    return render(request, "public_site/home.html", motionmate_pricing_context(request))


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="home", permanent=False)),
    path(
        "favicon.ico",
        RedirectView.as_view(
            url="/static/assets/img/favicons/favicon.ico?v=motionmate-20260629",
            permanent=False,
        ),
    ),
    path(
        "apple-touch-icon.png",
        RedirectView.as_view(
            url="/static/assets/img/favicons/apple-touch-icon.png?v=motionmate-20260629",
            permanent=False,
        ),
    ),
    path(
        "apple-touch-icon-precomposed.png",
        RedirectView.as_view(
            url="/static/assets/img/favicons/apple-touch-icon.png?v=motionmate-20260629",
            permanent=False,
        ),
    ),
    path(
        "manifest.json",
        RedirectView.as_view(
            url="/static/assets/img/favicons/manifest.json?v=motionmate-20260629",
            permanent=False,
        ),
    ),
    path(
        "site.webmanifest",
        RedirectView.as_view(
            url="/static/assets/img/favicons/site.webmanifest?v=motionmate-20260629",
            permanent=False,
        ),
    ),
    path(
        "browserconfig.xml",
        RedirectView.as_view(
            url="/static/assets/img/favicons/browserconfig.xml?v=motionmate-20260629",
            permanent=False,
        ),
    ),
    path("admin/", admin.site.urls),
    path("home/", landing, name="home"),
    path("site-preview/", site_preview, name="site_preview"),
    path("billing/checkout/success/", billing_checkout_success, name="billing_checkout_success"),
    path("billing/webhooks/stripe/", stripe_billing_webhook, name="stripe_billing_webhook"),
    path(
        "billing/checkout/cancelled/",
        billing_checkout_cancelled,
        name="billing_checkout_cancelled",
    ),
    path("billing/checkout/resume/", billing_checkout_resume, name="billing_checkout_resume"),
    path("billing/customer-portal/", billing_customer_portal, name="billing_customer_portal"),
    path("billing/payment-recovery/", billing_payment_recovery, name="billing_payment_recovery"),
    path("book/<slug:business_slug>/", public_booking, name="public_booking"),
    path(
        "book/<slug:business_slug>/thanks/",
        public_booking_thank_you,
        name="public_booking_thank_you",
    ),
    path("businesses/", include("apps.businesses.urls")),
    path("crm/", include("apps.crm.urls")),
    path("appointments/", include("apps.appointments.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("billings/", include("apps.billings.urls")),
]

# if settings.DEBUG:
#     urlpatterns += static(
#         settings.STATIC_URL,
#         document_root=settings.STATICFILES_DIRS[0],
#     )
