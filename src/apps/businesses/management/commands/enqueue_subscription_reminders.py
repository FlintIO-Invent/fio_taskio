from __future__ import annotations

from datetime import UTC

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.businesses.models import SubscriptionNotification
from apps.businesses.subscription_reminders import (
    enqueue_due_subscription_reminders,
)


class Command(BaseCommand):
    help = "Discover due Motionmate subscription reminders and enqueue outbox rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of candidate subscriptions to evaluate.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report due reminders without creating outbox rows or sending email.",
        )
        parser.add_argument(
            "--at",
            default=None,
            help="Timezone-aware ISO-8601 evaluation time, for example 2026-08-01T12:00:00+00:00.",
        )
        parser.add_argument(
            "--type",
            choices=[
                SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS,
                SubscriptionNotification.NotificationType.TRIAL_ENDING_1_DAY,
                SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY,
                SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED,
            ],
            default=None,
            help="Only discover one subscription reminder type.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is not None and limit <= 0:
            raise CommandError("--limit must be greater than zero.")

        try:
            evaluation_time = _parse_evaluation_time(options["at"])
            summary = enqueue_due_subscription_reminders(
                evaluation_time=evaluation_time,
                limit=limit,
                dry_run=bool(options["dry_run"]),
                notification_type=options["type"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        prefix = "would be enqueued" if options["dry_run"] else "enqueued"
        self.stdout.write(
            f"Evaluation time: {summary.evaluation_time.astimezone(UTC).isoformat()}"
        )
        if options["dry_run"]:
            self.stdout.write("Dry run only; no subscription reminders were enqueued or sent.")
        self.stdout.write(f"Candidate subscriptions found: {summary.candidate_count}")
        self.stdout.write(f"Eligible subscriptions evaluated: {summary.evaluated_count}")
        self.stdout.write(
            "Trial three-day reminders "
            f"{prefix}: {summary.created_counts[SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS]}"
        )
        self.stdout.write(
            "Trial one-day reminders "
            f"{prefix}: {summary.created_counts[SubscriptionNotification.NotificationType.TRIAL_ENDING_1_DAY]}"
        )
        self.stdout.write(
            "Grace one-day reminders "
            f"{prefix}: {summary.created_counts[SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY]}"
        )
        self.stdout.write(
            "Restricted-mode notifications "
            f"{prefix}: {summary.created_counts[SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED]}"
        )
        self.stdout.write(f"Duplicates skipped: {summary.duplicate_count}")
        self.stdout.write(f"Ineligible or stale states skipped: {summary.ineligible_or_stale_count}")
        self.stdout.write(f"Malformed states skipped: {summary.malformed_state_count}")


def _parse_evaluation_time(value: str | None):
    if not value:
        return timezone.now()
    parsed = parse_datetime(value)
    if parsed is None:
        raise CommandError("--at must be a valid ISO-8601 datetime.")
    if timezone.is_naive(parsed):
        raise CommandError("--at must include a timezone offset, for example +00:00.")
    return parsed
