"""Services dashboard presentation contracts; disposable PostgreSQL only."""

import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db import connection
from django.test import Client as WebClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice, InvoiceLine
from apps.billings.payment_services import record_invoice_payment
from apps.businesses.models import (
    Business,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    UserOnboardingState,
)
from apps.businesses.test_service_allowances import ServicesFixture
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Lead

NOW = datetime(2026, 11, 14, 9, tzinfo=UTC)
PEOPLE = [
    ("Jamie", "Rivera", "Harbour View Apartments"),
    ("Taylor", "Bennett", "Island Property Services"),
    ("Casey", "Laurent", "Household"),
    ("Jordan", "Ellis", "Seaview Guesthouse"),
    ("Riley", "James", "Market Street Studio"),
]


def assert_disposable():
    """Fail before fixture writes if the explicit cluster identity is missing."""
    root = Path(os.environ.get("SERVICES_DASHBOARD_UI_ROOT", "/missing"))
    db = connection.settings_dict
    if (
        (settings.SETTINGS_MODULE or os.environ.get("DJANGO_SETTINGS_MODULE"))
        != "taskio.services_test_settings"
        or db["HOST"] != "127.0.0.1"
        or str(db["PORT"]) == "5432"
        or not db["NAME"].startswith("test_")
        or not (root / "DISPOSABLE").is_file()
    ):
        raise RuntimeError(
            "Dashboard checks require the verified disposable Services cluster: "
            + json.dumps(
                {
                    "module": settings.SETTINGS_MODULE,
                    "host": db["HOST"],
                    "port": str(db["PORT"]),
                    "database": db["NAME"],
                    "marker": (root / "DISPOSABLE").is_file(),
                }
            )
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_setting('data_directory'), "
            "(SELECT system_identifier::text FROM pg_control_system())"
        )
        directory, identifier = cursor.fetchone()
    if (
        Path(directory).resolve() != (root / "pgdata").resolve()
        or identifier != (root / "DISPOSABLE").read_text().strip()
    ):
        raise RuntimeError("Disposable PostgreSQL identity does not match the approved marker.")


