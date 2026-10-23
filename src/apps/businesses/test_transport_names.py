from django.test import Client, TestCase
from django.urls import reverse

from apps.logistics import test_registration_changes as fixtures
from apps.logistics.forms import ParcelRegistrationForm
from apps.logistics.models import LogisticsProfile
from apps.logistics.shipment_forms import ShipmentForm

from .models import BusinessSubscription, BusinessUser
from .utils import CURRENT_BUSINESS_SESSION_KEY


class LogisticsTransportNameSettingsTests(TestCase):
    setUp = fixtures.ReusableLogisticsDefaultsTests.setUp
    parcel = fixtures.ReusableLogisticsDefaultsTests.parcel
    shipment = fixtures.ReusableLogisticsDefaultsTests.shipment

    def post(self, action="add", **data):
        return self.client.post(
            reverse("business_settings"),
            {"section": "logistics_transport", "action": action, **data},
        )

    def add(self, carrier="", vessel="", **data):
        return self.post(
            **{"transport-carrier_name": carrier, "transport-vessel_name": vessel, **data}
        )

    def saved(self, response):
        self.assertRedirects(response, f"{reverse('business_settings')}#logistics-defaults")

    def test_add_either_or_both_names_persists_only_for_current_business(self):
        self.saved(self.add(carrier="  Carrier One  ", business_id=self.other.pk, currency="EUR"))
        self.membership.role = BusinessUser.Role.ADMIN
        self.membership.save(update_fields=["role"])
        self.saved(self.add(vessel="MV One"))
        self.saved(self.add(carrier="Carrier Two", vessel="MV Two"))
        self.business.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.business.logistics_carrier_names, "Carrier One\nCarrier Two")
        self.assertEqual(self.business.logistics_vessel_names, "MV One\nMV Two")
        self.assertEqual(self.business.currency, "USD")
        self.assertEqual(self.other.logistics_carrier_names, "")
        self.assertEqual(self.other.logistics_vessel_names, "")
        shipment_form = ShipmentForm(business=self.business, actor=self.user)
        self.assertIn(
            ("Carrier Two", "Carrier Two"), shipment_form.fields["carrier_name"].widget.choices
        )
        parcel_form = ParcelRegistrationForm(business=self.business, actor=self.user)
        self.assertIn(("MV Two", "MV Two"), parcel_form.fields["vessel_name"].widget.choices)

    def test_validation_is_atomic_and_retains_submitted_values(self):
        self.saved(self.add(carrier="Carrier One"))
        for carrier, vessel, field in (
            ("", "", None),
            ("carrier ONE", "MV Valid", "carrier_name"),
            ("Carrier\nTwo", "", "carrier_name"),
            ("", "X" * 161, "vessel_name"),
        ):
            with self.subTest(carrier=carrier, field=field):
                response = self.add(carrier=carrier, vessel=vessel)
                self.assertEqual(response.status_code, 200)
                form = response.context["transport_form"]
                self.assertIn(field or "__all__", form.errors)
                self.assertEqual(form["vessel_name"].value(), vessel)
        self.business.refresh_from_db()
        self.assertEqual(self.business.logistics_carrier_names, "Carrier One")
        self.assertEqual(self.business.logistics_vessel_names, "")
        self.business.logistics_vessel_names = "\n".join(f"MV {i}" for i in range(100))
        self.business.save(update_fields=["logistics_vessel_names"])
        self.assertIn(
            "vessel_name", self.add(vessel="MV Overflow").context["transport_form"].errors
        )

    def test_default_clear_and_remove_preserve_historical_records(self):
        LogisticsProfile.objects.get_or_create(
            business=self.business, defaults={"transportation_modes": ["SEA"]}
        )
        parcel = self.parcel(mode_of_transport="SEA", vessel_name="MV One")
        shipment = self.shipment(
            transport_mode="SEA", vessel_name="MV One", carrier_name="Carrier One"
        )
        self.saved(self.add(carrier="Carrier One", vessel="MV One"))
        for kind, name in (("carrier", "Carrier One"), ("vessel", "MV One")):
            self.saved(self.post("default", kind=kind, name=name))
        self.business.refresh_from_db()
        self.assertEqual(self.business.logistics_default_vessel, "MV One")
        self.assertEqual(self.business.logistics_default_carrier, "Carrier One")
        self.assertEqual(
            ShipmentForm(business=self.business, actor=self.user)["carrier_name"].value(),
            "Carrier One",
        )
        self.saved(self.post("clear_default", kind="carrier", name="Carrier One"))
        self.saved(self.post("remove", kind="vessel", name="MV One"))
        self.business.refresh_from_db()
        self.assertEqual(self.business.logistics_vessel_names, "")
        self.assertEqual(self.business.logistics_default_vessel, "")
        self.assertEqual(self.business.logistics_carrier_names, "Carrier One")
        self.assertEqual(self.business.logistics_default_carrier, "")
        parcel.refresh_from_db()
        shipment.refresh_from_db()
        self.assertEqual(parcel.vessel_name, "MV One")
        self.assertEqual((shipment.vessel_name, shipment.carrier_name), ("MV One", "Carrier One"))
        self.assertIn(
            ("MV One", "MV One"),
            ShipmentForm(business=self.business, actor=self.user, instance=shipment)
            .fields["vessel_name"]
            .widget.choices,
        )

    def test_actions_reject_unknown_foreign_and_stale_names(self):
        self.saved(self.add(vessel="MV One"))
        self.other.logistics_vessel_names = "Foreign vessel"
        self.other.save(update_fields=["logistics_vessel_names"])
        for action, kind, name in (
            ("default", "vessel", "Foreign vessel"),
            ("remove", "vessel", "Unknown"),
            ("clear_default", "vessel", "MV One"),
            ("default", "invalid", "MV One"),
            ("invalid", "vessel", "MV One"),
        ):
            response = self.post(action, kind=kind, name=name)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["transport_action_form"].errors)
        self.business.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.business.logistics_vessel_names, "MV One")
        self.assertEqual(self.business.logistics_default_vessel, "")
        self.assertEqual(self.other.logistics_vessel_names, "Foreign vessel")

    def test_roles_service_and_restricted_workspaces_cannot_write(self):
        for role in ("staff", "viewer", "accountant"):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            self.assertNotContains(
                self.client.get(reverse("business_settings")), 'id="transport-name-form"'
            )
            self.assertEqual(self.add(vessel="Forbidden").status_code, 403)
            self.assertEqual(self.post("default", kind="vessel", name="Forbidden").status_code, 403)
        self.membership.role = BusinessUser.Role.OWNER
        self.membership.save(update_fields=["role"])
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.service.pk
        session.save()
        self.assertNotContains(
            self.client.get(reverse("business_settings")), 'id="transport-name-form"'
        )
        self.assertEqual(self.add(vessel="Forbidden").status_code, 403)
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        BusinessSubscription.objects.filter(business=self.business).update(status="cancelled")
        self.assertEqual(self.add(vessel="Forbidden").status_code, 302)
        self.business.refresh_from_db()
        self.assertEqual(self.business.logistics_vessel_names, "")
        self.client.logout()
        self.assertEqual(self.add(vessel="Forbidden").status_code, 302)

    def test_old_names_display_and_ordinary_business_save_preserves_names(self):
        self.business.logistics_vessel_names = "MV Existing"
        self.business.logistics_default_vessel = "MV Existing"
        self.business.save(update_fields=["logistics_vessel_names", "logistics_default_vessel"])
        response = self.client.get(reverse("business_settings"))
        self.assertContains(response, "MV Existing")
        self.assertContains(response, "Clear default")
        self.assertNotContains(response, '<textarea name="logistics_vessel_names"')
        form = response.context["form"]
        data = {
            name: form[name].value() if form[name].value() is not None else ""
            for name in form.fields
            if not name.startswith("logistics_")
        } | {"country": "US", "name": "Updated business"}
        self.assertRedirects(
            self.client.post(reverse("business_settings"), data), reverse("business_settings")
        )
        self.business.refresh_from_db()
        self.assertEqual(self.business.logistics_vessel_names, "MV Existing")
        self.assertEqual(self.business.logistics_default_vessel, "MV Existing")

    def test_add_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(
            client.post(
                reverse("business_settings"),
                {
                    "section": "logistics_transport",
                    "action": "add",
                    "transport-vessel_name": "Forbidden",
                },
            ).status_code,
            403,
        )
