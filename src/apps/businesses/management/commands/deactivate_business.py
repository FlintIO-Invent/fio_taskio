from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.businesses.business_data_operations import (
    BusinessDeactivationError,
    BusinessDeactivationPlan,
    deactivate_business,
    plan_business_deactivation,
)


class Command(BaseCommand):
    help = "Safely deactivate one exact Business without deleting tenant data."

    def add_arguments(self, parser):
        parser.add_argument("--business-id", type=int, required=True)
        parser.add_argument("--reason-reference", required=True)
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply the displayed reversible deactivation plan.",
        )
        parser.add_argument(
            "--confirm-business-id",
            type=int,
            default=None,
            help="Required with --execute and must exactly match --business-id.",
        )

    def handle(self, *args, **options):
        business_id = options["business_id"]
        execute = bool(options["execute"])
        confirmation_id = options.get("confirm_business_id")

        if execute and confirmation_id is None:
            raise CommandError("--execute requires --confirm-business-id.")
        if execute and confirmation_id != business_id:
            raise CommandError("--confirm-business-id must exactly match --business-id.")

        try:
            plan = plan_business_deactivation(
                business_id,
                reason_reference=options["reason_reference"],
            )
        except BusinessDeactivationError as exc:
            raise CommandError(f"{exc} [error_code={exc.error_code}]") from exc

        self._render_plan(plan, execute=execute)
        if not execute:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN ONLY: no database writes, audit records, session removals, "
                    "notification changes, or external calls were made."
                )
            )
            return

        try:
            result = deactivate_business(
                business_id=business_id,
                reason_reference=options["reason_reference"],
            )
        except BusinessDeactivationError as exc:
            raise CommandError(f"{exc} [error_code={exc.error_code}]") from exc

        if result.changed:
            self.stdout.write(
                self.style.SUCCESS(f"Business ID {business_id} was deactivated successfully.")
            )
            self.stdout.write(f"Notifications cancelled: {result.notification_count_cancelled}")
            self.stdout.write(
                f"Sessions invalidated: {result.session_summary.sessions_to_invalidate}"
            )
            self.stdout.write(
                "Audit operation completed: " f"{result.audit_operation_id or 'not created'}"
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Business ID {business_id} is already inactive; no change was required."
                )
            )
            self.stdout.write(
                "No audit operation, notification update, or session invalidation was created "
                "for this idempotent no-op."
            )

    def _render_plan(self, plan: BusinessDeactivationPlan, *, execute: bool) -> None:
        inventory = plan.inventory
        billing = inventory.billing_assessment
        self.stdout.write("Business deactivation plan")
        self.stdout.write(f"- Business ID: {plan.business_id}")
        self.stdout.write(f"- Business slug: {plan.business_slug}")
        self.stdout.write(f"- Business active: {plan.business_is_active}")
        self.stdout.write(
            "- Total directly and indirectly owned records: "
            f"{inventory.summary.total_directly_and_indirectly_owned_records}"
        )
        self.stdout.write(f"- Invoice count: {billing.invoice_count}")
        self.stdout.write(f"- InvoiceLine count: {billing.invoice_line_count}")
        self.stdout.write(f"- Subscription state: {billing.subscription_status or 'none'}")
        self.stdout.write(
            "- Cross-tenant integrity blockers: "
            f"{inventory.summary.cross_tenant_integrity_blocker_count}"
        )

        self.stdout.write("Record counts")
        for record in inventory.records:
            self.stdout.write(f"- {record.key}: {record.total_count}")

        self.stdout.write("Planned changes")
        if not plan.change_required:
            self.stdout.write("- No state change: the business is already inactive.")
            return

        action = "Will" if execute else "Would"
        self.stdout.write(f"- {action} set Business.is_active=False.")
        self.stdout.write(
            f"- {action} cancel {plan.pending_notification_count} unsent subscription "
            "notification(s); sent history remains unchanged."
        )
        self.stdout.write(
            f"- {action} selectively invalidate "
            f"{plan.session_summary.sessions_to_invalidate} session(s)."
        )
        self.stdout.write(
            f"- {action} preserve memberships, users, CRM data, appointments, services, "
            "subscriptions, invoices, invoice lines, and shared plans."
        )
        self.stdout.write(f"- {action} not contact Stripe or any other external API.")
        if plan.session_summary.corrupted_sessions_skipped:
            self.stdout.write(
                "- Undecodable sessions safely skipped: "
                f"{plan.session_summary.corrupted_sessions_skipped}."
            )
