"""Registration periods, read permissions and complete operational PDF exports."""

from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from apps.businesses.models import ClarivoPlan

from . import test_location_access as fixtures
from .manifest_forms import ManifestPeriodForm
from .manifest_pdf import render_parcel_manifest_pdf
from .models import Parcel, ParcelEvent, Shipment
from .parcel_services import register_parcel


class ManifestPeriodTests(SimpleTestCase):
    business = SimpleNamespace(timezone="America/New_York")
    now = datetime(2026, 11, 2, 2, tzinfo=UTC)  # Still Nov 1 at the business.

    def form(self, data):
        return ManifestPeriodForm(data, business=self.business, now=self.now)

    def test_presets_use_inclusive_business_calendar_days(self):
        for period, start, end in (
            ("today", date(2026, 11, 1), date(2026, 11, 1)),
            ("yesterday", date(2026, 10, 31), date(2026, 10, 31)),
            ("7_days", date(2026, 10, 26), date(2026, 11, 1)),
            ("30_days", date(2026, 10, 3), date(2026, 11, 1)),
        ):
            with self.subTest(period=period):
                form = self.form({"period": period})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["start_date"], start)
                self.assertEqual(form.cleaned_data["end_date"], end)

    def test_dst_days_have_calendar_midnight_boundaries(self):
        for day, start, end, hours in (
            (
                "2026-03-08",
                datetime(2026, 3, 8, 5, tzinfo=UTC),
                datetime(2026, 3, 9, 4, tzinfo=UTC),
                23,
            ),
            (
                "2026-11-01",
                datetime(2026, 11, 1, 4, tzinfo=UTC),
                datetime(2026, 11, 2, 5, tzinfo=UTC),
                25,
            ),
        ):
            with self.subTest(day=day):
                form = self.form({"period": "custom", "start_date": day, "end_date": day})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["start_at"], start)
                self.assertEqual(form.cleaned_data["end_at"], end)
                self.assertEqual((end - start).total_seconds(), hours * 3600)

    def test_custom_range_rejects_missing_invalid_reversed_and_overflow_dates(self):
        for data in (
            {"period": "custom"},
            {"period": "custom", "start_date": "2026-02-30", "end_date": "2026-03-01"},
            {"period": "custom", "start_date": "2026-11-02", "end_date": "2026-11-01"},
            {"period": "custom", "start_date": "9999-12-31", "end_date": "9999-12-31"},
            {"period": "unknown"},
        ):
            with self.subTest(data=data):
                self.assertFalse(self.form(data).is_valid())


