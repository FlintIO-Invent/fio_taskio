import io
import json
import os
import secrets
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client as HttpClient
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice, InvoiceLine
from apps.businesses.models import (
    Business,
    BusinessDataOperation,
    BusinessUser,
    ClarivoPlan,
    DemoSeedRecord,
    DemoSeedRun,
)
from apps.crm.models import Client

from .location_access import locations_for, require_work_location
from .location_access_services import select_work_location
from .location_services import save_location
from .models import LogisticsLocation, LogisticsTestLabAudit, Parcel, Shipment
from .parcel_services import parcels_for_business, register_parcel
from .shipment_services import create_shipment, shipments_for_business
from .test_lab import ACCOUNTS, DOMAIN, SLUG, authorize, database_identity, require_entitlement


@override_settings(
    DEBUG=True,
    MOTIONMATE_ENVIRONMENT="local",
    LOGISTICS_LOCAL_BILLING_BYPASS=True,
    LOGISTICS_TEST_LAB_ENABLED=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    MOTIONMATE_PUBLIC_BASE_URL="",
)
class LogisticsTestLabTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not shutil.which("age") or not shutil.which("age-keygen"):
            raise RuntimeError("Install age and age-keygen to test the secured credential handoff.")

    def setUp(self):
        self.env = patch.dict(os.environ, {"ENV": "local", "HEROKU_APP_NAME": "", "DYNO": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.key = self.root / "identity.txt"
        subprocess.run(["age-keygen", "-o", str(self.key)], capture_output=True, check=True)
        self.recipient = subprocess.run(
            ["age-keygen", "-y", str(self.key)], capture_output=True, text=True, check=True
        ).stdout.strip()
        self.identity = database_identity()
        self.db_setting = override_settings(LOGISTICS_TEST_LAB_DATABASE_ID=self.identity)
        self.db_setting.enable()
        self.addCleanup(self.db_setting.disable)
        self.plan = ClarivoPlan.objects.get(slug="logistics")
        self.counter = 0

    def command(self, **kwargs):
        output = io.StringIO()
        environment = kwargs.pop("environment", "local")
        call_command("setup_logistics_test_lab", environment=environment, stdout=output, **kwargs)
        return output.getvalue()

    def execute(self, **kwargs):
        self.counter += 1
        self.artifact = self.root / f"credentials-{self.counter}.age"
        return self.command(
            execute=True,
            confirm_database=self.identity,
            reason_reference="TEST-06A",
            credential_file=str(self.artifact),
            credential_recipient=self.recipient,
            **kwargs,
        )

    def decrypt(self):
        result = subprocess.run(
            ["age", "--decrypt", "-i", str(self.key), str(self.artifact)],
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def provision(self):
        self.output = self.execute()
        self.payload = self.decrypt()
        self.business = Business.objects.get(slug=SLUG)
        self.seed = DemoSeedRun.objects.get(business=self.business)
        self.users = {
            name: TaskIOUser.objects.get(email=f"{name}@{DOMAIN}") for name, _, _ in ACCOUNTS
        }
        self.sites = {site.code: site for site in self.business.logistics_locations.all()}

    def test_preview_inspection_are_zero_write(self):
        for kwargs in ({}, {"inspect": True}, {"initialize": True}):
            with CaptureQueriesContext(connection) as queries:
                output = self.command(**kwargs)
            self.assertIn("zero writes", output)
            self.assertFalse(
                any(
                    q["sql"]
                    .lstrip()
                    .upper()
                    .startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
                    for q in queries
                )
            )
        self.assertFalse(Business.objects.filter(slug=SLUG).exists())

    def test_provision_login_roles_encryption_and_no_email(self):
        self.provision()
        self.assertEqual(self.business.vertical, "LOGISTICS")
        self.assertEqual(self.business.memberships.count(), 9)
        self.assertEqual(self.business.logistics_locations.count(), 4)
        self.assertEqual(self.business.logistics_profile.operating_areas, ["TRANSPORTATION"])
        self.assertEqual(
            self.business.logistics_profile.transportation_modes, ["SEA", "AIR", "ROAD"]
        )
        self.assertIsNotNone(self.business.logistics_profile.location_operations_enabled_at)
        self.assertEqual(self.business.subscription.status, "pending_checkout")
        self.assertEqual(
            self.payload["login_url"], "http://127.0.0.1:8000" + reverse("business_login")
        )
        passwords = [a["password"] for a in self.payload["accounts"]]
        self.assertEqual(len(set(passwords)), 9)
        self.assertEqual(stat.S_IMODE(self.artifact.stat().st_mode), 0o600)
        ciphertext = self.artifact.read_text()
        for account in self.payload["accounts"]:
            self.assertGreaterEqual(len(account["password"]), 40)
            self.assertNotIn(account["password"], self.output)
            self.assertNotIn(account["password"], ciphertext)
            self.assertIsNotNone(authenticate(email=account["email"], password=account["password"]))
            browser = HttpClient()
            self.assertEqual(browser.post(reverse("business_login"), account).status_code, 302)
            self.assertIn("_auth_user_id", browser.session)
        for name, role, _ in ACCOUNTS:
            self.assertEqual(self.users[name].business_memberships.get().role, role)
            self.assertFalse(self.users[name].is_staff or self.users[name].is_superuser)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Parcel.objects.count() + Shipment.objects.count(), 0)

    def test_locations_current_context_and_manager_capabilities(self):
        self.provision()
        for name, role, codes in ACCOUNTS:
            visible = set(
                locations_for(self.business, self.users[name]).values_list("code", flat=True)
            )
            self.assertEqual(visible, set(self.sites) if role in ("owner", "admin") else set(codes))
        self.assertEqual(
            require_work_location(self.business, self.users["regional"]).code, "MIA-HUB"
        )
        select_work_location(
            business=self.business, actor=self.users["regional"], location=self.sites["SXM-PORT"]
        )
        self.assertEqual(
            require_work_location(self.business, self.users["regional"]).code, "SXM-PORT"
        )
        with self.assertRaises(PermissionDenied):
            require_work_location(self.business, self.users["unassigned"])
        with self.assertRaises(PermissionDenied):
            select_work_location(
                business=self.business, actor=self.users["miami"], location=self.sites["DM-HUB"]
            )
        save_location(
            business=self.business,
            actor=self.users["manager"],
            name="Management probe",
            code="MGMT-PROBE",
            location_type="HUB",
            country_code="US",
        )
        with self.assertRaises(PermissionDenied):
            save_location(
                business=self.business,
                actor=self.users["miami"],
                name="Forbidden",
                code="NO-PROBE",
                location_type="HUB",
                country_code="US",
            )

    def test_real_parcel_shipment_scope_and_tenant_isolation(self):
        self.provision()
        customer = Client.objects.create(
            business=self.business, first_name="Fictional", last_name="Cargo customer"
        )
        for code in self.sites:
            select_work_location(
                business=self.business, actor=self.users["owner"], location=self.sites[code]
            )
            register_parcel(
                business=self.business,
                actor=self.users["owner"],
                client=customer,
                origin="Test",
                destination="Test",
                package_description="Test cargo",
                origin_location=self.sites[code],
            )
            create_shipment(
                business=self.business,
                actor=self.users["owner"],
                origin="Test",
                destination="Test",
                origin_location=self.sites[code],
                transport_mode="ROAD",
            )
        for name, role, codes in ACCOUNTS:
            expected = 4 if role in ("owner", "admin") else len(codes)
            self.assertEqual(
                parcels_for_business(business=self.business, actor=self.users[name]).count(),
                expected,
            )
            self.assertEqual(
                shipments_for_business(business=self.business, actor=self.users[name]).count(),
                expected,
            )
        other = Business.objects.create(
            name="Other customer", slug="other-tenant", vertical="LOGISTICS"
        )
        with self.assertRaises(PermissionDenied):
            parcels_for_business(business=other, actor=self.users["owner"])
        outsider = TaskIOUser.objects.create_user(
            "outsider@example.test", password=secrets.token_urlsafe(32)
        )
        with self.assertRaises(PermissionDenied):
            parcels_for_business(business=self.business, actor=outsider)
        self.assertFalse(locations_for(other, self.users["miami"]).exists())

    def test_duplicate_refuses_without_mutating_passwords(self):
        self.provision()
        hashes = list(TaskIOUser.objects.order_by("pk").values_list("password", flat=True))
        with self.assertRaisesMessage(CommandError, "already exists"):
            self.execute()
        self.assertEqual(
            hashes, list(TaskIOUser.objects.order_by("pk").values_list("password", flat=True))
        )
        self.assertFalse(self.artifact.exists())

    def test_existing_case_insensitive_identity_or_business_not_reused(self):
        existing_password = secrets.token_urlsafe(32)
        user = TaskIOUser.objects.create_user(f"OWNER@{DOMAIN.upper()}", password=existing_password)
        with self.assertRaisesMessage(CommandError, "identities exist"):
            self.execute()
        user.refresh_from_db()
        self.assertTrue(user.check_password(existing_password))
        user.delete()
        Business.objects.create(name="Real customer", slug=SLUG)
        with self.assertRaisesMessage(CommandError, "ownership"):
            self.execute()

    def test_seat_allowance_opt_in_and_database_confirmation(self):
        self.plan.max_users = 8
        self.plan.save()
        with self.assertRaisesMessage(CommandError, "nine seats"):
            self.execute()
        self.plan.max_users = 9
        self.plan.save()
        with override_settings(LOGISTICS_TEST_LAB_ENABLED=False):
            with self.assertRaisesMessage(CommandError, "opt-in"):
                self.execute()
        with override_settings(LOGISTICS_TEST_LAB_DATABASE_ID="wrong"):
            with self.assertRaisesMessage(CommandError, "fingerprint"):
                self.execute()
        with self.assertRaisesMessage(CommandError, "confirm-database"):
            self.command(execute=True, confirm_database="wrong", reason_reference="TEST")
        self.assertFalse(Business.objects.filter(slug=SLUG).exists())

    def test_initialize_then_provision_requires_entitlement(self):
        with override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False):
            self.execute(initialize=True)
            self.assertEqual(len(self.decrypt()["accounts"]), 1)
            self.assertEqual(BusinessUser.objects.count(), 1)
            self.assertEqual(LogisticsLocation.objects.count(), 0)
            with self.assertRaisesMessage(CommandError, "entitlement"):
                self.execute()
        self.execute()
        self.assertEqual(len(self.decrypt()["accounts"]), 8)
        self.assertEqual(BusinessUser.objects.count(), 9)

    def test_production_rejects_all_operations_despite_overrides(self):
        for action in (
            {},
            {"inspect": True},
            {"initialize": True},
            {"rotate_passwords": True, "business_id": 1},
            {"cleanup": True, "business_id": 1},
        ):
            for environment in ("production", "prod", "unknown"):
                with override_settings(MOTIONMATE_ENVIRONMENT=environment):
                    with self.assertRaisesMessage(CommandError, "forbidden"):
                        self.command(**action)
        with patch.dict(os.environ, {"ENV": "production"}):
            with self.assertRaisesMessage(CommandError, "forbidden"):
                self.execute()
        self.assertFalse(Business.objects.filter(slug=SLUG).exists())

    def test_local_cloud_process_and_environment_mismatch_refused(self):
        with patch.dict(os.environ, {"DYNO": "run.123"}):
            with self.assertRaisesMessage(CommandError, "local process"):
                self.execute()
        with patch.dict(os.environ, {"ENV": "staging"}):
            with self.assertRaisesMessage(CommandError, "runtime ENV"):
                self.command()

    def test_shared_authorization_requires_app_postgresql_dedicated_staging(self):
        with (
            override_settings(MOTIONMATE_ENVIRONMENT="development"),
            patch.dict(os.environ, {"ENV": "development", "HEROKU_APP_NAME": "mm-development-app"}),
        ):
            if connection.vendor == "sqlite":
                with self.assertRaisesMessage(CommandError, "PostgreSQL"):
                    authorize("development")
            with (
                patch.object(connection, "vendor", "postgresql"),
                patch("apps.logistics.test_lab.database_identity", return_value=self.identity),
            ):
                self.assertEqual(
                    authorize(
                        "development",
                        execute=True,
                        confirm_database=self.identity,
                        confirm_app="mm-development-app",
                    ),
                    self.identity,
                )
                with self.assertRaisesMessage(CommandError, "confirm-app"):
                    authorize("development", execute=True, confirm_database=self.identity)
                with patch.dict(os.environ, {"HEROKU_APP_NAME": "mm-production-app"}):
                    with self.assertRaisesMessage(CommandError, "authorized app"):
                        authorize("development")
        with (
            override_settings(
                MOTIONMATE_ENVIRONMENT="staging",
                LOGISTICS_TEST_LAB_STAGING_APP="mm-development-app",
            ),
            patch.dict(os.environ, {"ENV": "staging"}),
        ):
            with self.assertRaisesMessage(CommandError, "dedicated"):
                authorize("staging")

    def test_shared_entitlement_rejects_bypass_pending_and_live_keys(self):
        self.provision()
        with override_settings(
            STRIPE_ENABLED=True,
            STRIPE_SECRET_KEY="sk_test_example",
            STRIPE_PUBLISHABLE_KEY="pk_test_example",
        ):
            with self.assertRaisesMessage(CommandError, "legitimate Stripe TEST"):
                require_entitlement(self.business.subscription, "development")
        with override_settings(
            STRIPE_ENABLED=True,
            STRIPE_SECRET_KEY="sk_live_example",
            STRIPE_PUBLISHABLE_KEY="pk_live_example",
        ):
            with self.assertRaisesMessage(CommandError, "Stripe TEST billing"):
                require_entitlement(self.business.subscription, "staging")

    def test_encryption_failure_rolls_back_every_record(self):
        with patch(
            "apps.logistics.test_lab.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "age", stderr=b"provider details"),
        ):
            with self.assertRaisesMessage(CommandError, "Encrypted handoff failed"):
                self.execute()
        self.assertFalse(Business.objects.filter(slug=SLUG).exists())
        self.assertFalse(TaskIOUser.objects.filter(email__endswith=DOMAIN).exists())
        self.assertFalse(self.artifact.exists())

    def test_artifact_requires_private_directory_new_file_valid_recipient(self):
        artifact = self.root / "existing.age"
        artifact.write_text("existing")
        with self.assertRaisesMessage(CommandError, "already exists"):
            self.command(
                execute=True,
                confirm_database=self.identity,
                reason_reference="TEST",
                credential_file=str(artifact),
                credential_recipient=self.recipient,
            )
        os.chmod(self.root, 0o755)
        with self.assertRaisesMessage(CommandError, "0700"):
            self.execute()
        os.chmod(self.root, 0o700)
        with self.assertRaisesMessage(CommandError, "age public"):
            self.command(
                execute=True,
                confirm_database=self.identity,
                reason_reference="TEST",
                credential_file=str(self.root / "invalid.age"),
                credential_recipient="invalid",
            )
        self.assertFalse(Business.objects.filter(slug=SLUG).exists())

    def test_rotation_changes_only_owned_passwords_and_invalidates_sessions(self):
        self.provision()
        Client.objects.create(business=self.business, first_name="Existing", last_name="Lab cargo")
        customer_password = secrets.token_urlsafe(32)
        customer = TaskIOUser.objects.create_user(
            "real-customer@example.test", password=customer_password
        )
        with self.assertRaisesMessage(CommandError, "confirm-business-id"):
            self.execute(rotate_passwords=True, business_id=self.business.pk)
        browser = HttpClient()
        browser.post(reverse("business_login"), self.payload["accounts"][0])
        old_session = browser.session.session_key
        output = self.execute(
            rotate_passwords=True,
            business_id=self.business.pk,
            confirm_business_id=self.business.pk,
        )
        for account in self.decrypt()["accounts"]:
            self.assertNotIn(account["password"], output)
            self.assertIsNotNone(authenticate(email=account["email"], password=account["password"]))
        for account in self.payload["accounts"]:
            self.assertIsNone(authenticate(email=account["email"], password=account["password"]))
        customer.refresh_from_db()
        self.assertTrue(customer.check_password(customer_password))
        from django.contrib.sessions.models import Session

        self.assertFalse(Session.objects.filter(session_key=old_session).exists())
        self.seed.refresh_from_db()
        self.assertEqual(self.seed.planned_counts["rotations"], 1)

    def cleanup(self, execute=False):
        return self.command(
            cleanup=True,
            execute=execute,
            business_id=self.business.pk,
            confirm_business_id=self.business.pk,
            reason_reference="TEST-CLEANUP",
            confirm_database=self.identity,
        )

    def test_cleanup_preview_audit_rebuild_preserve_service(self):
        service = Business.objects.create(
            name="Service customer", slug="service-customer", vertical="SERVICE"
        )
        customer_password = secrets.token_urlsafe(32)
        customer = TaskIOUser.objects.create_user(
            "service@example.test", password=customer_password
        )
        BusinessUser.objects.create(business=service, user=customer, role="owner")
        self.provision()
        with CaptureQueriesContext(connection) as queries:
            self.cleanup()
        self.assertFalse(
            any(q["sql"].upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries)
        )
        self.cleanup(execute=True)
        self.assertFalse(Business.objects.filter(slug=SLUG).exists())
        self.assertFalse(TaskIOUser.objects.filter(email__endswith=DOMAIN).exists())
        self.assertFalse(DemoSeedRecord.objects.exists() or DemoSeedRun.objects.exists())
        self.assertEqual(BusinessDataOperation.objects.get().status, "completed")
        self.assertTrue(
            Business.objects.filter(pk=service.pk, vertical="SERVICE", is_active=True).exists()
        )
        customer.refresh_from_db()
        self.assertTrue(customer.check_password(customer_password))
        original = {a["password"] for a in self.payload["accounts"]}
        self.execute()
        self.assertTrue(original.isdisjoint({a["password"] for a in self.decrypt()["accounts"]}))

    def test_cleanup_blocks_unowned_records_and_stripe_references(self):
        self.provision()
        client = Client.objects.create(
            business=self.business, first_name="Retained", last_name="Customer"
        )
        with self.assertRaisesMessage(CommandError, "Unowned crm.Client"):
            self.cleanup(execute=True)
        self.assertTrue(Client.objects.filter(pk=client.pk).exists())
        self.business.refresh_from_db()
        self.assertTrue(self.business.is_active)
        client.delete()
        subscription = self.business.subscription
        subscription.provider_customer_id = "cus_test_must_still_block_purge"
        subscription.save()
        with self.assertRaisesMessage(CommandError, "stripe_references_present"):
            self.cleanup(execute=True)
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())

    def test_cleanup_blocks_cross_tenant_membership_and_changed_marker(self):
        self.provision()
        other = Business.objects.create(name="Other", slug="other")
        member = BusinessUser.objects.create(
            business=other, user=self.users["regional"], role="staff"
        )
        with self.assertRaisesMessage(CommandError, "Unowned businesses.BusinessUser"):
            self.cleanup(execute=True)
        member.delete()
        self.seed.planned_counts["environment"] = "staging"
        self.seed.save()
        with self.assertRaisesMessage(CommandError, "ownership"):
            self.cleanup(execute=True)

    def test_exact_business_confirmation_and_reason(self):
        self.provision()
        with self.assertRaisesMessage(CommandError, "confirm-business-id"):
            self.command(
                cleanup=True,
                execute=True,
                business_id=self.business.pk,
                confirm_business_id=self.business.pk + 1,
                reason_reference="TEST",
                confirm_database=self.identity,
            )
        with self.assertRaisesMessage(CommandError, "reason-reference"):
            self.command(
                cleanup=True,
                execute=True,
                business_id=self.business.pk,
                confirm_business_id=self.business.pk,
                confirm_database=self.identity,
            )
        with self.assertRaisesMessage(CommandError, "Exact business ID"):
            self.command(inspect=True, business_id=self.business.pk + 1)

    def test_separately_approved_entitlement_is_audited_and_shared_provisioning_works(self):
        self.plan.is_active = True
        self.plan.max_users = 9
        self.plan.save()
        # Platform authorization is independently tested; this exercises the shared lifecycle.
        with (
            override_settings(
                MOTIONMATE_ENVIRONMENT="development", LOGISTICS_LOCAL_BILLING_BYPASS=False
            ),
            patch.dict(os.environ, {"ENV": "development"}),
            patch(
                "apps.logistics.management.commands.setup_logistics_test_lab.authorize",
                return_value=self.identity,
            ),
            patch("apps.logistics.test_lab.authorize", return_value=self.identity),
        ):
            self.execute(environment="development", initialize=True)
            business = Business.objects.get(slug=SLUG)
            with self.assertRaisesMessage(CommandError, "configured approval"):
                self.command(
                    environment="development",
                    activate_test_entitlement=True,
                    business_id=business.pk,
                    test_entitlement_approval="UNAPPROVED",
                )
            with override_settings(LOGISTICS_TEST_LAB_ENTITLEMENT_APPROVAL="APPROVED-LAB-06A"):
                self.command(
                    environment="development",
                    activate_test_entitlement=True,
                    execute=True,
                    business_id=business.pk,
                    confirm_business_id=business.pk,
                    reason_reference="GRANT-CHANGE-06A",
                    test_entitlement_approval="APPROVED-LAB-06A",
                )
            subscription = business.subscription
            self.assertEqual(subscription.status, "active")
            self.assertEqual(subscription.payment_provider, "local")
            self.assertEqual(subscription.provisioning_source, "free_test")
            self.assertFalse(
                subscription.provider_customer_id or subscription.provider_subscription_id
            )
            audit = LogisticsTestLabAudit.objects.get(action="test-entitlement")
            self.assertEqual(audit.approval_reference, "APPROVED-LAB-06A")
            self.assertEqual(audit.reason_reference, "GRANT-CHANGE-06A")
            self.execute(environment="development", business_id=business.pk)
            self.assertEqual(business.memberships.count(), 9)
            self.assertEqual(len(self.decrypt()["accounts"]), 8)
            self.command(
                environment="development",
                cleanup=True,
                execute=True,
                business_id=business.pk,
                confirm_business_id=business.pk,
                reason_reference="CLEANUP-06A",
            )
            self.assertTrue(LogisticsTestLabAudit.objects.filter(pk=audit.pk).exists())
            self.assertFalse(Business.objects.filter(pk=business.pk).exists())

    def test_entitlement_action_refuses_inactive_plan_and_stripe_identity(self):
        self.execute(initialize=True)
        business = Business.objects.get(slug=SLUG)
        with override_settings(LOGISTICS_TEST_LAB_ENTITLEMENT_APPROVAL="APPROVED-LAB"):
            with self.assertRaisesMessage(CommandError, "offering must be active"):
                self.command(
                    activate_test_entitlement=True,
                    business_id=business.pk,
                    test_entitlement_approval="APPROVED-LAB",
                )
            self.plan.is_active = True
            self.plan.save()
            subscription = business.subscription
            subscription.provider_checkout_session_id = "cs_retained_test_session"
            subscription.save()
            with self.assertRaisesMessage(CommandError, "without Stripe references"):
                self.command(
                    activate_test_entitlement=True,
                    business_id=business.pk,
                    test_entitlement_approval="APPROVED-LAB",
                )
        self.assertFalse(LogisticsTestLabAudit.objects.filter(action="test-entitlement").exists())

    def test_cleanup_preserves_financial_records_without_override(self):
        self.provision()
        client = Client.objects.create(
            business=self.business, first_name="Retained", last_name="Client"
        )
        invoice = Invoice.objects.create(
            business=self.business, client=client, invoice_number="RETAINED-001", status="PAID"
        )
        line = InvoiceLine.objects.create(
            invoice=invoice, description="Retained financial line", quantity=1, unit_price=50
        )
        with self.assertRaises(CommandError):
            self.cleanup(execute=True)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk, status="PAID").exists())
        self.assertTrue(InvoiceLine.objects.filter(pk=line.pk).exists())
        self.assertFalse(BusinessDataOperation.objects.exists())

    def test_changed_membership_cannot_delete_unowned_customer_user(self):
        self.provision()
        customer_password = secrets.token_urlsafe(32)
        real_user = TaskIOUser.objects.create_user(
            "real-user@example.test", password=customer_password
        )
        BusinessUser.objects.filter(business=self.business, user=self.users["miami"]).update(
            user=real_user
        )
        with self.assertRaisesMessage(CommandError, "unowned user"):
            self.cleanup(execute=True)
        real_user.refresh_from_db()
        self.assertTrue(real_user.check_password(customer_password))

    def test_service_entrypoint_independently_rejects_production(self):
        from .test_lab import execute_lab

        with override_settings(MOTIONMATE_ENVIRONMENT="production"):
            with self.assertRaisesMessage(CommandError, "forbidden"):
                execute_lab(
                    environment="local",
                    action="initialize",
                    identity=self.identity,
                    reason_reference="NO-PROD",
                )

    def test_login_url_uses_configured_loopback_port(self):
        from .test_lab import login_url

        with override_settings(MOTIONMATE_PUBLIC_BASE_URL="http://127.0.0.1:8016"):
            self.assertEqual(login_url(), "http://127.0.0.1:8016/accounts/login/")
        with override_settings(MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net"):
            self.assertEqual(login_url(), "http://127.0.0.1:8000/accounts/login/")
