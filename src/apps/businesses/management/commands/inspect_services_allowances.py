"""Read-only rollout preflight and historical appointment anomaly report."""

import json
from datetime import UTC
from importlib import import_module

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F
from django.db.models.functions import TruncMonth

from apps.appointments.models import Appointment
from apps.businesses.models import ClarivoPlan


class Command(BaseCommand):
    help = (
        "Read-only Services allowance preflight; reports customized plans and appointment months."
    )

    def handle(self, **options):
        rollout = import_module("apps.businesses.migrations.0035_services_allowances")
        plans = {p.slug: p for p in ClarivoPlan.objects.filter(slug__in=rollout.CONFIGURATIONS)}
        states = {
            slug: (
                rollout.configuration_state(plans[slug])
                if slug in plans and plans[slug].family == "SERVICE"
                else "missing_or_wrong_family"
            )
            for slug in rollout.CONFIGURATIONS
        }
        months = (
            Appointment.objects.filter(business__vertical="SERVICE")
            .annotate(month=TruncMonth("start_time", tzinfo=UTC))
            .values(
                "business_id", "month", "business__subscription__plan__max_appointments_per_month"
            )
            .annotate(count=Count("pk"))
            .filter(count__gt=F("business__subscription__plan__max_appointments_per_month"))
        )
        duplicates = (
            Appointment.objects.filter(business__vertical="SERVICE", source_lead__isnull=False)
            .values("business_id", "source_lead_id")
            .annotate(count=Count("pk"))
            .filter(count__gt=1)
        )
        self.stdout.write(
            json.dumps(
                {
                    "plans": states,
                    "over_limit_months": list(months),
                    "multiple_appointments_per_request_review_only": list(duplicates),
                },
                default=str,
                indent=2,
            )
        )
        if any(state not in {"baseline", "approved"} for state in states.values()):
            raise CommandError(
                "Services rollout requires explicit reconciliation; customized/missing plans were not changed."
            )
