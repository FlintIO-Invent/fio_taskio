"""Snapshot independence, actual symbol decoding, physical layout and private exports."""

import uuid
from io import BytesIO, StringIO
from unittest.mock import patch

import pypdfium2 as pdfium
import zxingcpp
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db.models import QuerySet
from django.test import TestCase, override_settings
from django.urls import reverse
from pypdf import PdfReader

from apps.businesses.models import BusinessSubscription, BusinessUser, DemoSeedRun

from . import test_demo_data, test_location_operations, test_parcels
from .forms import ParcelEditForm, ParcelRegistrationForm
from .location_access_services import set_location_assignment
from .models import Parcel, ParcelEvent
from .parcel_services import edit_parcel
from .public_tracking import lookup_public_tracking
from .scan import normalize_scan_code, resolve_scanned_parcel
from .shipment_services import assign_parcel, create_shipment
from .shipping_labels import (
    LABEL_HEIGHT,
    LABEL_WIDTH,
    render_shipping_label_pdf,
    shipping_party_lines,
)


def pdf_text(data):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


class ShippingLabelTests(TestCase):
    setUp = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    register = test_parcels.ParcelTests.register

    def shipping(self):
        return {
            "sender_name": "PRIVATE Sender Company",
            "sender_contact": "+1 555 0100",
            "sender_address_line_1": "22 Sender Street",
            "sender_address_line_2": "Unit 4",
            "sender_city": "Miami",
            "sender_region": "Florida",
            "sender_postal_code": "33101",
            "sender_country_code": "US",
            "recipient_name": "PRIVATE Recipient Company",
            "recipient_contact": "recipient@example.test",
            "recipient_address_line_1": "10 Recipient Road",
            "recipient_address_line_2": "Building B",
            "recipient_city": "Philipsburg",
            "recipient_region": "Lower Prince's Quarter",
            "recipient_postal_code": "1234",
            "recipient_country_code": "SX",
        }

    def url(self, parcel, *, pdf=False):
        return reverse(
            "logistics_shipping_label_pdf" if pdf else "logistics_shipping_label", args=[parcel.pk]
        )

    def test_registration_form_and_service_persist_snapshots_without_client_changes(self):
        before = self.customer.__dict__.copy()
        form = ParcelRegistrationForm(
            {
                **self.fields,
                **self.shipping(),
                "client": self.customer.pk,
                "idempotency_key": uuid.uuid4(),
            },
            business=self.business,
            actor=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        parcel = self.register(**self.shipping())
        parcel.refresh_from_db()
        for name, value in self.shipping().items():
            self.assertEqual(getattr(parcel, name), value)
        self.customer.refresh_from_db()
        for name, value in before.items():
            if not name.startswith("_"):
                self.assertEqual(getattr(self.customer, name), value)
        edit_parcel(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            recipient_city="Roseau",
            recipient_country_code="DM",
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.country, before["country"])
        self.assertEqual(parcel.events.count(), 2)

    def test_iso_choices_and_invalid_country_service_validation(self):
        form = ParcelRegistrationForm(business=self.business, actor=self.user)
        for side in ("sender", "recipient"):
            choices = dict(form.fields[f"{side}_country_code"].choices)
            self.assertIn("Sint Maarten", choices["SX"])
            self.assertEqual(choices["DM"], "Dominica")
            self.assertEqual(choices["AI"], "Anguilla")
            self.assertIn(
                "data-logistics-search-select", form.fields[f"{side}_country_code"].widget.attrs
            )
        for field in ("sender_country_code", "recipient_country_code"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.register(**{field: "ZZ"})
        self.assertFalse(Parcel.objects.exists())

    def test_legacy_codes_missing_parties_and_free_text_remain_usable(self):
        parcel = self.register(
            sender_address="Historical sender street",
            recipient_address="Historical recipient street",
        )
        QuerySet(model=Parcel).filter(pk=parcel.pk).update(
            tracking_code="F" * 48, sender_country_code="ZZ"
        )
        parcel.refresh_from_db()
        response = self.client.get(self.url(parcel, pdf=True))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Historical sender street", pdf_text(response.content))
        self.assertIn("Historical recipient street", pdf_text(response.content))
        form = ParcelEditForm(instance=parcel, business=self.business, actor=self.user)
        self.assertIn("ZZ", dict(form.fields["sender_country_code"].choices))
        edit_parcel(
            business=self.business, actor=self.user, parcel=parcel, internal_reference="LEGACY"
        )
        parcel.refresh_from_db()
        self.assertEqual(parcel.sender_name, "")
        self.assertIsNone(parcel.recipient_country_code)
        self.assertEqual(parcel.tracking_code, "F" * 48)
        empty = self.register()
        text = pdf_text(self.client.get(self.url(empty, pdf=True)).content)
        self.assertIn("Sender information not recorded", text)
        self.assertIn("Recipient information not recorded", text)
        self.assertNotIn(str(self.customer), text)

    def test_older_edit_payload_retains_additive_address_fields(self):
        parcel = self.register(**self.shipping())
        form = ParcelEditForm(
            {
                **self.fields,
                "expected_updated_at": parcel.updated_at.isoformat(),
                "sender_country_code": "US",
            },
            instance=parcel,
            business=self.business,
            actor=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["recipient_address_line_1"], "10 Recipient Road")
        self.assertEqual(form.cleaned_data["recipient_country_code"], "SX")

    def test_client_prefill_is_explicit_scoped_and_read_only(self):
        self.customer.street_address = "Prefill Street"
        self.customer.district = "PHILIPSBURG"
        self.customer.country = "Sint Maarten"
        self.customer.save()
        before = self.customer.__dict__.copy()
        url = reverse("logistics_shipping_prefill")
        response = self.client.get(url, {"client": self.customer.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["address_line_1"], "Prefill Street")
        self.assertEqual(response.json()["country_code"], "SX")
        self.assertEqual(response.json()["postal_code"], "")
        self.assertEqual(self.client.get(url, {"client": self.other_customer.pk}).status_code, 404)
        self.assertEqual(self.client.post(url, {"client": self.customer.pk}).status_code, 405)
        self.assertFalse(Parcel.objects.exists())
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.updated_at, before["updated_at"])

    def test_pdf_is_one_4_by_6_page_and_symbols_decode_exact_legacy_and_v2(self):
        for code in ("F" * 48, "A10F" * 12, "MM-PCL-" + "ABCDEFGHJKMNPQRSTUVWXYZ23456789ABCDEFGH"):
            parcel = self.register(**self.shipping(), weight_kg="1.250")
            QuerySet(model=Parcel).filter(pk=parcel.pk).update(tracking_code=code)
            parcel.refresh_from_db()
            data = render_shipping_label_pdf(parcel, current_business=self.business)
            reader = PdfReader(BytesIO(data))
            self.assertEqual(len(reader.pages), 1)
            self.assertEqual(tuple(reader.pages[0].mediabox), (0, 0, LABEL_WIDTH, LABEL_HEIGHT))
            text = pdf_text(data)
            self.assertIn("Weight: 1.250 kg", text)
            self.assertIn(code, "".join(text.split()))
            with pdfium.PdfDocument(data) as document:
                page = document[0]
                textpage = page.get_textpage()
                try:
                    for index in range(textpage.count_chars()):
                        if textpage.get_text_range(index, 1).strip():
                            left, bottom, right, top = textpage.get_charbox(index)
                            self.assertGreaterEqual(min(left, bottom), 0)
                            self.assertLessEqual(right, LABEL_WIDTH)
                            self.assertLessEqual(top, LABEL_HEIGHT)
                finally:
                    textpage.close()
                for dpi in (203, 300):
                    bitmap = page.render(scale=dpi / 72)
                    try:
                        symbols = zxingcpp.read_barcodes(bitmap.to_pil())
                    finally:
                        bitmap.close()
                    self.assertEqual(
                        {str(symbol.format) for symbol in symbols}, {"QR Code", "Code 128"}
                    )
                    for symbol in symbols:
                        self.assertEqual(symbol.text, code)
                        self.assertEqual(normalize_scan_code(symbol.text), code)
                        self.assertEqual(
                            resolve_scanned_parcel(
                                business=self.business, actor=self.user, code=symbol.text
                            ).pk,
                            parcel.pk,
                        )
                page.close()

    def test_long_addresses_wrap_without_loss_and_unprintable_overflow_is_explicit(self):
        fields = self.shipping()
        long_line = "Distribution Centre Warehouse Avenue " * 5
        fields.update(
            sender_address_line_1=long_line,
            sender_address_line_2=long_line,
            recipient_address_line_1=long_line,
            recipient_address_line_2=long_line,
        )
        parcel = self.register(**fields)
        response = self.client.get(self.url(parcel, pdf=True))
        self.assertEqual(response.status_code, 200)
        text = " ".join(pdf_text(response.content).split())
        self.assertIn(long_line.strip(), text)
        self.assertIn(
            "10 Recipient Road",
            shipping_party_lines(
                self.register(recipient_address="10 Recipient Road", recipient_city="Roseau"),
                "recipient",
            ),
        )
        for side in ("sender", "recipient"):
            setattr(parcel, f"{side}_name", "W" * 255)
            for suffix in ("address_line_1", "address_line_2"):
                setattr(parcel, f"{side}_{suffix}", "W" * 255)
            setattr(parcel, f"{side}_city", "W" * 100)
            setattr(parcel, f"{side}_region", "W" * 100)
        with self.assertRaisesMessage(ValidationError, "too long"):
            render_shipping_label_pdf(parcel, current_business=self.business)

    def test_pdf_and_preview_are_private_and_html_text_is_escaped(self):
        parcel = self.register(
            **{**self.shipping(), "recipient_name": '<script>alert("label")</script>'}
        )
        before = list(ParcelEvent.objects.values())
        response = self.client.get(self.url(parcel))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("label")</script>')
        self.assertNotContains(response, "dashboard_parent")
        self.assertContains(response, "size: 4in 6in")
        response = self.client.get(self.url(parcel, pdf=True) + "?download=1")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(list(ParcelEvent.objects.values()), before)
        self.assertEqual(self.client.post(self.url(parcel)).status_code, 405)

    @override_settings(LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE=False)
    def test_public_tracking_excludes_every_shipping_field(self):
        parcel = self.register(**self.shipping())
        result = lookup_public_tracking(parcel.tracking_code)
        self.assertIsNotNone(result)
        projection = str(result)
        self.assertNotIn("PRIVATE", projection)
        for field in self.shipping():
            self.assertNotIn(field, projection)

    def test_related_shipment_reference_and_mode_respect_own_access(self):
        parcel = self.register(**self.shipping())
        shipment = create_shipment(
            business=self.business,
            actor=self.user,
            origin="Miami",
            destination="Curacao",
            transport_mode="SEA",
        )
        assign_parcel(business=self.business, actor=self.user, parcel=parcel, shipment=shipment)
        response = self.client.get(self.url(parcel, pdf=True))
        self.assertIn(shipment.reference, "".join(pdf_text(response.content).split()))
        self.assertIn("Mode: Sea", pdf_text(response.content))
        with patch(
            "apps.logistics.shipment_services.shipments_for_business", side_effect=PermissionDenied
        ):
            response = self.client.get(self.url(parcel, pdf=True))
        self.assertNotIn(shipment.reference, "".join(pdf_text(response.content).split()))
        parcel.refresh_from_db()
        with self.assertRaises(ValueError):
            render_shipping_label_pdf(parcel, current_business=self.other)

    def test_anonymous_cross_tenant_service_and_revoked_membership_denied(self):
        parcel = self.register()
        self.client.logout()
        self.assertEqual(self.client.get(self.url(parcel)).status_code, 302)
        self.client.force_login(self.other_user)
        self.switch(self.other)
        self.assertEqual(self.client.get(self.url(parcel, pdf=True)).status_code, 404)
        self.client.force_login(self.user)
        self.switch(self.service)
        self.assertIn(self.client.get(self.url(parcel, pdf=True)).status_code, (302, 403))
        self.switch(self.business)
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        self.assertIn(self.client.get(self.url(parcel)).status_code, (302, 403))

    def test_role_and_effective_subscription_access_remain_enforced(self):
        parcel = self.register()
        self.membership.role = BusinessUser.Role.VIEWER
        self.membership.save(update_fields=["role"])
        self.assertEqual(self.client.get(self.url(parcel)).status_code, 404)
        self.assertEqual(
            self.client.get(
                reverse("logistics_shipping_prefill"), {"client": self.customer.pk}
            ).status_code,
            403,
        )
        self.membership.role = BusinessUser.Role.OWNER
        self.membership.save(update_fields=["role"])
        BusinessSubscription.objects.filter(business=self.business).update(
            status=BusinessSubscription.Status.EXPIRED
        )
        self.assertIn(self.client.get(self.url(parcel, pdf=True)).status_code, (302, 403))


class ShippingLabelLocationAccessTests(TestCase):
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    setUp = test_location_operations.LocationOperationsTests.setUp
    select = test_location_operations.LocationOperationsTests.select
    parcel = test_location_operations.LocationOperationsTests.parcel

    def test_worker_exports_are_scoped_and_grants_rechecked(self):
        self.select(self.user, self.unrelated)
        hidden = self.parcel(origin_location=self.unrelated, destination_location=self.unrelated)
        self.select(self.user, self.a)
        self.client.force_login(self.staff)
        self.switch(self.business)
        for route in ("logistics_shipping_label", "logistics_shipping_label_pdf"):
            self.assertEqual(self.client.get(reverse(route, args=[self.item.pk])).status_code, 200)
            self.assertEqual(self.client.get(reverse(route, args=[hidden.pk])).status_code, 404)
        for site in (self.a, self.b, self.stop):
            set_location_assignment(
                business=self.business,
                actor=self.user,
                membership=self.member,
                location=site,
                revoke=True,
            )
        self.assertIn(
            self.client.get(
                reverse("logistics_shipping_label_pdf", args=[self.item.pk])
            ).status_code,
            (403, 404),
        )


class ShippingLabelDemoTests(TestCase):
    setUp = test_demo_data.LogisticsDemoDataTests.setUp

    def test_preview_existing_seed_and_owned_snapshots_are_preserved(self):
        call_command("seed_logistics_demo_data", business_id=self.business.pk, stdout=StringIO())
        self.assertFalse(Parcel.objects.exists())
        call_command(
            "seed_logistics_demo_data",
            business_id=self.business.pk,
            execute=True,
            stdout=StringIO(),
        )
        self.assertEqual(Parcel.objects.count(), 20)
        for parcel in Parcel.objects.all():
            self.assertTrue(parcel.sender_name)
            self.assertTrue(parcel.recipient_name)
            self.assertTrue(parcel.sender_address_line_1)
            self.assertTrue(parcel.recipient_address_line_1)
            self.assertEqual(parcel.recipient_country_code, "SX")
            self.assertIn(
                str(parcel.pk),
                DemoSeedRun.objects.get()
                .owned_records.filter(model_label=Parcel._meta.label)
                .values_list("object_pk", flat=True),
            )
            render_shipping_label_pdf(parcel, current_business=self.business)
