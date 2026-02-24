from django.urls import path
from .views import (
    public_request,
    public_thank_you,
    agent_dashboard
    # staff_lead_list,
    # staff_lead_detail,
    # staff_lead_email,
)

urlpatterns = [
    path("agent/dashboard/", agent_dashboard, name="agent_dashboard"),
    path("public_request/", public_request, name="public_request"),
    path("thanks/", public_thank_you, name="public_thank_you"),

    # path("staff/leads/", staff_lead_list, name="staff_lead_list"),
    # path("staff/leads/<int:lead_id>/", staff_lead_detail, name="staff_lead_detail"),
    # path("staff/leads/<int:lead_id>/email/", staff_lead_email, name="staff_lead_email"),
]