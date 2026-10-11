import io
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings

from apps.businesses.models import Business, ClarivoPlan
from apps.crm.models import Client

from .models import LogisticsTestLabAudit, Parcel, Shipment
from .test_lab import SLUG, database_identity


@skipUnless(connection.vendor == "postgresql", "Dataset serialization requires PostgreSQL")
@override_settings(
    DEBUG=True,
    MOTIONMATE_ENVIRONMENT="local",
    LOGISTICS_LOCAL_BILLING_BYPASS=True,
    LOGISTICS_TEST_LAB_ENABLED=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class LogisticsTestLabDatasetConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_simultaneous_seed_creates_exactly_one_dataset(self):
        ClarivoPlan.objects.get_or_create(
            slug="logistics",
            defaults={"name": "Logistics", "family": "LOGISTICS", "allow_invoicing": True},
        )
        identity = database_identity()
        barrier = Barrier(2)
        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(LOGISTICS_TEST_LAB_DATABASE_ID=identity),
            patch.dict(os.environ, {"ENV": "local", "DYNO": "", "HEROKU_APP_NAME": ""}),
        ):
            key = Path(directory) / "identity.txt"
            subprocess.run(["age-keygen", "-o", str(key)], capture_output=True, check=True)
            recipient = subprocess.run(
                ["age-keygen", "-y", str(key)], capture_output=True, text=True, check=True
            ).stdout.strip()
            call_command(
                "setup_logistics_test_lab",
                environment="local",
                execute=True,
                confirm_database=identity,
                reason_reference="CONCURRENCY-FOUNDATION",
                credential_file=str(Path(directory) / "credentials.age"),
                credential_recipient=recipient,
                stdout=io.StringIO(),
            )
            business_id = Business.objects.get(slug=SLUG).pk

            def worker(number):
                close_old_connections()
                try:
                    barrier.wait(timeout=15)
                    call_command(
                        "seed_logistics_test_lab",
                        environment="local",
                        business_id=business_id,
                        execute=True,
                        confirm_business_id=business_id,
                        confirm_database=identity,
                        reason_reference=f"CONCURRENCY-{number}",
                        stdout=io.StringIO(),
                    )
                    return "created"
                except CommandError:
                    return "refused"
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(worker, (1, 2)))
            self.assertCountEqual(results, ["created", "refused"])
            self.assertEqual(Client.objects.count(), 12)
            self.assertEqual(Parcel.objects.count(), 40)
            self.assertEqual(Shipment.objects.count(), 10)
            self.assertEqual(LogisticsTestLabAudit.objects.filter(action="dataset-seed").count(), 1)