class DashboardFixture(ServicesFixture):
    """Synthetic records shared by the before/after browser and server checks."""

    def setUp(self):
        assert_disposable()
        clock = mock.patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        super().setUp()
        self.business.name = "Harbour Services · UI Review"
        self.business.timezone = "America/Lower_Princes"
        self.business.country = "Sint Maarten"
        self.business.default_locale = "en-SX"
        self.business.invoice_prefix = "INV"
        self.business.save()
        self.owner.first_name, self.owner.last_name = "Alex", "Morgan"
        self.owner.email = "alex@motionmate.example.test"
        self.owner.save()
        self.roles = {"owner": self.owner}
        for role in ("admin", "staff", "accountant", "viewer"):
            user = TaskIOUser.objects.create_user(
                email=f"{role}@motionmate.example.test", first_name="Alex", last_name="Morgan"
            )
            BusinessUser.objects.create(business=self.business, user=user, role=role)
            self.roles[role] = user
        self.onboarding = UserOnboardingState.objects.create(
            business=self.business,
            user=self.owner,
            selected_journey="setup_business",
            completed_welcome=True,
        )
        self.customers = [self.customer] + [self.new_client() for _ in range(4)]
        self.appointments, self.requests, self.invoices = [], [], []
        self.service.name = "Property maintenance consultation"
        self.service.save()
        for i, customer in enumerate(self.customers):
            start = NOW.replace(hour=11 + 3 * i)
            self.appointments.append(
                Appointment.objects.create(
                    business=self.business,
                    client=customer,
                    service=self.service,
                    service_name=self.service.name,
                    title="Initial site visit",
                    start_time=start,
                    end_time=start + timedelta(hours=1),
                )
            )
            self.requests.append(
                Lead.objects.create(
                    business=self.business,
                    lead_type="REQUEST",
                    requested_service=self.service,
                    first_name=PEOPLE[i][0],
                    last_name=PEOPLE[i][1],
                    company_name=PEOPLE[i][2],
                    email=f"request-{i}@example.test",
                    phone="+17215550101",
                    status="NEW" if i < 3 else "CONTACTED",
                    request_source="public_booking" if i < 2 else "staff",
                    preferred_start_time=start + timedelta(days=1),
                )
            )
            if i < 3:
                amount = Decimal(125 * (i + 1))
                invoice = Invoice.objects.create(
                    business=self.business,
                    client=customer,
                    invoice_number=f"AUD-{1001 + i}",
                    status="SENT",
                    subtotal=amount,
                    total=amount,
                )
                InvoiceLine.objects.create(
                    invoice=invoice, description="Consultation", unit_price=amount
                )
                self.invoices.append(invoice)
        self.empty_business = Business.objects.create(
            name="Harbour Services · Empty", slug="step7-empty"
        )
        BusinessSubscription.objects.create(
            business=self.empty_business, plan=self.plan, status="active", payment_provider="local"
        )
        BusinessUser.objects.create(business=self.empty_business, user=self.owner, role="owner")
        UserOnboardingState.objects.create(
            business=self.empty_business, user=self.owner, completed_welcome=True
        )
        self.logistics = Business.objects.create(
            name="Harbour Logistics · UI Review", slug="step7-logistics", vertical="LOGISTICS"
        )
        BusinessSubscription.objects.create(
            business=self.logistics,
            plan=ClarivoPlan.objects.get(slug="logistics"),
            status="pending_checkout",
            payment_provider="stripe",
            billing_interval="yearly",
            billing_currency="eur",
        )
        for role in ("owner", "staff"):
            BusinessUser.objects.create(business=self.logistics, user=self.roles[role], role=role)
        UserOnboardingState.objects.create(
            business=self.logistics, user=self.owner, completed_welcome=True
        )
        self.scenario("populated")

    def scenario(self, name):
        """Change only this fixture's records, within the verified test database."""
        self.business.name = "Harbour Services · UI Review"
        self.business.currency = "USD"
        self.business.country, self.business.default_locale = "Sint Maarten", "en-SX"
        self.business.save()
        self.plan.allow_appointments = self.plan.allow_invoicing = (
            self.plan.allow_public_booking
        ) = True
        self.plan.save()
        self.subscription.plan = self.plan
        self.subscription.status, self.subscription.payment_provider = "active", "local"
        self.subscription.past_due_since = self.subscription.grace_period_ends_at = None
        self.subscription.provider_customer_id = self.subscription.provider_subscription_id = ""
        self.subscription.save()
        for i, customer in enumerate(self.customers):
            customer.first_name, customer.last_name, customer.company_name = PEOPLE[i]
            customer.email = f"client-{i}@example.test"
            customer.save()
        self.onboarding.selected_journey, self.onboarding.completed_welcome = "setup_business", True
        self.onboarding.dismissed_at = None
        self.onboarding.save()
        if name == "locked":
            self.plan.allow_appointments = self.plan.allow_invoicing = (
                self.plan.allow_public_booking
            ) = False
            self.plan.save()
        if name in {"restricted", "grace"}:
            self.subscription.plan = ClarivoPlan.objects.get(slug="pro")
            self.subscription.status, self.subscription.payment_provider = "past_due", "stripe"
            self.subscription.provider_customer_id = "cus_step7_synthetic"
            self.subscription.provider_subscription_id = "sub_step7_synthetic"
            self.subscription.provider_price_id = "price_step7_synthetic"
            self.subscription.billing_interval, self.subscription.billing_currency = (
                "monthly",
                "usd",
            )
            self.subscription.current_period_start = NOW - timedelta(days=15)
            self.subscription.current_period_end = NOW + timedelta(days=15)
            self.subscription.past_due_since = NOW - timedelta(days=10)
            self.subscription.grace_period_ends_at = NOW + timedelta(
                days=1 if name == "grace" else -1
            )
            self.subscription.save()
        if name == "long":
            self.business.name = (
                "Harbour Association for Community Services and Property Administration"
            )
            self.business.save()
            for customer in self.customers:
                customer.company_name += (
                    " · Community services and waterfront property administration"
                )
                customer.save()
        if name == "welcome":
            self.onboarding.selected_journey, self.onboarding.completed_welcome = "", False
            self.onboarding.save()
        self.business._state.fields_cache.clear()

    def login_role(self, role="owner", business=None):
        self.client.force_login(self.roles[role])
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = (business or self.business).pk
        session.save()
        return self.client.cookies[settings.SESSION_COOKIE_NAME].value


