import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.logistics.test_lab import audit_operation, authorize
from apps.logistics.test_lab_acceptance import (
    EVIDENCE_KINDS,
    binding,
    build_report,
    finalize,
    read_credentials,
    verify_logins,
)


class Command(BaseCommand):
    help = "Inspect lab acceptance without writes; explicitly execute nine normal login checks. Missing evidence blocks promotion."

    def add_arguments(self, parser):
        parser.add_argument(
            "--environment", required=True, choices=("local", "development", "staging")
        )
        parser.add_argument("--business-id", required=True, type=int)
        parser.add_argument("--target", required=True, choices=("development", "staging", "pilot"))
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Authenticate all nine accounts; creates/destroys sessions, updates last_login and retains a lab audit.",
        )
        parser.add_argument("--confirm-business-id", type=int)
        parser.add_argument("--confirm-database")
        parser.add_argument("--confirm-app")
        parser.add_argument("--reason-reference")
        parser.add_argument(
            "--credential-file",
            action="append",
            help="Private age-encrypted handoff; repeat for owner bootstrap plus eight-account handoff.",
        )
        parser.add_argument(
            "--credential-identity",
            help="Private age identity, both files in an operator-owned 0700 directory.",
        )
        parser.add_argument(
            "--evidence-file",
            help="Matching, recent acceptance evidence JSON. Does not execute operator/provider checks.",
        )
        parser.add_argument(
            "--evidence-template",
            action="store_true",
            help="Print a binding and pending evidence checklist for this exact environment/code/configuration.",
        )
        parser.add_argument(
            "--output", help="Create a new 0600 JSON report; existing files are never overwritten."
        )
        parser.add_argument(
            "--require-ready",
            action="store_true",
            help="Write the report then exit nonzero if promotion is blocked.",
        )

    def handle(self, *args, **options):
        environment, business_id = options["environment"], options["business_id"]
        authorize(
            environment,
            execute=options["execute"],
            confirm_database=options["confirm_database"],
            confirm_app=options["confirm_app"],
        )
        if options["evidence_template"] and (options["execute"] or options["evidence_file"]):
            raise CommandError(
                "An evidence template is read-only and cannot be combined with execution/evidence."
            )
        if not options["execute"] and (
            options["credential_file"] or options["credential_identity"]
        ):
            raise CommandError(
                "Credential retrieval requires explicit --execute and confirmed lab/database."
            )
        if options["execute"] and (
            options["confirm_business_id"] != business_id
            or not options["reason_reference"]
            or not options["credential_file"]
            or not options["credential_identity"]
        ):
            raise CommandError(
                "Login execution requires exact --confirm-business-id, --reason-reference and the secured credential file/identity."
            )
        evidence = None
        if options["evidence_file"]:
            try:
                evidence = json.loads(Path(options["evidence_file"]).read_text())
            except (OSError, ValueError):
                raise CommandError("Evidence must be readable JSON.") from None
        report = build_report(
            environment=environment,
            business_id=business_id,
            target=options["target"],
            evidence=evidence,
        )
        if options["execute"]:
            credentials = read_credentials(
                credential_file=options["credential_file"],
                credential_identity=options["credential_identity"],
                report=report,
            )
            try:
                verify_logins(report, credentials)
            finally:
                credentials.clear()
            audit_operation(
                business_id, environment, "acceptance-logins", options["reason_reference"]
            )
            finalize(report, options["target"])
        if options["evidence_template"]:
            result = {
                "binding": binding(report),
                "recorded_at": report["recorded_at"],
                "checks": {
                    name: {"status": "PENDING", "kind": kind, "operator": "", "reference": ""}
                    for name, kind in EVIDENCE_KINDS.items()
                },
            }
        else:
            report["mode"] = (
                "normal authentication executed"
                if options["execute"]
                else "read-only; zero database writes"
            )
            result = report
        serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if options["output"]:
            try:
                fd = os.open(options["output"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as artifact:
                    artifact.write(serialized)
            except OSError:
                raise CommandError(
                    "Report output must be a new writable path; existing files cannot be overwritten."
                ) from None
        self.stdout.write(serialized)
        if (
            options["require_ready"]
            and not options["evidence_template"]
            and report["verdict"] == "BLOCKED"
        ):
            raise CommandError(
                "Promotion blocked; inspect the recorded blockers. No promotion performed."
            )
