import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.businesses.demo_seed_reset import DemoSeedResetError
from apps.businesses.models import Business, DemoSeedRun
from apps.logistics.demo import (
    LOGISTICS_DEMO_COUNTS,
    demo_actor,
    plan_logistics_demo_reset,
    require_logistics_business,
    reset_logistics_demo,
    seed_logistics_demo,
)


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
        parser.add_argument("--reset-demo", action="store_true")

    def handle(self, *args, **options):
        business_id = options["business_id"]
        actor_id = options.get("actor_id")
        if business_id <= 0 or (actor_id is not None and actor_id <= 0):
            raise CommandError("Business and actor IDs must be positive integers.")
        if options["reset_demo"] and actor_id is not None:
            raise CommandError("--actor-id cannot be combined with --reset-demo.")
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
                self.stdout.write(
                    json.dumps(
                        {
                            "business_id": business_id,
                            "actor_id": actor.pk,
                            "planned_counts": LOGISTICS_DEMO_COUNTS,
                        },
                        sort_keys=True,
                    )
                )
                if options["execute"]:
                    seed_logistics_demo(business_id=business_id, actor_id=actor.pk)
                    self.stdout.write("Logistics demo data created with ownership metadata.")
                else:
                    self.stdout.write("DRY RUN ONLY: no writes made. Add --execute to seed.")
        except Business.DoesNotExist as exc:
            raise CommandError("The selected existing Business was not found.") from exc
        except (ValidationError, PermissionDenied, DemoSeedResetError) as exc:
            raise CommandError(str(exc)) from exc