class ServicesDashboardUITests(DashboardFixture, TestCase):
    def test_grace_and_restricted_fixture_setup(self):
        self.login_role()
        for name in ("grace", "restricted"):
            self.scenario(name)
            response = self.client.get(reverse("agent_dashboard"))
            self.assertEqual(response.status_code, 200, getattr(response, "url", ""))
            self.assertEqual(response.context["workspace_can_modify"], name == "grace")

    def test_context_and_read_projections_preserve_business_records(self):
        self.login_role()
        before = {
            "appointments": list(Appointment.objects.filter(business=self.business).values()),
            "requests": list(Lead.objects.filter(business=self.business).values()),
            "invoices": list(Invoice.objects.filter(business=self.business).values()),
        }
        response = self.client.get(reverse("agent_dashboard"))
        self.assertTrue(response.context["services_dashboard_ui"])
        self.assertEqual(str(response.context["dashboard_timezone"]), self.business.timezone)
        self.assertEqual(response.context["today_appointment_count"], 5)
        self.assertEqual(list(response.context["upcoming_appointments"]), self.appointments)
        self.assertEqual(list(response.context["service_request_followups"]), self.requests)
        self.assertEqual(list(response.context["recent_invoices"]), list(reversed(self.invoices)))
        self.assertEqual(response.context["unpaid_invoice_total"], Decimal("750"))
        self.assertEqual(
            before,
            {
                "appointments": list(Appointment.objects.filter(business=self.business).values()),
                "requests": list(Lead.objects.filter(business=self.business).values()),
                "invoices": list(Invoice.objects.filter(business=self.business).values()),
            },
        )

    def test_services_dashboard_assets_are_absent_on_other_screens_and_logistics(self):
        self.login_role()
        for route in [
            "appointment_list",
            "staff_client_list",
            "invoice_list",
            "business_settings",
            "business_service_list",
        ]:
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "services-dashboard.css")
            self.assertNotContains(response, "services-dashboard.js")
            self.assertNotContains(response, "mm-services-dashboard-page")
        self.login_role(business=self.logistics)
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "services-dashboard.css")
        self.assertContains(response, 'class="logistics-workspace"')

    def test_all_service_roles_keep_existing_reads_and_setup_permissions(self):
        for role in self.roles:
            with self.subTest(role=role):
                self.login_role(role)
                response = self.client.get(reverse("agent_dashboard"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "AUD-1003")
                self.assertContains(
                    response, reverse("appointment_detail", args=[self.appointments[0].pk])
                )
                self.assertEqual(
                    response.context["onboarding_status"]["visible"], role in {"owner", "admin"}
                )

    def test_local_time_is_bounded_to_dashboard_and_includes_dst_offsets(self):
        self.login_role()
        response = self.client.get(reverse("agent_dashboard"))
        self.assertContains(response, "7:00 AM")
        self.assertContains(response, "UTC-04:00", html=False)
        self.assertEqual(timezone.get_current_timezone_name(), "UTC")
        self.business.timezone = "Europe/Amsterdam"
        self.business.save()
        for instant, offset in [
            (datetime(2026, 10, 25, 0, 30, tzinfo=UTC), "+02:00"),
            (datetime(2026, 10, 25, 1, 30, tzinfo=UTC), "+01:00"),
        ]:
            Appointment.objects.filter(pk=self.appointments[0].pk).update(
                start_time=instant, end_time=instant + timedelta(hours=1)
            )
            with mock.patch("django.utils.timezone.now", return_value=instant - timedelta(hours=1)):
                response = self.client.get(reverse("agent_dashboard"))
                self.assertContains(response, "2:30 AM")
                row = re.search(
                    r'data-record-id="' + str(self.appointments[0].pk) + r'".*?</a>',
                    response.content.decode(),
                    re.S,
                ).group()
                self.assertIn(offset, row)
        self.assertEqual(timezone.get_current_timezone_name(), "UTC")

    def test_real_onboarding_fields_and_post_are_retained(self):
        self.scenario("welcome")
        self.login_role()
        response = self.client.get(reverse("agent_dashboard"))
        self.assertContains(response, 'name="open_guide_after_select" value="1"')
        response = self.client.post(
            reverse("agent_dashboard"),
            {
                "onboarding_action": "select_journey",
                "selected_journey": "setup_business",
                "open_guide_after_select": "1",
            },
        )
        self.assertRedirects(response, reverse("agent_dashboard") + "?setup_guide=1")
        self.onboarding.refresh_from_db()
        self.assertEqual(self.onboarding.selected_journey, "setup_business")

    def test_lock_and_restricted_states_keep_existing_authoritative_context(self):
        self.login_role()
        self.scenario("locked")
        response = self.client.get(reverse("agent_dashboard"))
        self.assertFalse(response.context["dashboard_appointments_enabled"])
        self.assertFalse(response.context["dashboard_invoices_enabled"])
        self.assertEqual(len(response.context["service_request_followups"]), 5)
        self.assertNotContains(response, "AUD-1003")
        self.scenario("restricted")
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["workspace_can_modify"])
        self.assertFalse(response.context["public_booking_share_ready"])
        original = self.onboarding.last_step_key
        self.client.post(
            reverse("agent_dashboard"),
            {"onboarding_action": "guide_step", "target_step_key": "add_first_service"},
        )
        self.onboarding.refresh_from_db()
        self.assertEqual(self.onboarding.last_step_key, original)

    def test_saved_usd_receipts_and_eur_workspace_totals_stay_separate(self):
        self.login_role()
        record_invoice_payment(
            business=self.business,
            actor=self.owner,
            invoice=self.invoices[0],
            amount=Decimal("40"),
            currency="USD",
            method="CASH",
            reference="STEP7-SYNTHETIC",
            idempotency_key=uuid.uuid4(),
        )
        self.business.currency, self.business.country, self.business.default_locale = (
            "EUR",
            "Netherlands",
            "nl-NL",
        )
        self.business.save()
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.context["open_invoice_count"], 3)
        self.assertEqual(response.context["unpaid_invoice_total"], Decimal("625"))
        self.assertContains(response, "€625,00")
        self.assertContains(response, "$85,00")
        self.assertContains(response, "USD")
        self.assertContains(response, "all currencies")
        self.assertContains(response, "Partially paid")
        self.assertRegex(
            response.content.decode(),
            r'<!--\s*<section class="card mb-4" aria-label="Invoice balances by currency"',
        )
        self.assertEqual(self.invoices[0].total, Decimal("125"))

    def test_csrf_is_required_for_real_setup_post(self):
        web = WebClient(enforce_csrf_checks=True)
        web.force_login(self.owner)
        session = web.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        payload = {
            "onboarding_action": "continue_later",
            "current_step_key": "complete_business_profile",
        }
        self.assertEqual(web.post(reverse("agent_dashboard"), payload).status_code, 403)
        web.get(reverse("agent_dashboard"))
        response = web.post(
            reverse("agent_dashboard"),
            payload,
            HTTP_X_CSRFTOKEN=web.cookies[settings.CSRF_COOKIE_NAME].value,
        )
        self.assertEqual(response.status_code, 302)
        self.onboarding.refresh_from_db()
        self.assertEqual(self.onboarding.last_step_key, "complete_business_profile")

    def test_foreign_tenant_records_and_request_history_do_not_leak(self):
        other = Business.objects.create(name="Other", slug="step7-other")
        BusinessSubscription.objects.create(
            business=other, plan=self.plan, status="active", payment_provider="local"
        )
        Lead.objects.create(
            business=other,
            lead_type="REQUEST",
            status="NEW",
            first_name="Foreign",
            last_name="Requester",
            email="foreign@example.test",
        )
        Lead.objects.create(
            business=self.business,
            lead_type="INTEREST",
            status="NEW",
            first_name="Historical Interest",
            email="interest@example.test",
        )
        self.login_role()
        response = self.client.get(reverse("agent_dashboard"))
        self.assertNotContains(response, "Foreign Requester")
        self.assertNotContains(response, "Historical Interest")
        self.assertEqual(response.context["open_service_request_count"], 5)
        self.assertEqual(len(response.context["service_request_followups"]), 5)

    def test_today_count_and_capped_future_preview_remain_distinct(self):
        self.login_role()
        Appointment.objects.filter(pk=self.appointments[0].pk).update(
            start_time=NOW - timedelta(hours=1), end_time=NOW
        )
        for i in range(2):
            self.appointment(start=NOW + timedelta(days=1, hours=i))
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.context["today_appointment_count"], 5)
        self.assertEqual(response.context["upcoming_appointment_count"], 6)
        self.assertEqual(len(response.context["upcoming_appointments"]), 5)
        self.assertNotIn(self.appointments[0], response.context["upcoming_appointments"])
        self.assertContains(response, "5 scheduled today. Next scheduled")

    def test_unknown_zone_reuses_existing_fallback_without_global_activation(self):
        self.business.timezone = "Invalid/Zone"
        self.business.save()
        self.login_role()
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.context["dashboard_timezone"]), "UTC")
        self.assertEqual(timezone.get_current_timezone_name(), "UTC")

    def test_manifest_postprocessing_resolves_local_font_without_production_collection(self):
        from whitenoise.storage import CompressedManifestStaticFilesStorage

        source = Path(__file__).resolve().parents[2] / "static"
        names = [
            "assets/css/services-dashboard.css",
            "assets/js/services-dashboard.js",
            "assets/fonts/manrope/manrope-latin-wght-normal.woff2",
            "assets/fonts/manrope/OFL.txt",
        ]
        with tempfile.TemporaryDirectory(
            prefix="static-compat-", dir=os.environ["SERVICES_DASHBOARD_UI_ROOT"]
        ) as folder:
            for name in names:
                target = Path(folder) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, target)
            storage = CompressedManifestStaticFilesStorage(location=folder, base_url="/static/")
            outcomes = list(storage.post_process({name: (storage, name) for name in names}))
            self.assertFalse(
                [item for item in outcomes if isinstance(item[2], Exception)], outcomes
            )
            font = storage.hashed_files[names[2]]
            css = (Path(folder) / storage.hashed_files[names[0]]).read_text()
            self.assertIn(Path(font).name, css)
            self.assertTrue((Path(folder) / font).is_file())
