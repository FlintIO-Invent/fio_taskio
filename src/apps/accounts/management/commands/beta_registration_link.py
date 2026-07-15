from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from apps.accounts.beta_registration import get_configured_beta_registration_token


class Command(BaseCommand):
    help = "Print the configured reusable hidden Beta business registration link."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            default="",
            help="Optional public base URL, for example https://www.motionmate.net.",
        )

    def handle(self, *args, **options):
        token = get_configured_beta_registration_token()
        if not token:
            raise CommandError("BETA_REGISTRATION_TOKEN is not configured.")

        path = reverse("register_business_beta", args=[token])
        base_url = (options["base_url"] or "").strip().rstrip("/")
        self.stdout.write(f"{base_url}{path}" if base_url else path)
