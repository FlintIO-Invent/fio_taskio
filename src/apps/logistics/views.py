from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from .forms import LogisticsApplicationForm


@require_http_methods(["GET", "POST"])
def application_create(request):
    form = LogisticsApplicationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        # Identical public response for all decisions and relationship signals.
        return redirect("logistics_application_received")
    return render(request, "logistics/application_form.html", {"form": form})


@require_safe
def application_received(request):
    return render(request, "logistics/application_received.html")
