import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.businesses.business_data_inventory import (
    build_business_data_inventory,
    find_unregistered_direct_business_relations,
)
from apps.businesses.business_data_purge import purge_business
from apps.businesses.forms import BusinessSettingsForm
from apps.businesses.models import BusinessUser

from . import test_parcels
from .forms import LogisticsApplicationForm, ParcelEditForm, ParcelRegistrationForm
from .location_forms import LogisticsLocationForm
from .location_reference import country_choices, exact_country_code, location_references
from .location_services import save_location
from .models import LogisticsLocation, Parcel
from .parcel_services import edit_parcel
from .shipment_forms import ShipmentForm
from .shipment_services import create_shipment, update_shipment
from .tests import application_data


class LocationTests(TestCase):
    setUp = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    register = test_parcels.ParcelTests.register

    def facility(self, **changes):
        return save_location(
            business=self.business,
            actor=self.user,
            **{
                "name": "Philipsburg warehouse",
                "code": "WH-PHI",
                "country_code": "SX",
                "location_type": "WAREHOUSE",
                **changes,
            },
        )

    def shipment(self, **fields):
        return create_shipment(
            business=self.business,
            actor=self.user,
            origin="Miami",
            destination="Philipsburg",
            **fields,
        )

    def test_iso_reference_names_and_exact_matching(self):
        countries = dict(country_choices())
        self.assertEqual(len(countries), 249)
        self.assertEqual(countries["SX"], "Sint Maarten (Dutch part)")
        self.assertEqual(countries["DM"], "Dominica")
        self.assertEqual(countries["AI"], "Anguilla")
        self.assertEqual(countries["CW"], "Curaçao")
        self.assertEqual(exact_country_code("  Dominica  "), "DM")
        self.assertEqual(exact_country_code("DMA"), "DM")
        for value in ("Dominican", "St Martin", "Congo basin", "Miami", ""):
            self.assertIsNone(exact_country_code(value))

    def test_standard_country_names_preserve_configured_territory_policy(self):
        from .eligibility import evaluate_eligibility
        from .policy import LogisticsEligibilityPolicy

        policy = LogisticsEligibilityPolicy(supported_territories=("Sint Maarten", "Curacao", "NL"))
        for country in ("Sint Maarten (Dutch part)", "SX", "Curaçao", "Netherlands"):
            decision = evaluate_eligibility(application_data(country=country), policy)
            self.assertNotIn("UNSUPPORTED_TERRITORY", decision.reason_codes)
        self.assertIn(
            "UNSUPPORTED_TERRITORY",
            evaluate_eligibility(application_data(country="Dominica"), policy).reason_codes,
        )
        for country, code in (("Sint Maarten", "SX"), ("CW", "CW")):
            form = LogisticsApplicationForm(data=application_data(country=country))
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.instance.country_code, code)

    def test_creation_retries_retain_now_inactive_facilities(self):
        item = self.facility()
        parcel_key, shipment_key = uuid.uuid4(), uuid.uuid4()
        parcel = self.register(destination_location=item, idempotency_key=parcel_key)
        shipment = self.shipment(destination_location=item, idempotency_key=shipment_key)
        save_location(business=self.business, actor=self.user, location=item, is_active=False)
        self.assertEqual(
            self.register(destination_location=item, idempotency_key=parcel_key).pk, parcel.pk
        )
        self.assertEqual(
            self.shipment(destination_location=item, idempotency_key=shipment_key).pk, shipment.pk
        )
        for form in (
            ParcelRegistrationForm(
                business=self.business,
                data={
                    **self.fields,
                    "client": self.customer.pk,
                    "idempotency_key": parcel_key,
                    "destination_location": item.pk,
                },
            ),
            ShipmentForm(
                business=self.business,
                data={
                    "origin": "Miami",
                    "destination": "Philipsburg",
                    "idempotency_key": shipment_key,
                    "destination_location": item.pk,
                },
            ),
        ):
            self.assertIn(item, form.fields["destination_location"].queryset)
            self.assertTrue(form.is_valid(), form.errors)

    def test_verified_references_have_provenance_and_types(self):
        references = location_references()
        self.assertEqual(references["SXPHI"]["country_code"], "SX")
        self.assertEqual(references["DMRSU"]["types"], ["PORT"])
        self.assertIn("AIRPORT", references["SXSXM"]["types"])
        for reference in references.values():
            self.assertIn(reference["country_code"], dict(country_choices()))
            self.assertTrue(set(reference["types"]) <= {"PORT", "AIRPORT"})
            self.assertIn(reference["status"], ("AI", "AS", "RL"))

    def test_exact_country_backfill_preserves_legacy_registration_retry(self):
        key = uuid.uuid4()
        fields = {"origin": "Dominica", "destination": "Anguilla", "idempotency_key": key}
        parcel = self.register(**fields)
        QuerySet.update(
            Parcel.objects.filter(pk=parcel.pk),
            origin_country_code="DM",
            destination_country_code="AI",
        )
        replay = self.register(**fields)
        self.assertEqual(replay.pk, parcel.pk)
        self.assertEqual(replay.origin_country_code, "DM")
        self.assertEqual(replay.events.count(), 1)

    def test_location_creation_normalization_and_database_uniqueness(self):
        item = self.facility(code="wh-phi")
        self.assertEqual(item.code, "WH-PHI")
        for changes in (
            {"name": "Other name", "code": "wh-phi"},
            {"name": "philipsburg warehouse", "code": "WH-TWO"},
        ):
            with self.assertRaises(ValidationError):
                self.facility(**changes)
        # Verify constraints independently of model validation.
        with self.assertRaises(IntegrityError), transaction.atomic():
            QuerySet.bulk_create(
                LogisticsLocation.objects.all(),
                [
                    LogisticsLocation(
                        business=self.business,
                        name="Duplicate",
                        code="wh-phi",
                        country_code="SX",
                        location_type="HUB",
                    )
                ],
            )
        other = LogisticsLocation.objects.create(
            business=self.other,
            name=item.name,
            code=item.code,
            country_code="SX",
            location_type="WAREHOUSE",
        )
        self.assertNotEqual(item.pk, other.pk)

    def test_stable_code_country_and_tenant_are_immutable(self):
        item = self.facility()
        for changes in ({"code": "NEW-CODE"}, {"country_code": "DM"}, {"business": self.other}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                for name, value in changes.items():
                    setattr(item, name, value)
                item.save()
            item.refresh_from_db()

    def test_country_and_reference_type_validation(self):
        for changes in (
            {"country_code": "XX"},
            {"reference_code": "FAKE"},
            {"reference_code": "SXPHI"},
            {"reference_code": "DMRSU", "location_type": "PORT"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.facility(**changes)
        item = self.facility(reference_code="SXSXM", location_type="AIRPORT")
        self.assertEqual(item.reference_code, "SXSXM")

    def test_location_service_role_and_subscription_boundaries(self):
        for role in (
            BusinessUser.Role.STAFF,
            BusinessUser.Role.VIEWER,
            BusinessUser.Role.ACCOUNTANT,
        ):
            self.membership.role = role
            self.membership.save()
            with self.assertRaises(PermissionDenied):
                self.facility()
            self.assertEqual(
                self.client.get(reverse("logistics_location_settings")).status_code, 403
            )
        self.membership.role = BusinessUser.Role.ADMIN
        self.membership.save()
        item = self.facility()
        self.assertEqual(item.business, self.business)
        self.business.subscription.status = "cancelled"
        self.business.subscription.save()
        with self.assertRaises(PermissionDenied):
            save_location(business=self.business, actor=self.user, location=item, name="Changed")

    def test_facility_views_csrf_and_tenant_scope(self):
        item = self.facility()
        other = LogisticsLocation.objects.create(
            business=self.other,
            name="Other tenant",
            code="OTHER-HUB",
            country_code="DM",
            location_type="HUB",
        )
        response = self.client.get(reverse("logistics_location_settings"))
        self.assertContains(response, item.name)
        self.assertNotContains(response, other.name)
        self.assertEqual(
            self.client.get(reverse("logistics_location_edit", args=[other.pk])).status_code, 404
        )
        from django.test import Client

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        session = csrf_client.session
        from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.assertEqual(
            csrf_client.post(reverse("logistics_location_settings"), {}).status_code, 403
        )
        response = self.client.post(
            reverse("logistics_location_settings"),
            {
                "name": "Registered branch",
                "code": "BR-TWO",
                "location_type": "BRANCH",
                "country_code": "AI",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            LogisticsLocation.objects.filter(business=self.business, code="BR-TWO").exists()
        )

    def test_route_forms_searchable_scoped_and_separate(self):
        item = self.facility()
        other = LogisticsLocation.objects.create(
            business=self.other,
            name="Other tenant",
            code="OTHER-HUB",
            country_code="DM",
            location_type="HUB",
        )
        inactive = self.facility(name="Inactive", code="INACTIVE", is_active=False)
        for form in (
            ParcelRegistrationForm(business=self.business),
            ShipmentForm(business=self.business),
        ):
            self.assertIn(item, form.fields["destination_location"].queryset)
            self.assertNotIn(other, form.fields["destination_location"].queryset)
            self.assertNotIn(inactive, form.fields["destination_location"].queryset)
            for field in form.route_location_fields:
                self.assertIn("data-logistics-search-select", field.field.widget.attrs)
        for form in (
            LogisticsApplicationForm(),
            BusinessSettingsForm(instance=self.business),
            LogisticsLocationForm(business=self.business),
        ):
            name = "country_code" if isinstance(form, LogisticsLocationForm) else "country"
            self.assertIn("data-logistics-search-select", form.fields[name].widget.attrs)
        parcel_form = ParcelRegistrationForm(
            data={
                "client": self.customer.pk,
                "idempotency_key": uuid.uuid4(),
                **self.fields,
                "destination_location": other.pk,
            },
            business=self.business,
        )
        self.assertFalse(parcel_form.is_valid())
        self.assertIn("destination_location", parcel_form.errors)

    def test_geography_without_branches_and_addresses_preserved(self):
        parcel = self.register(
            origin_country_code="US",
            destination_country_code="DM",
            destination_reference_code="DMRSU",
            sender_address="123 Private Street",
            recipient_address="456 Private Road",
        )
        shipment = self.shipment(
            origin_country_code="US",
            destination_country_code="DM",
            destination_reference_code="DMRSU",
        )
        self.assertIsNone(parcel.destination_location)
        self.assertEqual(parcel.destination, "Curacao")
        self.assertEqual(parcel.recipient_address, "456 Private Road")
        self.assertFalse(parcel.location_review_required)
        self.assertFalse(shipment.location_review_required)
        self.assertEqual(LogisticsLocation.objects.count(), 0)
        self.assertContains(
            self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk])), "Dominica"
        )

    def test_route_model_and_services_enforce_tenant_country_and_reference(self):
        item = self.facility()
        for changes in ({"business": self.other},):
            foreign = LogisticsLocation.objects.create(
                name="Foreign", code="FOREIGN", country_code="SX", location_type="HUB", **changes
            )
        for fields in (
            {"destination_location": foreign},
            {"destination_location": item, "destination_country_code": "DM"},
            {"destination_reference_code": "FAKE"},
            {"destination_location": item, "destination_reference_code": "DMRSU"},
            {"destination_country_code": "AI", "destination_reference_code": "DMRSU"},
        ):
            for create in (self.register, self.shipment):
                with self.subTest(fields=fields, create=create), self.assertRaises(ValidationError):
                    create(**fields)

    def test_inactive_retention_new_assignment_rejected_and_protected_deletion(self):
        item = self.facility()
        parcel = self.register(destination_location=item)
        shipment = self.shipment(destination_location=item)
        save_location(business=self.business, actor=self.user, location=item, is_active=False)
        item.refresh_from_db()
        for create in (self.register, self.shipment):
            with self.assertRaises(ValidationError):
                create(destination_location=item)
        for form in (
            ParcelEditForm(instance=parcel, business=self.business),
            ShipmentForm(instance=shipment, business=self.business),
        ):
            self.assertIn(item, form.fields["destination_location"].queryset)
        parcel = edit_parcel(
            business=self.business, parcel=parcel, actor=self.user, internal_notes="Retained"
        )
        shipment = update_shipment(
            business=self.business, shipment=shipment, actor=self.user, notes="Retained"
        )
        self.assertEqual(parcel.destination_location, item)
        self.assertEqual(shipment.destination_location, item)
        with self.assertRaises(ProtectedError):
            item.delete()

    def test_shipment_fk_edit_and_retry_are_stable(self):
        item = self.facility()
        key = uuid.uuid4()
        shipment = self.shipment(
            idempotency_key=key, destination_location=item, destination_country_code="SX"
        )
        self.assertEqual(
            self.shipment(
                idempotency_key=key, destination_location=item, destination_country_code="SX"
            ).pk,
            shipment.pk,
        )
        key = uuid.uuid4()
        revised = update_shipment(
            business=self.business,
            shipment=shipment,
            actor=self.user,
            expected_revision=shipment.revision,
            idempotency_key=key,
            origin_location=item,
            origin_country_code="SX",
        )
        replay = update_shipment(
            business=self.business,
            shipment=shipment,
            actor=self.user,
            expected_revision=shipment.revision,
            idempotency_key=key,
            origin_location=item,
            origin_country_code="SX",
        )
        self.assertEqual(revised.revision, replay.revision)
        self.assertEqual(replay.origin_location, item)

    def test_legacy_form_edits_preserve_structured_fields(self):
        item = self.facility()
        parcel = self.register(destination_location=item, destination_country_code="SX")
        form = ParcelEditForm(
            instance=parcel,
            business=self.business,
            data={**self.fields, "expected_updated_at": parcel.updated_at.isoformat()},
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["destination_location"], item)
        self.assertEqual(form.cleaned_data["destination_country_code"], "SX")

    def test_application_country_selection_and_legacy_preservation(self):
        form = LogisticsApplicationForm(data=application_data(country="Dominica"))
        self.assertTrue(form.is_valid(), form.errors)
        application = form.save()
        self.assertEqual(application.country_code, "DM")
        application.country = "Unresolved historical territory"
        application.save()
        form = LogisticsApplicationForm(
            instance=application, data=application_data(country=application.country)
        )
        self.assertTrue(form.is_valid(), form.errors)
        application = form.save()
        self.assertTrue(application.location_review_required)
        fresh = LogisticsApplicationForm(data=application_data(country=application.country))
        self.assertFalse(fresh.is_valid())
        form = LogisticsApplicationForm(
            instance=application, data=application_data(country="Anguilla")
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().country_code, "AI")

    def test_review_flags_clear_after_structured_route_review(self):
        parcel = self.register()
        self.assertTrue(parcel.location_review_required)
        parcel = edit_parcel(
            business=self.business,
            parcel=parcel,
            actor=self.user,
            origin_country_code="US",
            destination_country_code="CW",
        )
        parcel.refresh_from_db()
        self.assertFalse(parcel.location_review_required)
        self.assertEqual(parcel.origin, "Miami")

    def test_inventory_and_controlled_purge_include_facilities(self):
        item = self.facility()
        self.register(destination_location=item)
        self.shipment(destination_location=item)
        self.assertFalse(find_unregistered_direct_business_relations())
        self.business.is_active = False
        self.business.save()
        purge_business(
            business_id=self.business.pk,
            reason_reference="TEST-LOCATION-PURGE",
        )
        self.assertFalse(LogisticsLocation.objects.filter(pk=item.pk).exists())

    def test_cross_tenant_corruption_blocks_purge(self):
        parcel = self.register()
        # Simulate historical/manual corruption; normal domain writes forbid this.
        QuerySet.update(
            Parcel.objects.filter(pk=parcel.pk),
            destination_location=LogisticsLocation.objects.create(
                business=self.other,
                name="Foreign",
                code="FOREIGN",
                country_code="SX",
                location_type="HUB",
            ),
        )
        inventory = build_business_data_inventory(self.business)
        self.assertTrue(
            any(
                check.check_code == "cross_tenant_parcel_destination_location_outbound"
                and check.affected_count
                for check in inventory.integrity_checks
            )
        )

    def test_service_settings_are_unchanged_and_facilities_not_available(self):
        form = BusinessSettingsForm(instance=self.service)
        self.assertNotIn("data-logistics-search-select", form.fields["country"].widget.attrs)
        self.switch(self.service)
        response = self.client.get(reverse("business_settings"))
        self.assertNotContains(response, "Operating locations")
        self.assertNotEqual(
            self.client.get(reverse("logistics_location_settings")).status_code, 200
        )
        with self.assertRaises(PermissionDenied):
            save_location(
                business=self.service,
                actor=self.user,
                name="Not allowed",
                code="SERVICE",
                country_code="US",
                location_type="HUB",
            )
