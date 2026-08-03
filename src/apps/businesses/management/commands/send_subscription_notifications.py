from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.businesses.models import SubscriptionNotification
from apps.businesses.subscription_notifications import deliver_subscription_notification


class Command(BaseCommand):
    help = "Send pending Motionmate subscription notification outbox emails."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum number of eligible notifications to process.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report eligible notifications without sending email or changing status.",
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Include failed notifications that are eligible for manual retry.",
        )

    def handle(self, *args, **options):
        limit = int(options["limit"])
        if limit <= 0:
            raise CommandError("--limit must be greater than zero.")

        dry_run = bool(options["dry_run"])
        retry_failed = bool(options["retry_failed"])
        now = timezone.now()
        statuses = [SubscriptionNotification.Status.PENDING]
        if retry_failed:
            statuses.append(SubscriptionNotification.Status.FAILED)

        eligible = SubscriptionNotification.objects.filter(
            status__in=statuses,
            available_at__lte=now,
        ).order_by("available_at", "pk")
        total_eligible = eligible.count()
        notifications = list(eligible[:limit])
        counts: Counter[str] = Counter()

        if dry_run:
            self.stdout.write("Dry run only; no subscription notifications were sent.")
            for notification in notifications:
                self.stdout.write(
                    f"Would process #{notification.pk}: "
                    f"{notification.notification_type} to "
                    f"{notification.recipient_email or 'missing recipient'} "
                    f"({notification.status})"
                )
                counts["skipped"] += 1
        else:
            for notification in notifications:
                result = deliver_subscription_notification(
                    notification.pk,
                    retry_failed=retry_failed,
                )
                counts[result.status] += 1
                if result.status == "failed":
                    self.stderr.write(
                        f"Notification #{notification.pk} failed: {result.message}"
                    )

        processed_count = len(notifications)
        remaining = total_eligible if dry_run else eligible.count()
        self.stdout.write(f"Eligible: {total_eligible}")
        self.stdout.write(f"Processed: {processed_count}")
        self.stdout.write(f"Sent: {counts['sent']}")
        self.stdout.write(f"Failed: {counts['failed']}")
        self.stdout.write(f"Cancelled: {counts['cancelled']}")
        self.stdout.write(f"Skipped: {counts['skipped']}")
        self.stdout.write(f"Remaining eligible: {remaining}")
