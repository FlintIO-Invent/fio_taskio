from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.businesses.business_data_purge import (
    PURGE_DELETION_ORDER,
    BusinessPurgeError,
    BusinessPurgePlan,
    plan_business_purge,
    purge_business,
)


class Command(BaseCommand):
    help = "Permanently purge one inactive, approved test/demo Business by exact ID."

    def add_arguments(self, parser):
        parser.add_argument("--business-id", type=int, required=True)
        parser.add_argument("--reason-reference", default=None)
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Execute the displayed irreversible purge plan.",
        )
        parser.add_argument(
            "--confirm-business-id",
            type=int,
            default=None,
            help="Required with --execute and must exactly match --business-id.",
        )
        parser.add_argument(
            "--confirm-test-financial-data",
            action="store_true",
            help=(
                "Confirm that every selected invoice and line is approved test/demo data. "
                "Never use this for genuine retained financial records."
            ),
        )
        parser.add_argument(
            "--delete-eligible-users",
            action="store_true",
            help="Also delete only users that pass every conservative eligibility check.",
        )

    def handle(self, *args, **options):
        business_id = options["business_id"]
        execute = bool(options["execute"])
        confirmation_id = options.get("confirm_business_id")
        reason_reference = options.get("reason_reference")
        confirm_test_financial_data = bool(options["confirm_test_financial_data"])
        delete_eligible_users = bool(options["delete_eligible_users"])

        if execute and confirmation_id is None:
            raise CommandError("--execute requires --confirm-business-id.")
        if execute and confirmation_id != business_id:
            raise CommandError("--confirm-business-id must exactly match --business-id.")
        if execute and not reason_reference:
            raise CommandError("--execute requires --reason-reference.")

        try:
            plan = plan_business_purge(
                business_id,
                confirm_test_financial_data=confirm_test_financial_data,
                delete_eligible_users=delete_eligible_users,
            )
        except BusinessPurgeError as exc:
            raise CommandError(f"{exc} [error_code={exc.error_code}]") from exc

        if plan is None:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Business ID {business_id} was not found or has already been purged. "
                    "No changes were made."
                )
            )
            return

        self._render_plan(plan, execute=execute)
        if not execute:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN ONLY: no database writes, audit records, session removals, "
                    "tenant deletion, user deletion, or external calls were made."
                )
            )
            return

        try:
            result = purge_business(
                business_id=business_id,
                reason_reference=reason_reference,
                confirm_test_financial_data=confirm_test_financial_data,
                delete_eligible_users=delete_eligible_users,
            )
        except BusinessPurgeError as exc:
            raise CommandError(f"{exc} [error_code={exc.error_code}]") from exc

        if result.already_absent:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Business ID {business_id} was not found or has already been purged. "
                    "No changes were made."
                )
            )
            return

        self.stdout.write(self.style.SUCCESS(f"Business ID {business_id} was permanently purged."))
        for key in PURGE_DELETION_ORDER:
            self.stdout.write(f"- Deleted {key}: {result.deletion_counts.get(key, 0)}")
        self.stdout.write(
            f"- Sessions invalidated: {result.session_summary.sessions_to_invalidate}"
        )
        self.stdout.write(
            f"- Audit operation completed: {result.audit_operation_id or 'not created'}"
        )
        self.stdout.write("No Stripe API or other external API was called.")

    def _render_plan(self, plan: BusinessPurgePlan, *, execute: bool) -> None:
        inventory = plan.inventory
        billing = inventory.billing_assessment
        self.stdout.write("PERMANENT business purge plan")
        self.stdout.write(f"- Business ID: {plan.business_id}")
        self.stdout.write(f"- Business slug: {plan.business_slug}")
        self.stdout.write(f"- Business active: {plan.business_is_active}")
        self.stdout.write(
            "- Total directly and indirectly owned records: "
            f"{inventory.summary.total_directly_and_indirectly_owned_records}"
        )
        self.stdout.write(f"- Invoice count: {billing.invoice_count}")
        self.stdout.write(f"- InvoiceLine count: {billing.invoice_line_count}")
        self.stdout.write(
            "- Cross-tenant integrity blockers: "
            f"{inventory.summary.cross_tenant_integrity_blocker_count}"
        )
        self.stdout.write(
            "- Stripe customer reference present: " f"{billing.provider_customer_id_present}"
        )
        self.stdout.write(
            "- Stripe subscription reference present: "
            f"{billing.provider_subscription_id_present}"
        )
        self.stdout.write(
            "- Stripe checkout reference present: " f"{billing.provider_checkout_id_present}"
        )
        self.stdout.write(
            f"- Correlated webhook references: {billing.correlated_webhook_event_count}"
        )
        if billing.invoice_count:
            self.stdout.write(
                self.style.ERROR(
                    "WARNING: invoices and invoice lines are permanent financial records. "
                    "Execution is permitted only for approved test/demo financial data with "
                    "--confirm-test-financial-data. There is no bypass for genuine retained "
                    "financial records."
                )
            )

        self.stdout.write("Record counts")
        for record in inventory.records:
            self.stdout.write(f"- {record.key}: {record.total_count}")

        self.stdout.write("Explicit deletion order")
        for index, key in enumerate(PURGE_DELETION_ORDER, start=1):
            self.stdout.write(f"{index}. {key}")

        deleting_users = [decision for decision in plan.user_decisions if decision.delete]
        preserved_users = [decision for decision in plan.user_decisions if not decision.delete]
        self.stdout.write("User handling")
        self.stdout.write(f"- Eligible users planned for deletion: {len(deleting_users)}")
        self.stdout.write(f"- Users planned for preservation: {len(preserved_users)}")
        for decision in preserved_users:
            self.stdout.write(
                f"- Preserve User ID {decision.user_id}: " f"{','.join(decision.reason_codes)}"
            )

        self.stdout.write("Safeguards")
        self.stdout.write(f"- Blocking conditions: {','.join(plan.blocking_error_codes) or 'none'}")
        self.stdout.write(
            f"- Sessions selected for safe invalidation: "
            f"{plan.session_summary.sessions_to_invalidate}"
        )
        self.stdout.write("- Shared plans and system configuration will be preserved.")
        self.stdout.write("- Stripe will not be contacted.")
        if execute:
            self.stdout.write("- Execution requested; all gates will be re-run under lock.")
