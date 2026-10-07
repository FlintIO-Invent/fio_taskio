"""Parcel metadata workflows preserve tenant, lifecycle and public-tracking boundaries."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client as BrowserClient
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.businesses.models import BusinessSubscription, BusinessUser
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client

from . import test_parcels as fixtures
from .forms import ParcelEditForm
from .models import Parcel, ParcelEvent
from .parcel_services import PARCEL_INPUT_FIELDS, edit_parcel, record_parcel_event, register_parcel
from .public_tracking import lookup_public_tracking
from .shipment_services import assign_parcel, create_shipment
from .test_public_tracking import TRACKING_CACHE


class ParcelMetadataTests(TestCase):
    setUp = fixtures.ParcelTests.setUp
    switch = fixtures.ParcelTests.switch
    register = fixtures.ParcelTests.register
    change = fixtures.ParcelTests.change

    def metadata(self):
        return {
            "hs_code": "4901",
            "marks_numbers": "BOX-01",
            "length_cm": "20.00",
            "width_cm": "10.00",
            "height_cm": "5.00",
            "volume_m3": "0.001",
            "sender_name": "Sender Example",
            "sender_contact": "sender@example.com",
            "sender_address": "10 Sender Street",
            "sender_country_code": "US",
            "sender_tax_id": "PRIVATE-TAX-ID",
            "recipient_name": "Recipient Example",
            "recipient_contact": "+599 1234567",
            "recipient_address": "20 Recipient Street",
            "mode_of_transport": "Sea",
            "vessel_name": "Example Vessel",
            "voyage_no": "VOY-10",
            "imo_no": "1234567",
            "port_load_unlocode": "USMIA",
            "port_discharge_unlocode": "CWWIL",
            "master_bl_no": "MASTER-10",
            "house_bl_no": "HOUSE-20",
            "issue_date": "2026-10-01",
            "incoterms": "DAP",
            "fragile_goods": True,
            "biodegradable_goods": True,
            "expiry_date": "2026-12-01",
            "internal_notes": "PRIVATE-HANDLING-NOTE",
        }

    def edit(self, parcel, **fields):
        return edit_parcel(business=self.business, parcel=parcel, actor=self.user, **fields)

    def edit_data(self, parcel, **overrides):
        data = {name: getattr(parcel, name) for name in PARCEL_INPUT_FIELDS}
        return {
            **{name: "" if value is None else value for name, value in data.items()},
            "expected_updated_at": parcel.updated_at.isoformat(),
            **overrides,
        }

    def test_create_persists_optional_metadata_without_duplicating_clients(self):
        client_count = Client.objects.count()
        response = self.client.post(
            reverse("logistics_parcel_register"),
            {
                **self.fields,
                **self.metadata(),
                "client": self.customer.pk,
                "idempotency_key": uuid.uuid4(),
                "sender_country_code": "us",
            },
        )
        parcel = Parcel.objects.get()
        self.assertRedirects(response, reverse("logistics_parcel_detail", args=[parcel.pk]))
        for name, raw in self.metadata().items():
            with self.subTest(field=name):
                expected = Parcel._meta.get_field(name).to_python(raw)
                self.assertEqual(getattr(parcel, name), expected)
        self.assertEqual(parcel.client_id, self.customer.pk)
        self.assertEqual(Client.objects.count(), client_count)
        self.assertEqual(parcel.events.count(), 1)
        self.assertEqual(parcel.created_by_id, self.user.pk)

    def test_minimal_existing_registration_keeps_new_fields_optional(self):
        response = self.client.post(
            reverse("logistics_parcel_register"),
            {
                **self.fields,
                "client": self.customer.pk,
                "idempotency_key": uuid.uuid4(),
            },
        )
        self.assertEqual(response.status_code, 302)
        parcel = Parcel.objects.get()
        self.assertIsNone(parcel.length_cm)
        self.assertIsNone(parcel.issue_date)
        self.assertFalse(parcel.fragile_goods)
        self.assertEqual(parcel.sender_name, "")

    def test_new_measurements_and_country_codes_validated_in_service(self):
        for fields in (
            {"length_cm": "0"},
            {"width_cm": "-1"},
            {"height_cm": "-1"},
            {"volume_m3": "-0.001"},
            {"sender_country_code": "U1"},
            {"sender_country_code": "USA1"},
            {"sender_address": "x" * 1001},
            {"issue_date": "invalid"},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.register(**fields)
        self.assertEqual(Parcel.objects.count(), 0)

    def test_invalid_create_preserves_values_client_and_tab_field_errors(self):
        response = self.client.post(
            reverse("logistics_parcel_register"),
            {
                **self.fields,
                **self.metadata(),
                "client": self.customer.pk,
                "idempotency_key": uuid.uuid4(),
                "length_cm": "-1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("length_cm", response.context["form"].errors)
        self.assertContains(response, 'value="Sender Example"')
        self.assertContains(response, 'id="parcel-physical"')
        self.assertContains(response, "data-logistics-form-errors")
        self.assertEqual(str(response.context["form"]["client"].value()), str(self.customer.pk))
        self.assertEqual(Parcel.objects.count(), 0)

    def test_measurement_boundary_and_clearing_optional_metadata(self):
        parcel = self.register(
            length_cm="0.01",
            width_cm="0.01",
            height_cm="0.01",
            volume_m3="0.000",
            fragile_goods=True,
            sender_name="Clear this",
            dimensions="Legacy dimensions in inches",
        )
        self.assertEqual(parcel.length_cm, Decimal("0.01"))
        edited = self.edit(parcel, length_cm=None, sender_name="", fragile_goods=False)
        self.assertIsNone(edited.length_cm)
        self.assertEqual(edited.sender_name, "")
        self.assertFalse(edited.fragile_goods)
        self.assertEqual(edited.dimensions, "Legacy dimensions in inches")
        self.assertEqual(edited.volume_m3, Decimal("0.000"))

    def test_creation_and_edit_use_grouped_client_form_patterns_and_date_inputs(self):
        response = self.client.get(reverse("logistics_parcel_register"))
        for marker in (
            "vertical-tab",
            "row g-5",
            "data-logistics-parcel-form",
            "data-parcel-client-form",
        ):
            self.assertContains(response, marker)
        parcel = self.register(**self.metadata())
        response = self.client.get(reverse("logistics_parcel_edit", args=[parcel.pk]))
        self.assertContains(response, 'value="2026-10-01"')
        self.assertContains(response, 'value="2026-12-01"')
        self.assertContains(response, parcel.updated_at.isoformat())
        form = response.context["form"]
        for name in (
            "client",
            "business",
            "tracking_code",
            "current_status",
            "shipment",
            "created_by",
        ):
            self.assertNotIn(name, form.fields)

    def test_list_view_action_opens_detail_with_metadata_location_and_shipment(self):
        parcel = self.register(**self.metadata(), declared_value="0.00")
        now = timezone.now()
        shipment = create_shipment(
            business=self.business,
            actor=self.user,
            origin="Miami",
            destination="Curacao",
            departure_at=now,
            estimated_arrival_at=now + timedelta(days=2),
        )
        assign_parcel(business=self.business, shipment=shipment, parcel=parcel, actor=self.user)
        location = self.change(parcel, "RECEIVED", location="Main depot")
        self.edit(parcel, internal_notes="Revised private note")
        listing = self.client.get(reverse("logistics_parcel_list"))
        self.assertContains(listing, reverse("logistics_parcel_detail", args=[parcel.pk]))
        response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        for value in (
            "Sender Example",
            "Recipient Example",
            "Example Vessel",
            "MASTER-10",
            "Main depot",
            "Estimated arrival",
            "0.00",
            "Revised private note",
        ):
            self.assertContains(response, value)
        self.assertContains(response, reverse("logistics_parcel_edit", args=[parcel.pk]))
        self.assertEqual(response.context["latest_status_event"].pk, location.pk)
        self.assertEqual(response.context["latest_location"].pk, location.pk)
        self.assertEqual(response.context["shipment"].pk, shipment.pk)

    def test_edit_updates_metadata_atomically_preserving_identifiers_status_and_shipment(self):
        parcel = self.register()
        shipment = create_shipment(
            business=self.business, actor=self.user, origin="A", destination="B"
        )
        assign_parcel(business=self.business, shipment=shipment, parcel=parcel, actor=self.user)
        parcel.refresh_from_db()
        original = (
            parcel.business_id,
            parcel.client_id,
            parcel.tracking_code,
            parcel.created_by_id,
            parcel.created_at,
            parcel.current_status,
            parcel.shipment_id,
        )
        response = self.client.post(
            reverse("logistics_parcel_edit", args=[parcel.pk]),
            self.edit_data(
                parcel,
                **self.metadata(),
                package_description="Updated books",
                client=self.other_customer.pk,
                business=self.other.pk,
                current_status="DELIVERED",
                tracking_code="chosen",
                shipment="",
                created_by=self.other_user.pk,
            ),
        )
        self.assertEqual(response.status_code, 302)
        parcel.refresh_from_db()
        self.assertEqual(parcel.package_description, "Updated books")
        self.assertEqual(parcel.length_cm, Decimal("20.00"))
        self.assertEqual(parcel.issue_date, date(2026, 10, 1))
        self.assertEqual(
            original,
            (
                parcel.business_id,
                parcel.client_id,
                parcel.tracking_code,
                parcel.created_by_id,
                parcel.created_at,
                parcel.current_status,
                parcel.shipment_id,
            ),
        )
        event = parcel.events.latest("pk")
        self.assertEqual(
            (event.actor_id, event.event_type, event.status, event.public_message),
            (self.user.pk, ParcelEvent.Type.NOTE, "", ""),
        )
        self.assertIn("Parcel details updated:", event.internal_note)
        self.assertNotIn("PRIVATE-TAX-ID", event.internal_note)

    def test_edit_rejects_invalid_data_and_preserves_bound_values(self):
        parcel = self.register()
        response = self.client.post(
            reverse("logistics_parcel_edit", args=[parcel.pk]),
            self.edit_data(
                parcel,
                length_cm="0",
                sender_name="Keep my sender",
                quantity="0",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("length_cm", response.context["form"].errors)
        self.assertIn("quantity", response.context["form"].errors)
        self.assertContains(response, 'value="Keep my sender"')
        parcel.refresh_from_db()
        self.assertEqual(parcel.sender_name, "")
        self.assertEqual(parcel.events.count(), 1)
        with self.assertRaises(ValidationError):
            self.edit(parcel, width_cm="-1")
        self.assertEqual(parcel.events.count(), 1)

    def test_stale_edits_do_not_overwrite_newer_metadata_or_status(self):
        parcel = self.register()
        stale = self.edit_data(parcel, sender_name="Stale sender")
        self.edit(parcel, sender_name="Current sender")
        response = self.client.post(reverse("logistics_parcel_edit", args=[parcel.pk]), stale)
        self.assertContains(response, "The parcel changed.")
        parcel.refresh_from_db()
        self.assertEqual(parcel.sender_name, "Current sender")
        stale = self.edit_data(parcel, sender_name="Another stale sender")
        self.change(parcel, "RECEIVED")
        response = self.client.post(reverse("logistics_parcel_edit", args=[parcel.pk]), stale)
        self.assertContains(response, "The parcel changed.")
        parcel.refresh_from_db()
        self.assertEqual(
            (parcel.sender_name, parcel.current_status), ("Current sender", "RECEIVED")
        )
        self.assertEqual(parcel.events.count(), 3)

    def test_identical_edit_retry_appends_history_once(self):
        parcel = self.register()
        data = self.edit_data(parcel, sender_name="Replayed sender")
        url = reverse("logistics_parcel_edit", args=[parcel.pk])
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(parcel.events.count(), 2)

    def test_history_failure_rolls_back_metadata_write(self):
        parcel = self.register()
        original_updated_at = parcel.updated_at
        with patch.object(
            ParcelEvent, "_domain_save", side_effect=RuntimeError("event unavailable")
        ):
            with self.assertRaises(RuntimeError):
                self.edit(parcel, sender_name="Rolled back")
        parcel.refresh_from_db()
        self.assertEqual(parcel.sender_name, "")
        self.assertEqual(parcel.updated_at, original_updated_at)
        self.assertEqual(parcel.events.count(), 1)

    def test_service_rejects_non_metadata_fields(self):
        parcel = self.register()
        for name, value in (
            ("client", self.other_customer),
            ("business_id", self.other.pk),
            ("tracking_code", "chosen"),
            ("current_status", "DELIVERED"),
            ("shipment_id", 123),
            ("created_by", self.other_user),
        ):
            with self.subTest(field=name), self.assertRaises(ValidationError):
                self.edit(parcel, **{name: value})
        self.assertEqual(parcel.events.count(), 1)

    def test_cross_tenant_and_moved_client_edit_rejected(self):
        foreign = register_parcel(
            business=self.other,
            client=self.other_customer,
            actor=self.other_user,
            **self.fields,
        )
        url = reverse("logistics_parcel_edit", args=[foreign.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, self.edit_data(foreign)).status_code, 404)
        with self.assertRaises(ValidationError):
            self.edit(foreign, sender_name="Tampered")
        parcel = self.register()
        Client.objects.filter(pk=self.customer.pk).update(business=self.other)
        self.assertEqual(
            self.client.get(reverse("logistics_parcel_edit", args=[parcel.pk])).status_code, 404
        )
        with self.assertRaises(ValidationError):
            self.edit(parcel, sender_name="Tampered")
        self.assertEqual(ParcelEvent.objects.count(), 2)

    def test_roles_membership_and_service_vertical_enforced_for_edit(self):
        parcel = self.register()
        url = reverse("logistics_parcel_edit", args=[parcel.pk])
        for role in (BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN, BusinessUser.Role.STAFF):
            self.membership.role = role
            self.membership.save()
            self.assertEqual(self.client.get(url).status_code, 200)
            self.edit(parcel, sender_name=role)
        for role in (BusinessUser.Role.ACCOUNTANT, BusinessUser.Role.VIEWER):
            self.membership.role = role
            self.membership.save()
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, self.edit_data(parcel)).status_code, 403)
            with self.assertRaises(PermissionDenied):
                self.edit(parcel, sender_name="Denied")
            response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
            self.assertNotContains(response, "Edit Parcel")
        self.membership.is_active = False
        self.membership.save()
        with self.assertRaises(PermissionDenied):
            self.edit(parcel, sender_name="Denied")
        self.switch(self.service)
        self.assertEqual(self.client.get(url, HTTP_ACCEPT="application/json").status_code, 403)

    def test_restricted_subscription_allows_detail_and_denies_metadata_edit(self):
        parcel = self.register()
        now = timezone.now()
        BusinessSubscription.objects.filter(business=self.business).update(
            status="past_due",
            payment_provider="stripe",
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_metadata_test",
            provider_subscription_id="sub_metadata_test",
            provider_price_id="price_metadata_test",
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )
        response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Edit Parcel")
        url = reverse("logistics_parcel_edit", args=[parcel.pk])
        self.assertEqual(self.client.get(url, HTTP_ACCEPT="application/json").status_code, 403)
        self.assertEqual(
            self.client.post(
                url, self.edit_data(parcel), HTTP_ACCEPT="application/json"
            ).status_code,
            403,
        )
        with self.assertRaises(PermissionDenied):
            self.edit(parcel, sender_name="Denied")

    @override_settings(
        CACHES=TRACKING_CACHE,
        LOGISTICS_TRACKING_CACHE_ALIAS="default",
        LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE=False,
        LOGISTICS_TRACKING_CLIENT_IP_MODE="direct",
    )
    def test_public_tracking_excludes_all_new_metadata_and_edit_history(self):
        cache.clear()
        parcel = self.register(**self.metadata())
        original = lookup_public_tracking(parcel.tracking_code)
        self.edit(parcel, sender_name="PRIVATE-UPDATED-SENDER")
        self.assertEqual(lookup_public_tracking(parcel.tracking_code), original)
        response = self.client.post(
            reverse("logistics_public_tracking"), {"tracking_code": parcel.tracking_code}
        )
        for value in (
            "PRIVATE-HANDLING-NOTE",
            "PRIVATE-TAX-ID",
            "PRIVATE-UPDATED-SENDER",
            "Recipient Example",
            "Parcel details updated",
        ):
            self.assertNotContains(response, value)
        self.assertEqual(
            set(original), {"tracking_code", "status", "status_label", "business", "events"}
        )

    def test_editor_requires_csrf_and_stale_token(self):
        parcel = self.register()
        url = reverse("logistics_parcel_edit", args=[parcel.pk])
        browser = BrowserClient(enforce_csrf_checks=True)
        browser.force_login(self.user)
        session = browser.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.assertEqual(browser.post(url, self.edit_data(parcel)).status_code, 403)
        data = self.edit_data(parcel, sender_name="Unsaved")
        data.pop("expected_updated_at")
        response = self.client.post(url, data)
        self.assertIn("expected_updated_at", response.context["form"].errors)
        self.assertEqual(parcel.events.count(), 1)

    def test_edit_form_cannot_save_outside_domain_service(self):
        parcel = self.register()
        form = ParcelEditForm(instance=parcel, business=self.business)
        with self.assertRaises(NotImplementedError):
            form.save()

    def test_tracking_update_still_enforces_status_and_keeps_private_metadata(self):
        parcel = self.register(**self.metadata())
        response = self.client.post(
            reverse("logistics_parcel_update", args=[parcel.pk]),
            {
                "status": "DELIVERED",
                "expected_status": "REGISTERED",
                "idempotency_key": uuid.uuid4(),
                "sender_name": "Injected",
                "location": "Depot",
            },
        )
        self.assertEqual(response.status_code, 200)
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "REGISTERED")
        self.assertEqual(parcel.sender_name, "Sender Example")
        record_parcel_event(
            business=self.business,
            parcel=parcel,
            actor=self.user,
            status="RECEIVED",
            location="Depot",
        )
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "RECEIVED")
        self.assertEqual(parcel.sender_name, "Sender Example")
