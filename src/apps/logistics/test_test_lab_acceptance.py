import copy
import hashlib
import importlib.util
import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client as HTTPClient
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.businesses.models import Business, BusinessSubscription, BusinessUser
from apps.crm.models import Client

from . import test_test_lab_dataset as dataset_tests
from .billing_services import add_charge, invoice_charges
from .models import LogisticsLocation, Parcel, ParcelEvent, Shipment
from .parcel_services import edit_parcel, parcels_for_business, register_parcel
from .public_tracking import lookup_public_tracking
from .scan import resolve_scanned_parcel
from .shipment_services import (
    assign_parcel,
    change_shipment_status,
    create_shipment,
    generate_manifest,
)
from .test_lab import DOMAIN, encrypted_handoff
from .test_lab_acceptance import (
    EVIDENCE_KINDS,
    PILOT_GATES,
    SCHEMA,
    apply_evidence,
    binding,
    build_report,
    finalize,
    read_credentials,
)
from .test_lab_dataset import work_at


class PromotionEvidenceTests(SimpleTestCase):
    def test_production_rejects_direct_credential_and_login_helpers_before_io(self):
        from .test_lab_acceptance import verify_logins

        with (
            override_settings(MOTIONMATE_ENVIRONMENT="production"),
            patch.dict("os.environ", {"ENV": "production"}),
            patch.object(Path, "lstat") as file_access,
        ):
            with self.assertRaisesMessage(CommandError, "forbidden in production"):
                read_credentials(
                    credential_file="missing.age",
                    credential_identity="missing.key",
                    report={"environment": "local"},
                )
            with self.assertRaisesMessage(CommandError, "forbidden in production"):
                verify_logins({"environment": "local"}, {})
            file_access.assert_not_called()

    def report(self, environment="local"):
        return {
            "schema": SCHEMA,
            "environment": environment,
            "database_id": "a" * 64,
            "business_id": 1,
            "foundation_version": "foundation",
            "dataset_version": "dataset",
            "commit_sha": "b" * 40,
            "tree_digest": "c" * 64,
            "configuration_digest": "d" * 64,
            "checks": {name: {"status": "PASS"} for name in PILOT_GATES},
        }

    def evidence(self, report, name="physical_android"):
        return {
            "binding": binding(report),
            "recorded_at": timezone.now().isoformat(),
            "checks": {
                name: {
                    "status": "PASS",
                    "kind": EVIDENCE_KINDS[name],
                    "operator": "Test operator",
                    "reference": "private acceptance record",
                },
            },
        }

    def test_missing_evidence_and_optional_failure_block_promotion(self):
        report = self.report()
        report["checks"]["login_http"]["status"] = "PENDING"
        self.assertEqual(finalize(report, "development")["verdict"], "BLOCKED")
        report["checks"]["login_http"]["status"] = "PASS"
        self.assertEqual(finalize(report, "development")["verdict"], "READY FOR NEXT ENVIRONMENT")
        report["checks"]["physical_iphone"]["status"] = "FAIL"
        self.assertEqual(finalize(report, "development")["verdict"], "BLOCKED")

    def test_pilot_needs_real_devices_printing_and_operator_approval(self):
        for name in (
            "physical_android",
            "physical_iphone",
            "physical_qr_code128",
            "label_print_4x6",
            "stripe_test",
            "promotion_approval",
        ):
            report = self.report("staging")
            report["checks"][name]["status"] = "PENDING"
            self.assertEqual(
                finalize(report, "pilot")["pilot_verdict"], "NOT READY FOR SUPERVISED PILOT"
            )
        self.assertEqual(
            finalize(self.report("staging"), "pilot")["pilot_verdict"], "READY FOR SUPERVISED PILOT"
        )

    def test_cannot_skip_environment_or_claim_emulation_as_physical(self):
        with self.assertRaises(CommandError):
            finalize(self.report(), "pilot")
        report = self.report("staging")
        evidence = self.evidence(report)
        evidence["checks"]["physical_android"]["kind"] = "browser-emulation"
        with self.assertRaises(CommandError):
            apply_evidence(report, evidence)

    def test_evidence_must_match_every_identity_and_be_recent(self):
        report = self.report()
        for key in binding(report):
            evidence = self.evidence(report)
            evidence["binding"][key] = "another environment/code/configuration"
            with self.subTest(key=key), self.assertRaises(CommandError):
                apply_evidence(report, evidence)
        for time in (timezone.now() - timedelta(days=8), timezone.now() + timedelta(hours=1)):
            evidence = self.evidence(report)
            evidence["recorded_at"] = time.isoformat()
            with self.assertRaises(CommandError):
                apply_evidence(report, evidence)

    def test_inspection_and_login_cannot_be_overridden(self):
        report = self.report()
        for name in ("login_http", "foundation", "reviewed_release"):
            evidence = self.evidence(report)
            evidence["checks"] = {name: {"status": "PASS", "kind": "operator"}}
            with self.assertRaises(CommandError):
                apply_evidence(report, evidence)

    def test_automated_results_need_nonempty_zero_skip_success_and_raw_log_digest(self):
        report = self.report()
        evidence = self.evidence(report, "automated_suite")
        entry = evidence["checks"]["automated_suite"]
        entry.update(exit_code=0, tests=10, failures=0, errors=0, skipped=0, log_sha256="e" * 64)
        apply_evidence(report, evidence)
        for key, value in (
            ("tests", 0),
            ("skipped", 1),
            ("exit_code", 1),
            ("errors", 1),
            ("failures", 1),
            ("log_sha256", "missing"),
        ):
            broken = copy.deepcopy(evidence)
            broken["checks"]["automated_suite"][key] = value
            with self.subTest(key=key), self.assertRaises(CommandError):
                apply_evidence(report, broken)

    def test_collector_rejects_tampered_stale_code_skips_and_changed_source(self):
        spec = importlib.util.spec_from_file_location(
            "acceptance_collector",
            Path(__file__).resolve().parents[3] / "scripts/collect_logistics_test_lab_evidence.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = self.report()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "tests.log"
            log.write_text("Ran 1 test. OK.")
            results = {
                "suite": "browser",
                "status": "PASS",
                "tests": 1,
                "errors": 0,
                "failures": 0,
                "skipped": 0,
                "exit_code": 0,
                "code_changed_during_run": False,
                "planned_tests": 1,
                "interrupted": False,
                "commit_sha": report["commit_sha"],
                "tree_digest": report["tree_digest"],
                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            }
            (root / "results.json").write_text(json.dumps(results))
            evidence = module.collect(report, [root], "Test operator")
            self.assertEqual(set(evidence["checks"]), {"browser"})
            apply_evidence(report, evidence)
            for key, value in (
                ("skipped", 1),
                ("code_changed_during_run", True),
                ("planned_tests", 2),
                ("interrupted", True),
                ("tree_digest", "another tree"),
                ("exit_code", 1),
            ):
                (root / "results.json").write_text(json.dumps({**results, key: value}))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    module.collect(report, [root], "Test operator")
            (root / "results.json").write_text(json.dumps(results))
            log.write_text("Tampered raw log")
            with self.assertRaises(ValueError):
                module.collect(report, [root], "Test operator")


@override_settings(
    DEBUG=True,
    MOTIONMATE_ENVIRONMENT="local",
    LOGISTICS_LOCAL_BILLING_BYPASS=True,
    LOGISTICS_TEST_LAB_ENABLED=True,
    MOTIONMATE_PUBLIC_BASE_URL="http://testserver",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class TestLabAcceptanceTests(TestCase):
    setUp = dataset_tests.LogisticsTestLabDatasetTests.setUp
    command = dataset_tests.LogisticsTestLabDatasetTests.command
    execute = dataset_tests.LogisticsTestLabDatasetTests.execute
    decrypt = dataset_tests.LogisticsTestLabDatasetTests.decrypt
    provision = dataset_tests.LogisticsTestLabDatasetTests.provision
    data_command = dataset_tests.LogisticsTestLabDatasetTests.data_command
    seed_data = dataset_tests.LogisticsTestLabDatasetTests.seed_data

    def lab(self):
        self.provision()
        self.seed_data()
        self.seed.refresh_from_db()

    def http(self, name):
        client = HTTPClient(enforce_csrf_checks=True)
        client.get(reverse("business_login"))
        credential = next(a for a in self.payload["accounts"] if a["email"] == f"{name}@{DOMAIN}")
        response = client.post(
            reverse("business_login"),
            {**credential, "csrfmiddlewaretoken": client.cookies["csrftoken"].value},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", client.session)
        return client

    def post(self, client, name, data, args=()):
        return client.post(
            reverse(name, args=args),
            {**data, "csrfmiddlewaretoken": client.cookies["csrftoken"].value},
        )

    def acceptance(self, **kwargs):
        output = io.StringIO()
        call_command(
            "accept_logistics_test_lab",
            environment="local",
            business_id=self.business.pk,
            target="development",
            stdout=output,
            **kwargs,
        )
        return json.loads(output.getvalue())

    def test_report_preview_zero_writes_and_all_nine_secured_normal_logins(self):
        self.lab()
        connection.queries_log.clear()
        with CaptureQueriesContext(connection) as queries:
            report = self.acceptance()
        self.assertTrue(queries)
        self.assertFalse(
            any(
                q["sql"]
                .lstrip()
                .upper()
                .startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
                for q in queries
            )
        )
        for name in ("foundation", "dataset", "migrations", "location_querysets"):
            self.assertEqual(report["checks"][name]["status"], "PASS", report)
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(report["checks"]["login_http"]["status"], "PENDING")
        with self.assertRaisesMessage(CommandError, "Promotion blocked"):
            self.acceptance(require_ready=True)
        executed = self.acceptance(
            execute=True,
            confirm_business_id=self.business.pk,
            confirm_database=self.identity,
            reason_reference="TEST-06C",
            credential_file=str(self.artifact),
            credential_identity=str(self.key),
        )
        self.assertEqual(executed["checks"]["login_http"]["status"], "PASS")
        self.assertEqual(len(executed["accounts"]), 9)
        self.assertTrue(all(a["login"] == "PASS" for a in executed["accounts"]))
        serialized = json.dumps(executed)
        for account in self.payload["accounts"]:
            self.assertNotIn(account["password"], serialized)
        split_files = []
        for index, accounts in enumerate(
            (self.payload["accounts"][:1], self.payload["accounts"][1:])
        ):
            path = self.root / f"split-{index}.age"
            encrypted_handoff(path, self.recipient, {**self.payload, "accounts": accounts})
            split_files.append(path)
        combined = read_credentials(
            credential_file=split_files, credential_identity=self.key, report=executed
        )
        self.assertEqual(set(combined), {a["email"] for a in executed["accounts"]})
        combined.clear()
        with self.assertRaises(CommandError):
            read_credentials(
                credential_file=[split_files[0]], credential_identity=self.key, report=executed
            )
        with self.assertRaises(CommandError):
            read_credentials(
                credential_file=[split_files[0], split_files[0]],
                credential_identity=self.key,
                report=executed,
            )
        split_files[0].chmod(0o644)
        with self.assertRaises(CommandError):
            read_credentials(
                credential_file=split_files, credential_identity=self.key, report=executed
            )
        self.assertEqual(ParcelEvent.objects.count(), 179)
        self.assertEqual(self.acceptance()["checks"]["dataset"]["status"], "PASS")
        for environment in ("production", "prod", "unknown"):
            with (
                override_settings(MOTIONMATE_ENVIRONMENT=environment),
                patch.dict("os.environ", {"ENV": environment}),
                self.assertRaises(CommandError),
            ):
                self.acceptance(
                    execute=True,
                    confirm_business_id=self.business.pk,
                    confirm_database=self.identity,
                    reason_reference="REJECT",
                    credential_file=str(self.artifact),
                    credential_identity=str(self.key),
                )

    def test_nine_account_direct_urls_post_actions_exports_and_scanner_matrix(self):
        self.lab()
        report = build_report(
            environment="local", business_id=self.business.pk, target="development"
        )
        for account in report["accounts"]:
            name = account["email"].split("@")[0]
            actor = self.users[name]
            client = self.http(name)
            visible = set(
                parcels_for_business(business=self.business, actor=actor).values_list(
                    "pk", flat=True
                )
            )
            for parcel in Parcel.objects.filter(business=self.business):
                resolved = resolve_scanned_parcel(
                    business=self.business, actor=actor, code=parcel.tracking_code
                )
                self.assertEqual(resolved is not None, parcel.pk in visible, name)
            allowed = Parcel.objects.filter(pk__in=visible).first()
            denied = Parcel.objects.exclude(pk__in=visible).first()
            for parcel, status in ((allowed, 200), (denied, 404)):
                if parcel is None:
                    continue
                for route in (
                    "logistics_parcel_detail",
                    "logistics_shipping_label",
                    "logistics_shipping_label_pdf",
                ):
                    response = client.get(reverse(route, args=[parcel.pk]))
                    self.assertEqual(response.status_code, status, (name, route))
                    self.assertIn("no-store", response["Cache-Control"])
                lookup = self.post(
                    client, "logistics_parcel_scan", {"tracking_code": parcel.tracking_code}
                )
                self.assertEqual(lookup.status_code, status)
            if denied:
                for route, data in (
                    ("logistics_parcel_update", {"status": "RECEIVED"}),
                    (
                        "logistics_parcel_scan_action",
                        {
                            "status": "RECEIVED",
                            "expected_status": denied.current_status,
                            "idempotency_key": str(uuid4()),
                        },
                    ),
                    ("logistics_parcel_charge", {"description": "Unauthorized", "amount": "1.00"}),
                ):
                    response = self.post(client, route, data, [denied.pk])
                    self.assertIn(response.status_code, (403, 404), (name, route))
            for shipment in Shipment.objects.all():
                readable = (
                    account["business_wide"]
                    or shipment.origin_location.code in account["locations"]
                    or shipment.destination_location.code in account["locations"]
                )
                response = client.get(reverse("logistics_shipment_manifest", args=[shipment.pk]))
                self.assertEqual(response.status_code, 200 if readable else 404, name)
            self.assertEqual(
                client.get(reverse("logistics_location_access")).status_code,
                200 if account["business_wide"] else 403,
            )
            if not account["business_wide"]:
                forbidden = next(
                    site for site in self.sites.values() if site.code not in account["locations"]
                )
                self.assertEqual(
                    self.post(
                        client, "logistics_work_location", {"location": forbidden.pk}
                    ).status_code,
                    403,
                )
            self.assertEqual(
                client.post(
                    reverse("logistics_work_location"), {"location": self.sites["MIA-HUB"].pk}
                ).status_code,
                403,
            )  # CSRF
            client.get(reverse("logout"))
            self.assertNotIn("_auth_user_id", client.session)
            self.assertEqual(client.get(reverse("logistics_parcel_list")).status_code, 302)
        self.assertEqual(ParcelEvent.objects.count(), 179)

    def test_connected_registration_scan_shipment_manifest_invoice_and_stale_writes(self):
        self.lab()
        owner, port, warehouse = (
            self.users["owner"],
            self.users["sxm-port"],
            self.users["sxm-warehouse"],
        )
        customer = Client.objects.filter(business=self.business).first()
        origin, destination = self.sites["SXM-PORT"], self.sites["SXM-DC"]
        with work_at(self.business, owner, origin):
            parcels = [
                register_parcel(
                    business=self.business,
                    actor=owner,
                    client=customer,
                    origin="Sint Maarten",
                    destination="SXM distribution",
                    origin_location=origin,
                    destination_location=destination,
                    sender_name="Fictional Sender",
                    recipient_name="Fictional Recipient",
                    package_description="Acceptance carton",
                    weight_kg="2.5",
                    quantity=1,
                )
                for _ in range(2)
            ]
            shipment = create_shipment(
                business=self.business,
                actor=owner,
                origin="Port",
                destination="Warehouse",
                origin_location=origin,
                destination_location=destination,
                transport_mode="ROAD",
                driver_name="Fictional Driver",
                vehicle_reference="LAB-06C",
            )
            for parcel in parcels:
                assign_parcel(business=self.business, actor=owner, shipment=shipment, parcel=parcel)
        client = self.http("sxm-port")
        for parcel in parcels:
            data = {
                "status": "RECEIVED",
                "expected_status": "REGISTERED",
                "idempotency_key": str(uuid4()),
            }
            self.assertEqual(
                self.post(
                    client, "logistics_parcel_scan", {"tracking_code": parcel.tracking_code}
                ).status_code,
                200,
            )
            for _ in range(2):
                self.assertEqual(
                    self.post(
                        client, "logistics_parcel_scan_action", data, [parcel.pk]
                    ).status_code,
                    302,
                )
            self.assertEqual(parcel.events.filter(status="RECEIVED").count(), 1)
            event = parcel.events.get(status="RECEIVED")
            self.assertEqual((event.actor_id, event.operational_location_id), (port.pk, origin.pk))
            self.assertEqual(
                self.post(
                    client,
                    "logistics_parcel_scan_action",
                    {**data, "idempotency_key": str(uuid4()), "status": "IN_TRANSIT"},
                    [parcel.pk],
                ).status_code,
                400,
            )
            old_updated = parcel.updated_at
            with self.assertRaises(ValidationError):
                edit_parcel(
                    business=self.business,
                    actor=owner,
                    parcel=parcel,
                    expected_updated_at=old_updated,
                    package_description="Stale edit",
                )
            with self.assertRaises(PermissionDenied):
                edit_parcel(
                    business=self.business,
                    actor=port,
                    parcel=parcel,
                    destination_location=self.sites["DM-HUB"],
                )
        shipment.refresh_from_db()
        change_shipment_status(
            business=self.business,
            actor=port,
            shipment=shipment,
            status="READY",
            expected_revision=shipment.revision,
        )
        shipment.refresh_from_db()
        stale_revision = shipment.revision
        change_shipment_status(
            business=self.business,
            actor=port,
            shipment=shipment,
            status="IN_TRANSIT",
            expected_revision=stale_revision,
        )
        with self.assertRaises(ValidationError):
            change_shipment_status(
                business=self.business,
                actor=port,
                shipment=shipment,
                status="ARRIVED",
                expected_revision=stale_revision,
            )
        change_shipment_status(
            business=self.business, actor=warehouse, shipment=shipment, status="ARRIVED"
        )
        from .parcel_services import change_parcel_status

        for parcel in parcels:
            parcel.refresh_from_db()
            self.assertEqual(parcel.current_status, "ARRIVED")
            for status in ("READY", "DELIVERED"):
                change_parcel_status(
                    business=self.business, actor=warehouse, parcel=parcel, status=status
                )
        change_shipment_status(
            business=self.business, actor=warehouse, shipment=shipment, status="COMPLETED"
        )
        manifest = generate_manifest(business=self.business, actor=owner, shipment=shipment)
        self.assertEqual(len(manifest["parcels"]), 2)
        charge = add_charge(
            business=self.business,
            actor=owner,
            shipment=shipment,
            description="Acceptance freight",
            quantity="2",
            unit_price="25.00",
            idempotency_key=uuid4(),
        )
        invoice = invoice_charges(business=self.business, actor=owner, charge_ids=[charge.pk])
        self.assertEqual(str(invoice.total), "50.00")
        self.assertEqual(invoice.lines.count(), 1)
        self.assertEqual(invoice.status, "DRAFT")
        for parcel in parcels:
            self.assertEqual(
                self.http("sxm-warehouse")
                .get(reverse("logistics_shipping_label_pdf", args=[parcel.pk]))
                .status_code,
                200,
            )

    def test_cross_tenant_requests_public_privacy_and_subscription_failure(self):
        self.lab()
        self.plan.is_active = True
        self.plan.save(update_fields=["is_active"])
        other = Business.objects.create(
            name="Other fictional tenant", slug="acceptance-other", vertical="LOGISTICS"
        )
        BusinessUser.objects.create(business=other, user=self.users["owner"], role="owner")
        BusinessSubscription.objects.create(
            business=other, plan=self.plan, status="active", billing_interval="yearly"
        )
        customer = Client.objects.create(business=other, first_name="Private other client")
        foreign = register_parcel(
            business=other,
            actor=self.users["owner"],
            client=customer,
            package_description="Private other cargo",
            origin="Miami",
            destination="SXM",
            quantity=1,
            weight_kg="1",
        )
        foreign_site = LogisticsLocation.objects.create(
            business=other,
            name="Other Hub",
            code="OTHER-HUB",
            location_type="HUB",
            country_code="US",
        )
        client = self.http("owner")
        self.assertEqual(
            client.get(reverse("logistics_parcel_detail", args=[foreign.pk])).status_code, 404
        )
        self.assertEqual(
            client.get(reverse("logistics_shipping_label_pdf", args=[foreign.pk])).status_code, 404
        )
        self.assertEqual(
            self.post(
                client, "logistics_parcel_scan", {"tracking_code": foreign.tracking_code}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.post(client, "logistics_work_location", {"location": foreign_site.pk}).status_code,
            403,
        )
        with self.assertRaises(PermissionDenied):
            parcels_for_business(business=other, actor=self.users["miami"])
        # Isolated test DB only: a provider-backed active subscription requires
        # a valid billing period. Public tracking deliberately ignores Local bypass.
        subscription = self.business.subscription
        subscription.status = "active"
        subscription.current_period_end = timezone.now() + timedelta(days=365)
        subscription.save()
        parcel = Parcel.objects.filter(business=self.business).first()
        public = lookup_public_tracking(parcel.tracking_code)
        self.assertEqual(
            set(public), {"tracking_code", "status", "status_label", "business", "events"}
        )
        output = json.dumps(public)
        for private in (
            parcel.sender_name,
            parcel.recipient_name,
            parcel.client.email,
            "operational_location",
            "internal_note",
            "actor_id",
        ):
            self.assertNotIn(private, output)
        subscription.status = "pending_checkout"
        subscription.save()
        with override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False):
            response = client.get(reverse("logistics_parcel_list"))
            self.assertIn(response.status_code, (302, 403))
