from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.crm.importing.retention import cleanup_import_jobs


class Command(BaseCommand):
    help = "Expire stale import jobs and enforce import preview/metadata retention."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report cleanup counts without changing ImportJob records.",
        )
        parser.add_argument(
            "--business-id",
            type=int,
            help="Optionally limit cleanup to one exact Business ID.",
        )

    def handle(self, *args, **options):
        try:
            result = cleanup_import_jobs(
                business_id=options.get("business_id"),
                dry_run=options["dry_run"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        mode = "DRY RUN" if result.dry_run else "COMPLETED"
        scope = (
            f"business_id={options['business_id']}"
            if options.get("business_id") is not None
            else "all businesses"
        )
        self.stdout.write(f"Import job cleanup {mode} ({scope}).")
        self.stdout.write(
            f"Stale jobs to expire: {result.stale_jobs_marked_expired}"
        )
        self.stdout.write(
            f"Preview payloads to clear: {result.preview_payloads_cleared}"
        )
        self.stdout.write(
            f"Metadata jobs to delete: {result.metadata_jobs_deleted}"
        )