class ParcelManifestPDFTests(TestCase):
    setUp_base = fixtures.LocationAccessTests.setUp_base
    switch = fixtures.LocationAccessTests.switch
    parcel = fixtures.LocationAccessTests.parcel
    shipment = fixtures.LocationAccessTests.shipment
    grant = fixtures.LocationAccessTests.grant
    login_worker = fixtures.LocationAccessTests.login_worker
    setUp = fixtures.LocationAccessTests.setUp

    def pdf(self, **params):
        response = self.client.get(
            reverse("logistics_parcel_manifest"), {"download": "pdf", **params}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        return response, PdfReader(BytesIO(response.content))

    def text(self, document):
        return "\n".join(page.extract_text() for page in document.pages)

    def test_dashboard_link_and_today_default(self):
        dashboard = self.client.get(reverse("agent_dashboard"))
        self.assertContains(dashboard, f'href="{reverse("logistics_parcel_manifest")}"')
        response = self.client.get(reverse("logistics_parcel_manifest"))
        self.assertContains(response, "registration date")
        self.assertContains(response, '<option value="today" selected>Today</option>')
        self.assertContains(response, "Custom range")
        self.assertContains(response, "Both start and end dates are included.")
        _, document = self.pdf()
        text = self.text(document)
        self.assertIn("Total parcels: 3", text)
        self.assertIn(self.pa.tracking_code, "".join(text.split()))

    def test_registration_boundaries_are_inclusive_in_business_timezone(self):
        self.business.timezone = "America/New_York"
        self.business.save(update_fields=["timezone"])
        start = datetime(2026, 11, 1, 4, tzinfo=UTC)
        end = datetime(2026, 11, 2, 5, tzinfo=UTC)
        included, excluded = [], []
        for timestamp, expected in (
            (start - timedelta(microseconds=1), excluded),
            (start, included),
            (end - timedelta(microseconds=1), included),
            (end, excluded),
        ):
            with patch("django.utils.timezone.now", return_value=timestamp):
                expected.append(self.parcel(self.a).tracking_code)
        with patch(
            "apps.logistics.manifest_views.timezone.now", return_value=end - timedelta(hours=1)
        ):
            response, document = self.pdf(
                period="custom", start_date="2026-11-01", end_date="2026-11-01"
            )
        text = self.text(document)
        self.assertIn("Total parcels: 2", text)
        self.assertIn("01 Nov 2026 to 01 Nov 2026 (inclusive)", text)
        self.assertIn("America/New_York", text)
        self.assertIn("EST", text)
        for code in included:
            self.assertIn(code, "".join(text.split()))
        for code in excluded:
            self.assertNotIn(code, "".join(text.split()))
        self.assertIn(
            "courier-manifest-2026-11-01-to-2026-11-01.pdf", response["Content-Disposition"]
        )

    def test_invalid_ranges_render_errors_without_generating_pdf(self):
        with patch("apps.logistics.manifest_views.render_parcel_manifest_pdf") as renderer:
            response = self.client.get(
                reverse("logistics_parcel_manifest"),
                {
                    "download": "pdf",
                    "period": "custom",
                    "start_date": "2026-11-02",
                    "end_date": "2026-11-01",
                },
            )
        self.assertContains(response, "End date must be on or after start date.", status_code=400)
        renderer.assert_not_called()

    def test_empty_period_produces_a_clear_pdf(self):
        _, document = self.pdf(period="custom", start_date="2000-01-01", end_date="2000-01-02")
        text = self.text(document)
        self.assertIn("Total parcels: 0", text)
        self.assertIn("No parcels were registered in this period", text)
        self.assertIn("Page 1", text)

    def test_business_and_location_scopes_and_existing_read_roles(self):
        foreign = register_parcel(
            business=self.other, actor=self.other_user, client=self.other_customer, **self.fields
        )
        self.login_worker()
        for role in ("staff", "viewer", "accountant", "admin", "owner"):
            with self.subTest(role=role):
                self.member.role = role
                self.member.save(update_fields=["role"])
                _, document = self.pdf()
                text = "".join(self.text(document).split())
                self.assertIn(self.pa.tracking_code, text)
                self.assertNotIn(foreign.tracking_code, text)
                if role in ("owner", "admin"):
                    self.assertIn(self.pc.tracking_code, text)
                else:
                    self.assertNotIn(self.pc.tracking_code, text)
                    self.assertNotIn(self.legacy.tracking_code, text)

    def test_read_only_location_assignment_can_download_without_writes(self):
        self.grant(self.a, operate=False)
        self.login_worker()
        _, document = self.pdf()
        self.assertIn(self.pa.tracking_code, "".join(self.text(document).split()))
        self.assertNotIn(self.pc.tracking_code, "".join(self.text(document).split()))

    def test_no_location_grant_has_no_parcel_data(self):
        from .models import LogisticsLocationAssignment

        LogisticsLocationAssignment.objects.filter(membership=self.member).delete()
        self.login_worker()
        _, document = self.pdf()
        self.assertIn("Total parcels: 0", self.text(document))
        self.assertNotIn(self.pa.tracking_code, "".join(self.text(document).split()))

    def test_inactive_membership_and_django_staff_do_not_bypass_access(self):
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        form = ManifestPeriodForm({"period": "today"}, business=self.business)
        self.assertTrue(form.is_valid())
        with self.assertRaises(PermissionDenied):
            render_parcel_manifest_pdf(
                business=self.business,
                actor=self.staff,
                period=form.cleaned_data,
                generated_at=timezone.now(),
            )
        self.login_worker()
        response = self.client.get(reverse("logistics_parcel_manifest"), {"download": "pdf"})
        self.assertNotEqual(response.get("Content-Type"), "application/pdf")

    def test_anonymous_and_post_requests_cannot_download(self):
        self.assertEqual(self.client.post(reverse("logistics_parcel_manifest")).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("logistics_parcel_manifest")).status_code, 302)

    def test_manifest_entitlement_is_enforced_on_dashboard_and_direct_download(self):
        allows_module = ClarivoPlan.allows_module
        with patch.object(
            ClarivoPlan,
            "allows_module",
            autospec=True,
            side_effect=lambda plan, module: module != "manifests" and allows_module(plan, module),
        ):
            response = self.client.get(reverse("agent_dashboard"))
            download = self.client.get(reverse("logistics_parcel_manifest"), {"download": "pdf"})
        self.assertNotContains(response, f'href="{reverse("logistics_parcel_manifest")}"')
        self.assertNotEqual(download.get("Content-Type"), "application/pdf")

    def test_pdf_contains_operational_fields_but_no_finances_or_mutations(self):
        register_parcel(
            business=self.business,
            actor=self.user,
            client=self.customer,
            **{
                **self.fields,
                "sender_name": "Renée & Sons <Export>",
                "recipient_name": "Isabel Recipient",
                "package_description": "Fragile books",
                "weight_kg": "12.345",
                "internal_notes": "PRIVATE-NOTES-NEVER-EXPORT",
                "declared_value": "987654.32",
            },
        )
        before = (
            list(Parcel.objects.values()),
            list(ParcelEvent.objects.values()),
            list(Shipment.objects.values()),
        )
        with CaptureQueriesContext(connection) as queries:
            _, document = self.pdf()
        text = self.text(document)
        for value in (
            "Renée & Sons <Export>",
            "Isabel Recipient",
            "Fragile books",
            "12.345",
            "Registered",
            "Curacao",
            "Courier",
        ):
            self.assertIn(value, text)
        for value in (
            "987654.32",
            "PRIVATE-NOTES-NEVER-EXPORT",
            "Outstanding",
            "Revenue",
            "Invoice",
            "Payment",
        ):
            self.assertNotIn(value, text)
        self.assertFalse(
            any(
                query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                and '"django_session"' not in query["sql"]
                for query in queries
            )
        )
        self.assertEqual(
            before,
            (
                list(Parcel.objects.values()),
                list(ParcelEvent.objects.values()),
                list(Shipment.objects.values()),
            ),
        )

    def test_large_manifest_has_all_parcels_repeated_headers_and_page_numbers(self):
        # Explicit fixture inserts bypass the public domain write guard only in tests.
        items = [
            Parcel(
                business=self.business,
                client=self.customer,
                origin="Miami",
                destination="Curacao",
                package_description=(
                    "Boxes " + "unbroken" * 100 if index == 0 else "Books and clothing"
                ),
                sender_name="Sender " + str(index),
                recipient_name="Recipient " + str(index),
            )
            for index in range(1000)
        ]
        from django.db.models import QuerySet

        QuerySet.bulk_create(Parcel.objects.all(), items)
        _, document = self.pdf()
        text = self.text(document)
        self.assertIn("Total parcels: 1003", text)
        self.assertGreater(len(document.pages), 3)
        for item in items:
            # A tracking number may wrap within its table cell.
            self.assertIn(item.tracking_code, "".join(text.split()))
        for number, page in enumerate(document.pages, 1):
            self.assertIn("Tracking number", page.extract_text())
            self.assertIn(f"Page {number}", page.extract_text())

    def test_services_dashboard_and_access_remain_unchanged(self):
        self.switch(self.service)
        response = self.client.get(reverse("agent_dashboard"))
        self.assertNotContains(response, f'href="{reverse("logistics_parcel_manifest")}"')
        self.assertFalse(response.context.get("logistics_dashboard", False))
        self.assertContains(response, "Unpaid Invoice Value")
        response = self.client.get(reverse("logistics_parcel_manifest"), {"download": "pdf"})
        self.assertNotEqual(response.get("Content-Type"), "application/pdf")
