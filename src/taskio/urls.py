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


def landing(request):
    pricing_plans = ClarivoPlan.objects.filter(is_active=True).order_by("created_at", "pk")
    context = {"pricing_plans": pricing_plans}
    return render(request, "main/landing.html", context)

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="home", permanent=False)),
    path("admin/", admin.site.urls),
    path("home/", landing, name="home"),
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
