import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.businesses.models import Business
from apps.logistics.monitoring import record_signal
from apps.logistics.subscription_usage import logistics_subscription_usage
from apps.logistics.usage_warnings import enqueue_usage_warnings


class Command(BaseCommand):
    help = "Snapshot Logistics usage; optionally enqueue deduplicated warnings. Never sends email."

    def add_arguments(self, parser):
        parser.add_argument("--business-id", type=int)
        parser.add_argument("--after-business-id", type=int, default=0)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument(
            "--enqueue",
            action="store_true",
            help="Create warning outbox records; default is read-only.",
        )
        parser.add_argument(
            "--database-size",
            action="store_true",
            help="Include whole PostgreSQL database bytes, never per-tenant allocation or costs.",
        )

    def handle(self, *args, **options):
        if (
            options["after_business_id"] < 0
            or options["limit"] <= 0
            or (options["business_id"] is not None and options["business_id"] <= 0)
        ):
            raise CommandError("Business ID and limit must be positive.")
        businesses = Business.objects.filter(
            vertical="LOGISTICS", is_active=True, pk__gt=options["after_business_id"]
        )
        if options["business_id"]:
            businesses = businesses.filter(pk=options["business_id"])
        for business in businesses.order_by("pk")[: options["limit"]]:
            usage = logistics_subscription_usage(business=business)
            warnings = enqueue_usage_warnings(
                business=business, snapshot=usage, dry_run=not options["enqueue"]
            )
            output = {
                "business_id": business.pk,
                "period": usage["period"],
                "metrics": [
                    {key: row[key] for key in ("name", "used", "allowance", "state", "measured")}
                    for row in usage["hard"] + usage["monitoring"]
                ],
                "accepted_subscription_emails": usage["accepted_subscription_emails"],
                "warnings": warnings,
                "read_only": not options["enqueue"],
            }
            self.stdout.write(json.dumps(output))
            record_signal("usage_snapshot", business_id=business.pk, period=usage["period"])
        if options["database_size"]:
            size = None
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_database_size(current_database())")
                    size = cursor.fetchone()[0]
            self.stdout.write(
                json.dumps(
                    {"database_bytes": size, "scope": "whole_database", "cost_estimate": None}
                )
            )
