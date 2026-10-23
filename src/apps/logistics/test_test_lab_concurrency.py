import io
import os
import shutil
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

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessUser, ClarivoPlan, DemoSeedRun

from . import test_lab
from .models import LogisticsTestLabAudit


@skipUnless(connection.vendor == "postgresql", "Lab creation serialization requires PostgreSQL")
@override_settings(
    DEBUG=True,
    MOTIONMATE_ENVIRONMENT="local",
    LOGISTICS_LOCAL_BILLING_BYPASS=True,
    LOGISTICS_TEST_LAB_ENABLED=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class LogisticsTestLabConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_simultaneous_first_provision_has_one_lab_and_one_handoff(self):
        self.assertTrue(shutil.which("age") and shutil.which("age-keygen"))
        ClarivoPlan.objects.get_or_create(
            slug="logistics", defaults={"name": "Logistics", "family": "LOGISTICS"}
        )
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key.txt"
            subprocess.run(["age-keygen", "-o", str(key)], capture_output=True, check=True)
            recipient = subprocess.run(
                ["age-keygen", "-y", str(key)], capture_output=True, text=True, check=True
            ).stdout.strip()
            identity = test_lab.database_identity()
            barrier = Barrier(2)
            original = test_lab.lab_for

            def synchronized_lookup(*args, **kwargs):
                result = original(*args, **kwargs)
                if kwargs.get("lock"):
                    barrier.wait(timeout=15)
                return result

            def worker(number):
                close_old_connections()
                try:
                    call_command(
                        "setup_logistics_test_lab",
                        environment="local",
                        execute=True,
                        confirm_database=identity,
                        reason_reference="LAB-CONCURRENCY",
                        credential_file=str(Path(directory) / f"{number}.age"),
                        credential_recipient=recipient,
                        stdout=io.StringIO(),
                    )
                    return "created"
                except CommandError:
                    return "refused"
                finally:
                    connections.close_all()

            with (
                override_settings(LOGISTICS_TEST_LAB_DATABASE_ID=identity),
                patch.dict(os.environ, {"ENV": "local", "DYNO": "", "HEROKU_APP_NAME": ""}),
                patch("apps.logistics.test_lab.lab_for", side_effect=synchronized_lookup),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                results = list(pool.map(worker, (1, 2)))
            self.assertCountEqual(results, ["created", "refused"])
            self.assertEqual(len(list(Path(directory).glob("*.age"))), 1)
            self.assertEqual(Business.objects.filter(slug=test_lab.SLUG).count(), 1)
            self.assertEqual(DemoSeedRun.objects.count(), 1)
            self.assertEqual(BusinessUser.objects.count(), 9)
            self.assertEqual(TaskIOUser.objects.count(), 9)
            self.assertEqual(LogisticsTestLabAudit.objects.filter(action="provision").count(), 1)
