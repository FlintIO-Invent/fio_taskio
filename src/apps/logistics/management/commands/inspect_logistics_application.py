import json
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from apps.logistics.inventory import application_inventory
from apps.logistics.models import LogisticsApplication


class Command(BaseCommand):
    help = "Inspect one Logistics application and its decision/retention inventory without changing data."

    def add_arguments(self, parser):
        parser.add_argument("--application-id", required=True, type=UUID)

    def handle(self, *args, **options):
        try:
            inventory = application_inventory(options["application_id"])
        except LogisticsApplication.DoesNotExist as exc:
            raise CommandError("Logistics application not found.") from exc
        self.stdout.write(json.dumps(inventory, sort_keys=True, indent=2))
