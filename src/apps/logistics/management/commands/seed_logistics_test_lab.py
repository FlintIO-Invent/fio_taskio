import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.businesses.demo_seed_reset import DemoSeedResetError
from apps.logistics.test_lab import authorize
from apps.logistics.test_lab_dataset import execute_dataset, inspect_dataset, plan_dataset


class Command(BaseCommand):
    help = "Preview, seed, inspect or reset connected cargo in the owned Block 06A lab."

    def add_arguments(self, parser):
        parser.add_argument(
            "--environment", required=True, choices=("local", "development", "staging")
        )
        parser.add_argument("--business-id", required=True, type=int)
        actions = parser.add_mutually_exclusive_group()
        actions.add_argument(
            "--inspect", action="store_true", help="Read-only counts and stable record identifiers."
        )
        actions.add_argument(
            "--reset",
            action="store_true",
            help="Preview owned-only dataset removal; keep the foundation.",
        )
        parser.add_argument(
            "--execute", action="store_true", help="Explicit write; default is zero-write preview."
        )
        parser.add_argument("--confirm-business-id", type=int)
        parser.add_argument("--confirm-database")
        parser.add_argument("--confirm-app")
        parser.add_argument("--reason-reference")
        parser.add_argument(
            "--confirm-test-financial-data",
            action="store_true",
            help="Reset only unchanged, undispatched fixture draft invoices.",
        )

    def handle(self, *args, **options):
        if options["business_id"] <= 0 or options["business_id"] == 133:
            raise CommandError("Select the exact owned lab ID; business 133 is excluded.")
        if options["inspect"] and options["execute"]:
            raise CommandError("--inspect is read-only.")
        try:
            identity = authorize(
                options["environment"],
                execute=options["execute"],
                confirm_database=options["confirm_database"],
                confirm_app=options["confirm_app"],
            )
            common = dict(environment=options["environment"], business_id=options["business_id"])
            if options["inspect"]:
                result = inspect_dataset(**common)
            elif options["execute"]:
                result = execute_dataset(
                    **common,
                    confirm_business_id=options["confirm_business_id"],
                    confirm_database=options["confirm_database"],
                    confirm_app=options["confirm_app"],
                    reason_reference=options["reason_reference"],
                    reset=options["reset"],
                    confirm_test_financial_data=options["confirm_test_financial_data"],
                )
            else:
                result = plan_dataset(**common, reset=options["reset"])
        except (PermissionDenied, ValidationError, IntegrityError, DemoSeedResetError) as exc:
            raise CommandError(str(exc)) from exc
        result["database_id"] = identity
        result["mode"] = "executed" if options["execute"] else "read-only; zero writes"
        self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
