"""Daily route entry uses tenant configuration without granting site operations."""

import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.models import BusinessUser, UserOnboardingState

from . import test_parcels
from .forms import ParcelEditForm, ParcelRegistrationForm
from .location_access import require_record_operation
from .location_access_services import review_location_access, set_location_assignment
from .models import LogisticsLocation, LogisticsProfile
from .parcel_services import edit_parcel, register_parcel
from .shipment_forms import ShipmentForm
from .shipment_services import assign_parcel, create_shipment, update_shipment


class RouteEntryTests(TestCase):
    switch = test_parcels.ParcelTests.switch

    def setUp(self):
        test_parcels.ParcelTests.setUp(self)
        self.business.country = "Anguilla"
        self.business.save(update_fields=["country"])
        self.profile, _ = LogisticsProfile.objects.get_or_create(business=self.business)
        self.profile.transportation_modes = ["SEA", "AIR"]
        self.profile.save()
        self.sxm = LogisticsLocation.objects.create(
            business=self.business,
            name="SXM warehouse",
            code="SXM",
            country_code="SX",
            location_type="WAREHOUSE",
        )
        self.dm = LogisticsLocation.objects.create(
            business=self.business,
            name="Roseau warehouse",
            code="DM",
            country_code="DM",
            location_type="WAREHOUSE",
        )
        self.foreign = LogisticsLocation.objects.create(
            business=self.other,
            name="Foreign warehouse",
            code="FOREIGN",
            country_code="DM",
            location_type="WAREHOUSE",
        )
        self.staff = TaskIOUser.objects.create_user(
            email="route-staff@example.com", password="Test123!"
        )
        member = BusinessUser.objects.create(business=self.business, user=self.staff, role="staff")
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=member,
            location=self.sxm,
            can_operate=True,
        )
        review_location_access(business=self.business, actor=self.user)
        self.profile.refresh_from_db()
        for user in (self.user, self.staff):
            UserOnboardingState.objects.get_or_create(
                business=self.business,
                user=user,
                defaults={"completed_welcome": True},
            )
        self.client.force_login(self.staff)
        self.switch(self.business)

    def data(self, shipment=False, **changes):
        data = {
            "origin_country_code": "SX",
            "destination_country_code": "DM",
            "origin_location": self.sxm.pk,
            "destination_location": self.dm.pk,
            "idempotency_key": str(uuid.uuid4()),
        }
        if shipment:
            data["transport_mode"] = "SEA"
        else:
            data.update(
                client=self.customer.pk,
                mode_of_transport="SEA",
                package_description="Synthetic cargo",
                quantity=2,
            )
        return {**data, **changes}

    def parcel_form(self, **changes):
        return ParcelRegistrationForm(
            self.data(**changes), business=self.business, actor=self.staff
        )

    def shipment_form(self, **changes):
        return ShipmentForm(
            self.data(shipment=True, **changes), business=self.business, actor=self.staff
        )

    def save_parcel(self):
        form = self.parcel_form()
        self.assertTrue(form.is_valid(), form.errors)
        return register_parcel(business=self.business, actor=self.staff, **form.cleaned_data)

    def save_shipment(self):
        form = self.shipment_form()
        self.assertTrue(form.is_valid(), form.errors)
        return create_shipment(business=self.business, actor=self.staff, **form.cleaned_data)

    def test_registration_has_one_pricing_quantity_in_add_charge(self):
        from decimal import Decimal

        from .billing_forms import LogisticsChargeForm
        from .models import Parcel

        response = self.client.get(reverse("logistics_parcel_register"))
        self.assertNotIn("quantity", response.context["form"].fields)
        self.assertNotContains(response, 'name="quantity"')
        data = self.data()
        data.pop("quantity")
        response = self.client.post(reverse("logistics_parcel_register"), data)
        self.assertEqual(response.status_code, 302)
        parcel = Parcel.objects.get()
        self.assertEqual(parcel.quantity, 1)
        response = self.client.get(reverse("logistics_parcel_edit", args=[parcel.pk]))
        self.assertEqual(response.context["form"]["quantity"].value(), 1)
        charge_url = reverse("logistics_parcel_charge", args=[parcel.pk]) + "?registration=1"
        response = self.client.get(charge_url)
        self.assertIsInstance(response.context["form"], LogisticsChargeForm)
        self.assertContains(response, 'name="quantity"', count=1)
        response = self.client.post(
            charge_url,
            {
                "charge_type": "custom",
                "description": "Freight",
                "quantity": "3",
                "unit_price": "10",
                "idempotency_key": uuid.uuid4(),
            },
        )
        self.assertEqual(response.status_code, 302)
        charge = parcel.charges.get()
        self.assertEqual(charge.quantity, Decimal("3"))
        self.assertEqual(charge.total, Decimal("30"))
        parcel.refresh_from_db()
        self.assertEqual(parcel.quantity, 1)

    def test_staff_all_business_destinations_and_valid_origin_defaults(self):
        for cls in (ParcelRegistrationForm, ShipmentForm):
            form = cls(business=self.business, actor=self.staff)
            self.assertEqual(form.initial["origin_location"], self.sxm.pk)
            self.assertEqual(form.initial["origin_country_code"], "SX")
            self.assertEqual(
                set(dict(form.fields["destination_country_code"].choices)), {"", "SX", "DM", "AI"}
            )
            self.assertEqual(set(form.fields["destination_location"].queryset), {self.sxm, self.dm})
            self.assertIn(
                str(self.dm.pk), {row["value"] for row in form.route_options["destination"]}
            )
            self.assertNotIn(
                str(self.foreign.pk), {row["value"] for row in form.route_options["destination"]}
            )
            self.assertNotIn(self.foreign, form.fields["destination_location"].queryset)
            self.assertEqual(
                [f.name for f in form.route_location_fields],
                [
                    "origin_country_code",
                    "destination_country_code",
                    "origin_location",
                    "destination_location",
                ],
            )
            self.assertTrue(form.fields["origin"].widget.is_hidden)
        for form in (self.parcel_form(), self.shipment_form()):
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["destination_location"], self.dm)
            self.assertEqual(form.cleaned_data["destination"], "Roseau warehouse")
        for url in ("logistics_parcel_register", "logistics_shipment_create"):
            response = self.client.get(reverse(url))
            self.assertContains(response, "Dominica")
            self.assertContains(response, "Additional details")
            self.assertNotContains(response, "Foreign warehouse")
            self.assertNotContains(response, "geographic place")

    def test_facilities_and_territories_reject_mismatch_foreign_and_unconfigured(self):
        for make in (self.parcel_form, self.shipment_form):
            for changes in (
                {"destination_location": self.foreign.pk},
                {"destination_country_code": "SX"},
                {"destination_country_code": "US"},
            ):
                form = make(**changes)
                self.assertFalse(form.is_valid())
        for country, site in (("SX", self.dm), ("DM", self.foreign)):
            with self.assertRaises(ValidationError):
                register_parcel(
                    business=self.business,
                    actor=self.staff,
                    client=self.customer,
                    origin="SXM",
                    destination="Test",
                    origin_location=self.sxm,
                    destination_country_code=country,
                    destination_location=site,
                    package_description="Test",
                    mode_of_transport="SEA",
                )

    def test_staff_can_create_and_edit_remote_destination_without_operating_there(self):
        parcel, shipment = self.save_parcel(), self.save_shipment()
        edit_parcel(
            business=self.business,
            actor=self.staff,
            parcel=parcel,
            destination_country_code="AI",
            destination_location=None,
        )
        update_shipment(
            business=self.business,
            actor=self.staff,
            shipment=shipment,
            expected_revision=shipment.revision,
            destination_country_code="AI",
            destination_location=None,
        )
        # Selecting a destination does not authorize editing records based there.
        remote = register_parcel(
            business=self.business,
            actor=self.user,
            client=self.customer,
            origin="Dominica",
            destination="Anguilla",
            origin_location=self.dm,
            package_description="Remote",
            mode_of_transport="SEA",
        )
        with self.assertRaises(PermissionDenied):
            require_record_operation(remote, business=self.business, actor=self.staff)
        with self.assertRaises(PermissionDenied):
            edit_parcel(
                business=self.business, actor=self.staff, parcel=parcel, origin_location=self.dm
            )

    def test_optional_facility_and_ports(self):
        for make in (self.parcel_form, self.shipment_form):
            form = make(destination_country_code="AI", destination_location="")
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["destination"], "Anguilla")
            self.assertFalse(form.fields["destination_reference_code"].required)
            self.assertEqual(form.cleaned_data["destination_reference_code"], "")

    def test_port_choices_match_territory_and_mode_and_legacy_ports_are_dropdowns(self):
        for make, mode_name in (
            (self.parcel_form, "mode_of_transport"),
            (self.shipment_form, "transport_mode"),
        ):
            for mode, allowed, rejected in (("SEA", "DMRSU", "DMDOM"), ("AIR", "DMDOM", "DMRSU")):
                form = make(**{mode_name: mode, "destination_reference_code": allowed})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertIn(allowed, dict(form.fields["destination_reference_code"].choices))
                self.assertNotIn(rejected, dict(form.fields["destination_reference_code"].choices))
                self.assertFalse(
                    make(**{mode_name: mode, "destination_reference_code": rejected}).is_valid()
                )
            self.assertFalse(make(destination_reference_code="USMIA").is_valid())
        self.assertTrue(self.parcel_form(port_discharge_unlocode="DMRSU").is_valid())
        self.assertFalse(
            self.parcel_form(mode_of_transport="AIR", port_discharge_unlocode="DMRSU").is_valid()
        )

    def test_modes_use_enabled_configuration_and_single_mode_default(self):
        self.profile.transportation_modes = ["AIR"]
        self.profile.save()
        for cls, field in (
            (ParcelRegistrationForm, "mode_of_transport"),
            (ShipmentForm, "transport_mode"),
        ):
            form = cls(business=self.business, actor=self.staff)
            self.assertEqual(form.initial[field], "AIR")
            self.assertEqual(set(dict(form.fields[field].choices)), {"", "AIR"})
            self.assertEqual(form.fields[field].label, "Transport mode")
        self.assertFalse(self.parcel_form(mode_of_transport="SEA").is_valid())
        self.assertFalse(self.shipment_form(transport_mode="SEA").is_valid())
        with self.assertRaises(ValidationError):
            register_parcel(
                business=self.business,
                actor=self.staff,
                client=self.customer,
                **self.fields,
                origin_location=self.sxm,
                mode_of_transport="SEA",
            )
        with self.assertRaises(ValidationError):
            create_shipment(
                business=self.business,
                actor=self.staff,
                origin="SXM",
                destination="DM",
                origin_location=self.sxm,
                transport_mode="SEA",
            )
        self.profile.transportation_modes = []
        self.profile.save()
        self.assertEqual(
            list(ShipmentForm(business=self.business).fields["transport_mode"].choices),
            [("", "Unknown")],
        )
        with self.assertRaises(ValidationError):
            create_shipment(
                business=self.business,
                actor=self.staff,
                origin="SXM",
                destination="DM",
                origin_location=self.sxm,
                transport_mode="AIR",
            )

    def test_mode_mismatches_rejected_on_assignment_and_edits(self):
        parcel, shipment = self.save_parcel(), self.save_shipment()
        air = create_shipment(
            business=self.business,
            actor=self.staff,
            origin="SXM",
            destination="DM",
            origin_location=self.sxm,
            transport_mode="AIR",
        )
        with self.assertRaises(ValidationError):
            assign_parcel(business=self.business, actor=self.staff, shipment=air, parcel=parcel)
        assign_parcel(business=self.business, actor=self.staff, shipment=shipment, parcel=parcel)
        with self.assertRaises(ValidationError):
            edit_parcel(
                business=self.business, actor=self.staff, parcel=parcel, mode_of_transport="AIR"
            )
        shipment.refresh_from_db()
        with self.assertRaises(ValidationError):
            update_shipment(
                business=self.business,
                actor=self.staff,
                shipment=shipment,
                expected_revision=shipment.revision,
                transport_mode="AIR",
            )

    def test_existing_missing_disabled_modes_and_text_are_preserved(self):
        parcel, shipment = self.save_parcel(), self.save_shipment()
        self.profile.transportation_modes = ["AIR"]
        self.profile.save()
        for mode in ("SEA", ""):
            # Synthetic historical snapshots, through model domain writes.
            parcel.mode_of_transport = mode
            parcel.origin = "Original detailed free text"
            parcel._domain_save(update_fields=["mode_of_transport", "origin"])
            form = ParcelEditForm(
                {"quantity": 3, "expected_updated_at": parcel.updated_at},
                instance=parcel,
                business=self.business,
                actor=self.staff,
            )
            self.assertTrue(form.is_valid(), form.errors)
            result = edit_parcel(
                business=self.business, actor=self.staff, parcel=parcel, **form.cleaned_data
            )
            self.assertEqual(result.mode_of_transport, mode)
            self.assertEqual(result.origin, "Original detailed free text")
            parcel.refresh_from_db()
        for mode in ("SEA", None):
            shipment.transport_mode = mode
            shipment._domain_save(update_fields=["transport_mode"])
            form = ShipmentForm(
                {"idempotency_key": uuid.uuid4(), "expected_revision": shipment.revision},
                instance=shipment,
                business=self.business,
                actor=self.staff,
            )
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["transport_mode"], mode)
            result = update_shipment(
                business=self.business,
                actor=self.staff,
                shipment=shipment,
                expected_revision=shipment.revision,
                notes="Retained mode",
            )
            self.assertEqual(result.transport_mode, mode)
            shipment.refresh_from_db()

    def test_optional_references_preserved_on_edit_and_wrong_mode_new_references_rejected(self):
        parcel = self.save_parcel()
        edit_parcel(
            business=self.business, actor=self.staff, parcel=parcel, vessel_name="Saved vessel"
        )
        parcel.refresh_from_db()
        edit_parcel(
            business=self.business, actor=self.staff, parcel=parcel, mode_of_transport="AIR"
        )
        parcel.refresh_from_db()
        self.assertEqual(parcel.vessel_name, "Saved vessel")
        with self.assertRaises(ValidationError):
            edit_parcel(
                business=self.business, actor=self.staff, parcel=parcel, vessel_name="New vessel"
            )

    def test_creation_retries_survive_mode_and_facility_configuration_changes(self):
        parcel_data, shipment_data = self.data(), self.data(shipment=True)
        parcel_form = ParcelRegistrationForm(parcel_data, business=self.business, actor=self.staff)
        shipment_form = ShipmentForm(shipment_data, business=self.business, actor=self.staff)
        self.assertTrue(parcel_form.is_valid(), parcel_form.errors)
        self.assertTrue(shipment_form.is_valid(), shipment_form.errors)
        parcel = register_parcel(
            business=self.business, actor=self.staff, **parcel_form.cleaned_data
        )
        shipment = create_shipment(
            business=self.business, actor=self.staff, **shipment_form.cleaned_data
        )
        self.profile.transportation_modes = ["AIR"]
        self.profile.save()
        self.dm.is_active = False
        self.dm.save()
        for cls, data, service, record in (
            (ParcelRegistrationForm, parcel_data, register_parcel, parcel),
            (ShipmentForm, shipment_data, create_shipment, shipment),
        ):
            form = cls(data, business=self.business, actor=self.staff)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(
                service(business=self.business, actor=self.staff, **form.cleaned_data).pk, record.pk
            )

    def test_historical_mismatched_assignment_allows_unchanged_mode_edit(self):
        parcel, shipment = self.save_parcel(), self.save_shipment()
        assign_parcel(business=self.business, actor=self.staff, shipment=shipment, parcel=parcel)
        parcel.refresh_from_db()
        parcel.mode_of_transport = "AIR"
        parcel._domain_save(update_fields=["mode_of_transport"])
        shipment.refresh_from_db()
        update_shipment(
            business=self.business,
            actor=self.staff,
            shipment=shipment,
            expected_revision=shipment.revision,
            transport_mode="SEA",
            notes="Historical edit",
        )

    def test_territory_change_rejects_retained_port_from_another_territory(self):
        parcel = self.save_parcel()
        edit_parcel(
            business=self.business, actor=self.staff, parcel=parcel, port_discharge_unlocode="DMRSU"
        )
        with self.assertRaises(ValidationError):
            edit_parcel(
                business=self.business,
                actor=self.staff,
                parcel=parcel,
                destination_country_code="AI",
                destination_location=None,
            )
