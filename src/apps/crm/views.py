from urllib import request

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Q

from .forms import PublicLeadForm
from .models import Lead
from .services import send_lead_email



def agent_dashboard(request):

    context = {}
    return render(request, "crm/agent_dashboard/agent_dashboard.html", context)



def public_request(request):
    if request.method == "POST":
        form = PublicLeadForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("public_thank_you")
    else:
        form = PublicLeadForm()
    # return render(request, "accounts/main/customer_registration.html", {"form": form})
    return render(request, "crm/forms/public_request.html", {"form": form})


def public_thank_you(request):
    return render(request, "crm/success_fail/success.html")


# @login_required
# def staff_lead_list(request):
#     qs = Lead.objects.select_related("category").all()

#     status = request.GET.get("status", "").strip()
#     lead_type = request.GET.get("lead_type", "").strip()
#     q = request.GET.get("q", "").strip()

#     if status:
#         qs = qs.filter(status=status)
#     if lead_type:
#         qs = qs.filter(lead_type=lead_type)
#     if q:
#         qs = qs.filter(
#             Q(first_name__icontains=q)
#             | Q(last_name__icontains=q)
#             | Q(email__icontains=q)
#             | Q(phone__icontains=q)
#         )

#     return render(request, "staff/lead_list.html", {"leads": qs, "filters": {"status": status, "lead_type": lead_type, "q": q}})


# @login_required
# def staff_lead_detail(request, lead_id: int):
#     lead = get_object_or_404(Lead, pk=lead_id)
#     return render(request, "staff/lead_detail.html", {"lead": lead})


# @login_required
# def staff_lead_email(request, lead_id: int):
    lead = get_object_or_404(Lead, pk=lead_id)

    if request.method == "POST":
        form = StaffEmailForm(request.POST)
        if form.is_valid():
            send_lead_email(
                actor=request.user,
                lead=lead,
                subject=form.cleaned_data["subject"],
                body=form.cleaned_data["body"],
            )
            return redirect("staff_lead_detail", lead_id=lead.id)
    else:
        form = StaffEmailForm(initial={"subject": f"Re: {lead.category.name}", "body": f"Hi {lead.first_name},\n\n"})

    return render(request, "staff/email_compose.html", {"lead": lead, "form": form})