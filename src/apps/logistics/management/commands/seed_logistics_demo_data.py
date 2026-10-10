import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.businesses.demo_seed_reset import DemoSeedResetError
from apps.businesses.models import Business, DemoSeedRun
from apps.logistics.demo import (
    LOGISTICS_DEMO_COUNTS,
    PARCEL_STATUS_COUNTS,
    SHIPMENT_STATUS_COUNTS,
    demo_actor,
    logistics_demo_location_plan,
    logistics_demo_profile_plan,
    plan_logistics_demo_reset,
    require_logistics_business,
    reset_logistics_demo,
    seed_logistics_demo,
)
from apps.logistics.models import Parcel, Shipment


class Command(BaseCommand):
    help = "Preview or seed/reset owned Logistics demo data for an existing Business."

    def add_arguments(self, parser):
        parser.add_argument("--business-id", required=True, type=int)
        parser.add_argument(
            "--actor-id",
            type=int,
            help="Existing operator (otherwise first eligible member by ID).",
        )
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--origin-location-id", type=int)
        parser.add_argument("--destination-location-id", type=int)
        parser.add_argument("--reset-demo", "--reset", dest="reset_demo", action="store_true")

    def handle(self, *args, **options):
        business_id = options["business_id"]
        actor_id = options.get("actor_id")
        if business_id <= 0 or (actor_id is not None and actor_id <= 0):
            raise CommandError("Business and actor IDs must be positive integers.")
        origin_location_id = options.get("origin_location_id")
        destination_location_id = options.get("destination_location_id")
        if any(
            value is not None and value <= 0
            for value in (origin_location_id, destination_location_id)
        ):
            raise CommandError("Operating-site IDs must be positive integers.")
        if options["reset_demo"] and actor_id is not None:
            raise CommandError("--actor-id cannot be combined with --reset-demo.")
        if options["reset_demo"] and (origin_location_id or destination_location_id):
            raise CommandError("Operating sites cannot be combined with --reset-demo.")
        try:
            business = Business.objects.get(pk=business_id)
            require_logistics_business(business)
            seed = DemoSeedRun.objects.filter(business=business).first()
            if options["reset_demo"]:
                plan = plan_logistics_demo_reset(business=business, seed_run=seed)
                self.stdout.write(
                    json.dumps(
                        {
                            "business_id": business_id,
                            "reset_counts": plan.counts,
                            "stale_tracking_records": plan.stale_tracking_record_count,
                        },
                        sort_keys=True,
                    )
                )
                if options["execute"]:
                    result = reset_logistics_demo(business_id=business_id)
                    self.stdout.write(
                        "Reset complete." if result else "No demo ownership metadata; no changes."
                    )
                else:
                    self.stdout.write("RESET PREVIEW ONLY: no writes made. Add --execute to reset.")
            else:
                if seed:
                    raise CommandError(
                        "Demo ownership metadata already exists; preview/reset it before seeding again."
                    )
                actor = demo_actor(business=business, actor_id=actor_id)
                location_plan = logistics_demo_location_plan(
                    business=business,
                    actor=actor,
                    origin_location_id=origin_location_id,
                    destination_location_id=destination_location_id,
                )
                profile_plan = logistics_demo_profile_plan(business)
                self.stdout.write(
                    json.dumps(
                        {
                            "business_id": business_id,
                            "actor_id": actor.pk,
                            **({"operational_locations": location_plan} if location_plan else {}),
                            "planned_counts": {
                                "logistics_profiles": profile_plan["create_count"],
                                **LOGISTICS_DEMO_COUNTS,
                            },
                            "logistics_profile": profile_plan,
                            "shipment_mode_counts": profile_plan["shipment_mode_counts"],
                            "parcel_status_counts": PARCEL_STATUS_COUNTS,
                            "shipment_status_counts": SHIPMENT_STATUS_COUNTS,
                            "invoice_status_counts": {"DRAFT": 1, "SENT": 2, "PAID": 1},
                        },
                        sort_keys=True,
                    )
                )
                if options["execute"]:
                    seed = seed_logistics_demo(
                        business_id=business_id,
                        actor_id=actor.pk,
                        origin_location_id=origin_location_id,
                        destination_location_id=destination_location_id,
                    )
                    self.stdout.write("Logistics demo data created with ownership metadata.")
                    owned = [
                        int(pk)
                        for pk in seed.owned_records.filter(
                            model_label=Parcel._meta.label
                        ).values_list("object_pk", flat=True)
                    ]
                    tracking = list(
                        Parcel.objects.filter(
                            business=business,
                            pk__in=owned,
                            internal_reference__in=("DEMO-001", "DEMO-004"),
                        )
                        .order_by("internal_reference")
                        .values("internal_reference", "current_status", "tracking_code")
                    )
                    shipment_pks = [
                        int(pk)
                        for pk in seed.owned_records.filter(
                            model_label=Shipment._meta.label
                        ).values_list("object_pk", flat=True)
                    ]
                    manifest = (
                        Shipment.objects.filter(
                            business=business,
                            pk__in=shipment_pks,
                            status=Shipment.Status.IN_TRANSIT,
                        )
                        .values("id", "reference")
                        .get()
                    )
                    self.stdout.write(
                        json.dumps(
                            {"demo_tracking": tracking, "manifest_shipment": manifest},
                            sort_keys=True,
                        )
                    )
                else:
                    self.stdout.write("DRY RUN ONLY: no writes made. Add --execute to seed.")
        except Business.DoesNotExist as exc:
            raise CommandError("The selected existing Business was not found.") from exc
        except (ValidationError, PermissionDenied, DemoSeedResetError) as exc:
            raise CommandError(str(exc)) from exc
