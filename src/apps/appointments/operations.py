"""Retry keys distinguish a repeated submission from another deliberate appointment."""

import hashlib
import json
import uuid

from django.db import transaction

from apps.businesses.usage_limits import QuotaError, lock_capacity_scope


def operation_key(data):
    value = data.get("operation_key")
    if not value:
        # Compatibility for already-open forms and legacy embedded submissions.
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise QuotaError("Reload the form before submitting this operation.") from exc


def operation_fingerprint(request):
    payload = {
        key: request.POST.getlist(key)
        for key in sorted(request.POST)
        if key not in {"csrfmiddlewaretoken", "operation_key"}
    }
    binding = [request.path, getattr(request.user, "pk", None), payload]
    return hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()


def completed_operation(model, business, key, fingerprint):
    if key is None:
        return None
    previous = model.objects.filter(business=business, submission_key=key).first()
    if previous and previous.submission_fingerprint != fingerprint:
        raise QuotaError(
            "This submission was already used for different details. Reload the form to start another operation."
        )
    return previous


@transaction.atomic
def create_appointment_operation(request, form, *, source_lead=None):
    from .models import Appointment

    business, _ = lock_capacity_scope(request.current_business.pk)
    key = operation_key(request.POST)
    fingerprint = operation_fingerprint(request)
    previous = completed_operation(Appointment, business, key, fingerprint)
    if previous:
        return previous, False
    appointment = form.save(commit=False)
    appointment.business = business
    appointment.source_lead = source_lead
    appointment.submission_key = key
    appointment.submission_fingerprint = fingerprint if key else ""
    appointment.save()
    return appointment, True
