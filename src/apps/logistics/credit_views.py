"""Accounting-only review and audited approval/revocation of movement credit."""

import uuid
from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.businesses.utils import business_module_required, business_role_required

from .credit_services import approve_credit, credit_review, fingerprint, revoke_credit
from .models import LogisticsCreditApproval
from .parcel_services import parcels_for_business


class CreditApprovalForm(forms.Form):
    status = forms.ChoiceField(
        choices=[("IN_TRANSIT", "Origin departure only"), ("DELIVERED", "Final delivery only")]
    )
    reason_reference = forms.CharField(
        max_length=1000,
        label="Reason / evidence reference",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    expires_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
    )
    confirm_obligations = forms.BooleanField(
        label="I reviewed these exact obligations and full shared Invoice balance limits"
    )
    obligation_fingerprint = forms.CharField(widget=forms.HiddenInput)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-check-input"
                if isinstance(field.widget, forms.CheckboxInput)
                else "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )


@never_cache
@business_module_required("invoicing")
@business_role_required("owner", "admin")
@require_http_methods(["GET", "POST"])
def parcel_credit(request, parcel_id):
    parcel = get_object_or_404(
        parcels_for_business(business=request.current_business, actor=request.user), pk=parcel_id
    )
    error, snapshot = "", None
    form = None
    if request.method == "POST" and request.POST.get("revoke"):
        try:
            approval_id = int(request.POST["revoke"])
        except (TypeError, ValueError) as exc:
            raise Http404("Credit approval is unavailable.") from exc
        approval = get_object_or_404(
            LogisticsCreditApproval,
            business=request.current_business,
            parcel=parcel,
            pk=approval_id,
        )
        try:
            revoke_credit(
                business=request.current_business,
                actor=request.user,
                approval=approval,
                reason_reference=request.POST.get("reason_reference", ""),
                idempotency_key=request.POST.get("idempotency_key"),
            )
        except ValidationError as exc:
            error = "; ".join(exc.messages)
        else:
            return redirect("logistics_parcel_credit", parcel_id=parcel.pk)
    else:
        try:
            snapshot = credit_review(
                business=request.current_business, actor=request.user, parcel=parcel
            )
        except ValidationError as exc:
            error = "; ".join(exc.messages)
        if snapshot is not None:
            form = CreditApprovalForm(
                request.POST if request.method == "POST" else None,
                initial={
                    "expires_at": timezone.now() + timedelta(days=7),
                    "obligation_fingerprint": fingerprint(snapshot),
                    "idempotency_key": uuid.uuid4(),
                },
            )
            if request.method == "POST" and form.is_valid():
                fields = dict(form.cleaned_data)
                fields.pop("confirm_obligations")
                try:
                    approve_credit(
                        business=request.current_business,
                        actor=request.user,
                        parcel=parcel,
                        **fields,
                    )
                except ValidationError as exc:
                    form.add_error(None, "; ".join(exc.messages))
                else:
                    return redirect("logistics_parcel_credit", parcel_id=parcel.pk)
    approvals = list(
        LogisticsCreditApproval.objects.filter(business=request.current_business, parcel=parcel)
        .select_related("approved_by", "revocation__revoked_by")
        .order_by("-approved_at", "-pk")
    )
    for approval in approvals:
        approval.revocation_nonce = uuid.uuid4()
    return render(
        request,
        "logistics/credit_form.html",
        {
            "parcel": parcel,
            "form": form,
            "snapshot": snapshot,
            "credit_error": error,
            "approvals": approvals,
        },
    )
