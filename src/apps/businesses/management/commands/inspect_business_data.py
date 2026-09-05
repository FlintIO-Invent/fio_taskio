from __future__ import annotations

import json
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.businesses.business_data_inventory import (
    BusinessDataInventory,
    build_business_data_inventory,
)
from apps.businesses.business_resolution import (
    BusinessCandidate,
    BusinessResolutionError,
    resolve_business_candidates,
)


class _RejectDatabaseWrites:
    write_statements = {"ALTER", "CREATE", "DELETE", "DROP", "INSERT", "REPLACE", "UPDATE"}

    def __call__(self, execute, sql, params, many, context):
        normalized_sql = sql.lstrip().upper()
        statement = normalized_sql.partition(" ")[0]
        is_write_cte = statement == "WITH" and bool(
            set(re.findall(r"\b[A-Z]+\b", normalized_sql)) & self.write_statements
        )
        if statement in self.write_statements or is_write_cte:
            raise CommandError(
                f"inspect_business_data blocked an unexpected {statement} database statement."
            )
        return execute(sql, params, many, context)


class Command(BaseCommand):
    help = "Inspect business-owned data without modifying local or external state."

    def add_arguments(self, parser):
        lookup_group = parser.add_mutually_exclusive_group(required=True)
        lookup_group.add_argument("--business-id", dest="business_id")
        lookup_group.add_argument("--slug")
        lookup_group.add_argument("--email")
        parser.add_argument(
            "--format",
            dest="output_format",
            choices=("text", "json"),
            default="text",
        )

    def handle(self, *args, **options):
        output_format = options["output_format"]
        lookup = {
            "business_id": options.get("business_id"),
            "slug": options.get("slug"),
            "email": options.get("email"),
        }

        with connection.execute_wrapper(_RejectDatabaseWrites()):
            try:
                candidates = resolve_business_candidates(**lookup)
            except BusinessResolutionError as exc:
                raise CommandError(str(exc)) from exc

            if not candidates:
                self._render_lookup_failure(
                    output_format=output_format,
                    status="not_found",
                    message="No business matched the supplied lookup.",
                    candidates=(),
                    supplied_email=options.get("email"),
                )
                raise CommandError("Business lookup returned no candidates.")

            if len(candidates) != 1:
                self._render_lookup_failure(
                    output_format=output_format,
                    status="ambiguous",
                    message=(
                        "Multiple businesses matched. Review every candidate and rerun using "
                        "--business-id."
                    ),
                    candidates=candidates,
                    supplied_email=options.get("email"),
                )
                raise CommandError(
                    "Business lookup is ambiguous; rerun with an exact --business-id."
                )

            candidate = candidates[0]
            inventory = build_business_data_inventory(candidate.business_id)

        if output_format == "json":
            self.stdout.write(json.dumps(inventory.to_dict(), sort_keys=True))
        else:
            self._render_text_inventory(inventory)

    def _render_lookup_failure(
        self,
        *,
        output_format: str,
        status: str,
        message: str,
        candidates: tuple[BusinessCandidate, ...],
        supplied_email: str | None,
    ) -> None:
        candidate_data = [
            self._safe_candidate_dict(candidate, supplied_email=supplied_email)
            for candidate in candidates
        ]
        if output_format == "json":
            self.stdout.write(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": status,
                        "message": message,
                        "candidates": candidate_data,
                    },
                    sort_keys=True,
                )
            )
            return

        self.stdout.write(message)
        for candidate in candidate_data:
            self.stdout.write(
                "Candidate: "
                f"Business ID={candidate['business_id']} "
                f"name={candidate['business_name']} "
                f"slug={candidate['slug']} "
                f"contact_email={candidate['business_contact_email'] or '<not displayed>'} "
                f"active={candidate['is_active']}"
            )
            for match in candidate["matches"]:
                membership = ""
                if match["membership_role"] is not None:
                    membership = (
                        f" role={match['membership_role']} "
                        f"membership_active={match['membership_is_active']}"
                    )
                self.stdout.write(f"  matched_by={match['matched_by']}{membership}")

    @staticmethod
    def _safe_candidate_dict(
        candidate: BusinessCandidate,
        *,
        supplied_email: str | None,
    ) -> dict[str, object]:
        normalized_supplied_email = (supplied_email or "").strip().casefold()
        contact_email = candidate.business_contact_email
        show_contact_email = bool(
            normalized_supplied_email
            and contact_email.strip().casefold() == normalized_supplied_email
        )
        return {
            "business_id": candidate.business_id,
            "business_name": candidate.business_name,
            "slug": candidate.slug,
            "business_contact_email": contact_email if show_contact_email else None,
            "is_active": candidate.is_active,
            "matches": [
                {
                    "matched_by": match.matched_by.value,
                    "membership_role": match.membership_role,
                    "membership_is_active": match.membership_is_active,
                }
                for match in candidate.matches
            ],
        }

    def _render_text_inventory(self, inventory: BusinessDataInventory) -> None:
        self.stdout.write(f"Selected Business ID: {inventory.business_id}")
        self.stdout.write(f"Business name: {inventory.business_name}")
        self.stdout.write(f"Business slug: {inventory.business_slug}")
        self.stdout.write(f"Business active: {inventory.business_is_active}")

        self.stdout.write("\nRecord inventory")
        for record in inventory.records:
            active_count = "n/a" if record.active_count is None else str(record.active_count)
            inactive_count = (
                "n/a"
                if record.archived_inactive_count is None
                else str(record.archived_inactive_count)
            )
            self.stdout.write(
                f"- {record.app_label}.{record.model_name}: "
                f"relationship={record.relationship_path}; "
                f"classification={record.classification.value}; "
                f"active={active_count}; inactive_or_archived={inactive_count}; "
                f"total={record.total_count}; "
                f"explicit_deletion_required={record.explicit_deletion_required}; "
                f"financial_or_legal={record.financially_or_legally_sensitive}"
            )

        self.stdout.write("\nUser impact")
        if not inventory.user_impact:
            self.stdout.write("- No BusinessUser memberships found.")
        for impact in inventory.user_impact:
            self.stdout.write(
                f"- User ID={impact.user_id}; active={impact.is_active}; "
                f"staff={impact.is_staff}; superuser={impact.is_superuser}; "
                f"role={impact.role}; membership_active={impact.membership_is_active}; "
                f"other_memberships={impact.other_business_membership_count}; "
                f"shared={impact.appears_shared}; "
                "automatic_account_deletion_prohibited="
                f"{impact.automatic_account_deletion_prohibited}"
            )

        self.stdout.write("\nIntegrity checks")
        for check in inventory.integrity_checks:
            self.stdout.write(
                f"- [{check.severity.value}] {check.check_code}: "
                f"relationship={check.model_relationship}; count={check.affected_count}; "
                f"{check.explanation}"
            )

        billing = inventory.billing_assessment
        self.stdout.write("\nInvoice and billing assessment")
        self.stdout.write(f"- Invoice count: {billing.invoice_count}")
        self.stdout.write(f"- InvoiceLine count: {billing.invoice_line_count}")
        self.stdout.write(
            f"- Invoice.business deletion behavior: {billing.invoice_business_on_delete}"
        )
        self.stdout.write(
            f"- Invoice PROTECT would block deletion: "
            f"{billing.invoice_protect_would_block_delete}"
        )
        self.stdout.write(f"- Subscription present: {billing.subscription_present}")
        self.stdout.write(f"- Subscription status: {billing.subscription_status or 'none'}")
        self.stdout.write(
            f"- Provider customer identifier present: {billing.provider_customer_id_present}"
        )
        self.stdout.write(
            "- Provider subscription identifier present: "
            f"{billing.provider_subscription_id_present}"
        )
        self.stdout.write(
            f"- Provider checkout identifier present: {billing.provider_checkout_id_present}"
        )
        self.stdout.write(
            f"- Provider price identifier present: {billing.provider_price_id_present}"
        )
        self.stdout.write(f"- Correlated webhook events: {billing.correlated_webhook_event_count}")
        self.stdout.write(
            f"- Future Stripe closure required: {billing.future_stripe_closure_required}"
        )

        summary = inventory.summary
        self.stdout.write("\nSummary")
        self.stdout.write(f"- Selected Business ID: {summary.selected_business_id}")
        self.stdout.write(f"- Business slug: {summary.business_slug}")
        self.stdout.write(f"- Business active: {summary.business_is_active}")
        self.stdout.write(
            "- Total directly and indirectly owned records: "
            f"{summary.total_directly_and_indirectly_owned_records}"
        )
        self.stdout.write(f"- Shared users: {summary.shared_user_count}")
        self.stdout.write(f"- Protected/system users: {summary.protected_or_system_user_count}")
        self.stdout.write(f"- PROTECT blockers: {summary.protect_blocker_count}")
        self.stdout.write(f"- SET_NULL/orphan-risk records: {summary.set_null_orphan_risk_count}")
        self.stdout.write(
            "- Cross-tenant integrity blockers: " f"{summary.cross_tenant_integrity_blocker_count}"
        )
        self.stdout.write(f"- Correlated webhook events: {summary.correlated_webhook_event_count}")
        self.stdout.write(f"- Invoices exist: {summary.invoices_exist}")
        self.stdout.write(f"- Stripe closure required: {summary.stripe_closure_required}")
        self.stdout.write(
            f"- Overall future-purge readiness: {summary.future_purge_readiness.value}"
        )
        self.stdout.write("Informational only; this output does not authorize deletion.")
