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
from django.shortcuts import render
from django.urls import include, path
from django.views.generic import RedirectView

from apps.businesses.models import ClarivoPlan
from apps.crm.views import public_booking, public_booking_thank_you


def motionmate_pricing_context():
    pricing_plans = list(ClarivoPlan.motionmate_plans())
    ClarivoPlan.attach_display_pricing(pricing_plans)
    return {"pricing_plans": pricing_plans}


def landing(request):
    return render(request, "public_site/home.html", motionmate_pricing_context())


def site_preview(request):
    return render(request, "public_site/home.html", motionmate_pricing_context())

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
