import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.businesses.business_data_purge import BusinessPurgeError
from apps.businesses.business_sessions import SelectiveSessionInvalidationUnavailable
from apps.businesses.models import ClarivoPlan
from apps.logistics.test_lab import (
    ACCOUNTS,
    DOMAIN,
    authorize,
    cleanup_plan,
    entitlement_plan,
    execute_lab,
    inspect_lab,
    lab_for,
    owned_objects,
    require_entitlement,
    seat_plan,
)


class Command(BaseCommand):
    help = "Preview, initialize, provision, inspect, rotate or safely clean up the fictional Logistics lab."

    def add_arguments(self, parser):
        parser.add_argument(
            "--environment", choices=("local", "development", "staging"), required=True
        )
        actions = parser.add_mutually_exclusive_group()
        actions.add_argument(
            "--initialize",
            action="store_true",
            help="Create only owner and pending checkout workspace.",
        )
        actions.add_argument("--inspect", action="store_true", help="Read-only lab inventory.")
        actions.add_argument(
            "--activate-test-entitlement",
            action="store_true",
            help="Requires separately configured approval; never creates a Stripe subscription.",
        )
        parser.add_argument(
            "--test-entitlement-approval",
            help="Exact preconfigured approval reference for test entitlement.",
        )
        actions.add_argument(
            "--cleanup",
            action="store_true",
            help="Preview guarded cleanup; rebuild with a separate provision operation.",
        )
        actions.add_argument(
            "--rotate-passwords",
            action="store_true",
            help="Rotate only owned account passwords; invalidate lab sessions.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Write explicitly; default is zero-write preview.",
        )
        parser.add_argument(
            "--confirm-database", help="Exact connected database fingerprint from preview."
        )
        parser.add_argument("--confirm-app", help="Authorized shared Heroku app name.")
        parser.add_argument("--business-id", type=int)
        parser.add_argument("--confirm-business-id", type=int)
        parser.add_argument(
            "--reason-reference",
            help="Approval/change reference; do not include credentials or personal data.",
        )
        parser.add_argument(
            "--credential-recipient",
            help="age public recipient (age1...). Private key stays with operator.",
        )
        parser.add_argument(
            "--credential-file",
            help="New encrypted artifact in an existing operator-owned 0700 directory.",
        )

    def handle(self, *args, **options):
        execute = options["execute"]
        action = next(
            (
                name
                for flag, name in (
                    ("initialize", "initialize"),
                    ("inspect", "inspect"),
                    ("cleanup", "cleanup"),
                    ("rotate_passwords", "rotate"),
                    ("activate_test_entitlement", "test-entitlement"),
                )
                if options[flag]
            ),
            "provision",
        )
        if action == "inspect" and execute:
            raise CommandError("--inspect is read-only and cannot use --execute.")
        if options["business_id"] is not None and options["business_id"] <= 0:
            raise CommandError("--business-id must be positive.")
        if action in ("cleanup", "rotate", "test-entitlement") and options["business_id"] is None:
            raise CommandError("Cleanup and rotation require an exact --business-id.")
        if execute and (not options["reason_reference"] or len(options["reason_reference"]) > 120):
            raise CommandError("Execute requires a --reason-reference of at most 120 characters.")
        if (
            execute
            and action in ("cleanup", "rotate", "test-entitlement")
            and options["confirm_business_id"] != options["business_id"]
        ):
            raise CommandError("--confirm-business-id must exactly match --business-id.")
        if action in ("cleanup", "test-entitlement") and (
            options["credential_file"] or options["credential_recipient"]
        ):
            raise CommandError("This action does not produce credentials.")
        try:
            identity = authorize(
                options["environment"],
                execute=execute,
                confirm_database=options["confirm_database"],
                confirm_app=options["confirm_app"],
            )
            business, seed = lab_for(options["environment"], options["business_id"])
            if action == "inspect":
                result = inspect_lab(business, seed)
            elif action == "test-entitlement":
                if business:
                    owned_objects(business, seed)
                result = entitlement_plan(business, options["test_entitlement_approval"])
            elif action == "cleanup":
                result = cleanup_plan(business, seed)
            elif action == "rotate":
                if business is None:
                    raise CommandError("No owned lab exists.")
                owned_objects(business, seed, check_dependents=False)
                result = {
                    "business_id": business.pk,
                    "rotate_owned_accounts": business.memberships.count(),
                }
            else:
                if business:
                    owned_objects(business, seed)
                    if action == "initialize" or seed.planned_counts.get("phase") == "ready":
                        raise CommandError(
                            "Lab already exists. Inspect it or use guarded cleanup before rebuilding."
                        )
                    require_entitlement(business.subscription, options["environment"])
                else:
                    reserved = [f"{name}@{DOMAIN}" for name, _, _ in ACCOUNTS]
                    if any(
                        get_user_model().objects.filter(email__iexact=email).exists()
                        for email in reserved
                    ):
                        raise CommandError(
                            "Reserved test identities exist; refusing to overwrite users."
                        )
                    from apps.businesses.models import BusinessSubscription

                    seat_plan(BusinessSubscription(plan=ClarivoPlan.objects.get(slug="logistics")))
                result = inspect_lab(business, seed)
                result["planned_action"] = action
                if not business and options["environment"] != "local" and action == "provision":
                    result["blocker"] = (
                        "Use --initialize first, then separately approved test entitlement or legitimate approval-bound Stripe TEST activation, then provision."
                    )
            if execute:
                result = execute_lab(
                    environment=options["environment"],
                    action=action,
                    credential_file=options["credential_file"],
                    recipient=options["credential_recipient"],
                    business_id=options["business_id"],
                    reason_reference=options["reason_reference"],
                    identity=identity,
                    approval_reference=options["test_entitlement_approval"],
                )
            self.stdout.write(
                json.dumps({"database_id": identity, "execute": execute, **result}, sort_keys=True)
            )
            self.stdout.write(
                "Complete. Credentials are encrypted in the selected artifact."
                if execute and action not in ("cleanup", "test-entitlement")
                else "Operation complete." if execute else "READ ONLY: zero writes."
            )
        except (
            ValidationError,
            PermissionDenied,
            BusinessPurgeError,
            SelectiveSessionInvalidationUnavailable,
        ) as exc:
            raise CommandError(str(exc)) from None
        except ClarivoPlan.DoesNotExist:
            raise CommandError(
                "Existing Logistics offering is missing; apply project migrations first."
            ) from None
        except IntegrityError:
            raise CommandError(
                "Concurrent execution or conflicting fixture records; transaction rolled back."
            ) from None
