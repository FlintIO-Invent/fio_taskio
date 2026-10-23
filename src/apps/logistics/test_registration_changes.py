"""Permission separation, explicit decisions and snapshot-safe business suggestions."""

import uuid
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.billings.models import Invoice, InvoicePayment
from apps.businesses.forms import BusinessSettingsForm
from apps.businesses.models import BusinessUser

from . import test_billing, test_location_operations, test_parcels, test_registration
from .billing_forms import LogisticsChargeForm
from .billing_services import add_charge
from .forms import ParcelRegistrationForm
from .models import LogisticsProfile
from .shipment_forms import ShipmentForm
from .shipment_services import (
    change_shipment_status,
    create_shipment,
    remove_parcel,
    update_shipment,
)


class ShipmentStaffVisibilityTests(TestCase):
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    setUp = test_location_operations.LocationOperationsTests.setUp
    select = test_location_operations.LocationOperationsTests.select
    parcel = test_location_operations.LocationOperationsTests.parcel
    ship = test_location_operations.LocationOperationsTests.ship

    def test_staff_read_mutation_denials_and_registration_assignment(self):
        shipment = self.ship()
        foreign = create_shipment(
            business=self.other, actor=self.other_user, origin="X", destination="Y"
        )
        self.client.force_login(self.staff)
        self.assertNotContains(
            self.client.get(reverse("logistics_parcel_detail", args=[self.item.pk])),
            reverse("logistics_shipment_create"),
        )
        self.assertContains(self.client.get(reverse("logistics_shipment_list")), shipment.reference)
        detail = reverse("logistics_shipment_detail", args=[shipment.pk])
        response = self.client.get(detail)
        self.assertContains(response, shipment.reference)
        self.assertNotContains(
            response, 'action="' + reverse("logistics_shipment_status", args=[shipment.pk]) + '"'
        )
        self.assertNotContains(
            response, 'href="' + reverse("logistics_shipment_edit", args=[shipment.pk]) + '"'
        )
        self.assertEqual(
            self.client.get(reverse("logistics_shipment_manifest", args=[shipment.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("logistics_shipment_detail", args=[foreign.pk])).status_code,
            404,
        )
        for name, args in (
            ("logistics_shipment_create", []),
            ("logistics_shipment_edit", [shipment.pk]),
            ("logistics_shipment_status", [shipment.pk]),
            ("logistics_shipment_remove", [shipment.pk, self.item.pk]),
        ):
            self.assertEqual(self.client.post(reverse(name, args=args), {}).status_code, 403, name)
        for operation, fields in (
            (create_shipment, {"origin": "X", "destination": "Y"}),
            (update_shipment, {"shipment": shipment, "notes": "forbidden"}),
            (change_shipment_status, {"shipment": shipment, "status": "CANCELLED"}),
            (remove_parcel, {"shipment": shipment, "parcel": self.item}),
        ):
            with self.assertRaises(PermissionDenied):
                operation(business=self.business, actor=self.staff, **fields)
        url = reverse("logistics_parcel_registration", args=[self.item.pk])
        response = self.client.get(url)
        self.assertTrue(response.context["can_assign"])
        self.assertNotContains(response, "Create Shipment with this Parcel")
        data = {
            "action": "assign",
            "shipment": shipment.pk,
            "expected_revision": shipment.revision,
            "idempotency_key": uuid.uuid4(),
        }
        for _ in range(2):
            self.assertEqual(self.client.post(url, data).status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.shipment_id, shipment.pk)
        shipment.refresh_from_db()
        self.assertEqual(len(shipment.operation_history), 2)  # creation, assignment
        self.assertEqual(self.client.post(url, {**data, "shipment": foreign.pk}).status_code, 404)

    def test_unassigned_or_other_location_staff_cannot_read_shipment(self):
        shipment = self.ship()
        self.client.force_login(self.staff)
        self.member.logistics_location_assignments.exclude(location=self.unrelated).delete()
        url = reverse("logistics_shipment_detail", args=[shipment.pk])
        self.assertEqual(self.client.get(url).status_code, 404)


class ExplicitPaymentDecisionTests(TestCase):
    setUp = test_registration.ParcelRegistrationTests.setUp
    parcel = test_registration.ParcelRegistrationTests.parcel
    charge = test_registration.ParcelRegistrationTests.charge
    bill = test_registration.ParcelRegistrationTests.bill
    issue = test_registration.ParcelRegistrationTests.issue
    pay = test_registration.ParcelRegistrationTests.pay
    url = test_registration.ParcelRegistrationTests.url

    def prepare(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.issue(invoice)
        return parcel, invoice

    def test_no_default_unpaid_preserves_balance_and_saved_choice(self):
        parcel, invoice = self.prepare()
        page = self.client.get(self.url(parcel))
        self.assertEqual(page.context["resume_step"], "registration-payment")
        self.assertIsNone(page.context["payment_decision_form"]["decision"].value())
        for value in ("", "other"):
            response = self.pay(parcel, invoice, decision=value)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Select paid or unpaid") if not value else None
            self.assertEqual(InvoicePayment.objects.count(), 0)
        for _ in range(2):
            response = self.client.post(
                self.url(parcel), {"action": "payment", "decision": "unpaid"}
            )
            self.assertRedirects(response, self.url(parcel) + "#registration-shipment")
        page = self.client.get(self.url(parcel))
        self.assertEqual(page.context["payment_decision_form"]["decision"].value(), "unpaid")
        self.assertEqual(page.context["resume_step"], "registration-shipment")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "SENT")
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(InvoicePayment.objects.count(), 0)

    def test_paid_requires_details_preserves_errors_and_replays_once(self):
        parcel, invoice = self.prepare()
        self.client.post(self.url(parcel), {"action": "payment", "decision": "unpaid"})
        response = self.pay(parcel, invoice, amount="", method="")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["payment_decision_form"]["decision"].value(), "paid")
        self.assertIn("amount", response.context["payment_form"].errors)
        self.assertIn("method", response.context["payment_form"].errors)
        self.assertFalse(response.context["payment_decision_complete"])
        key = uuid.uuid4()
        for _ in range(2):
            self.assertRedirects(
                self.pay(parcel, invoice, idempotency_key=key),
                self.url(parcel) + "#registration-shipment",
            )
        self.assertEqual(InvoicePayment.objects.count(), 1)
        self.assertEqual(Invoice.objects.count(), 1)
        page = self.client.get(self.url(parcel))
        self.assertEqual(page.context["payment_decision_form"]["decision"].value(), "paid")

    def test_paid_without_invoice_is_validation_error_unpaid_has_no_writes(self):
        parcel = self.parcel()
        response = self.client.post(self.url(parcel), {"action": "payment", "decision": "paid"})
        self.assertContains(response, "Create and issue an Invoice")
        self.assertRedirects(
            self.client.post(self.url(parcel), {"action": "payment", "decision": "unpaid"}),
            self.url(parcel) + "#registration-shipment",
        )
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(InvoicePayment.objects.count(), 0)


class ReusableLogisticsDefaultsTests(TestCase):
    setUp = test_billing.LogisticsBillingTests.setUp
    parcel = test_billing.LogisticsBillingTests.parcel
    shipment = test_billing.LogisticsBillingTests.shipment
    saved_service = test_billing.LogisticsBillingTests.saved_service
    bill = test_billing.LogisticsBillingTests.bill

    def data(self):
        form = BusinessSettingsForm(instance=self.business)
        return {
            name: form[name].value() if form[name].value() is not None else ""
            for name in form.fields
        } | {"country": "US"}

    def test_configuration_permissions_scope_and_validation(self):
        data = self.data() | {
            "logistics_vessel_names": "MV One\nMV Two\nMV One",
            "logistics_default_vessel": "MV One",
            "logistics_carrier_names": "Carrier One",
            "logistics_default_carrier": "Carrier One",
            "business_id": self.other.pk,
        }
        for role in ("owner", "admin"):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            self.assertRedirects(
                self.client.post(reverse("business_settings"), data), reverse("business_settings")
            )
        self.business.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.business.logistics_vessel_names, "MV One\nMV Two")
        self.assertEqual(self.other.logistics_vessel_names, "")
        form = BusinessSettingsForm(
            data | {"logistics_default_vessel": "Unknown"}, instance=self.business
        )
        self.assertFalse(form.is_valid())
        self.assertIn("logistics_default_vessel", form.errors)
        for role in ("staff", "viewer", "accountant"):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            self.assertEqual(self.client.post(reverse("business_settings"), data).status_code, 403)
        self.assertNotIn(
            "logistics_vessel_names", BusinessSettingsForm(instance=self.service).fields
        )

    def test_options_defaults_and_historical_transport_and_charges_are_preserved(self):
        LogisticsProfile.objects.get_or_create(
            business=self.business, defaults={"transportation_modes": ["SEA"]}
        )
        shipment = self.shipment(
            transport_mode="SEA", vessel_name="Historical vessel", carrier_name="Historical carrier"
        )
        parcel = self.parcel(mode_of_transport="SEA", vessel_name="Historical vessel")
        service = self.saved_service(description="Handling snapshot", tax_rate=Decimal("5"))
        charge = add_charge(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            service=service,
            idempotency_key=uuid.uuid4(),
        )
        invoice = self.bill(charge)
        before_charge = dict(type(charge).objects.filter(pk=charge.pk).values().get())
        before_line = list(invoice.lines.values())
        self.business.logistics_vessel_names = "MV New"
        self.business.logistics_carrier_names = "Carrier New"
        self.business.logistics_default_vessel = "MV New"
        self.business.logistics_default_carrier = "Carrier New"
        self.business.save()
        LogisticsProfile.objects.filter(business=self.business).update(transportation_modes=["SEA"])
        form = ShipmentForm(business=self.business, actor=self.user)
        self.assertEqual(form["vessel_name"].value(), "MV New")
        self.assertEqual(form["carrier_name"].value(), "Carrier New")
        self.assertIn(("MV New", "MV New"), list(form.fields["vessel_name"].widget.choices))
        form = ShipmentForm(business=self.business, actor=self.user, instance=shipment)
        self.assertEqual(form["vessel_name"].value(), "Historical vessel")
        self.assertIn(
            ("Historical vessel", "Historical vessel"),
            list(form.fields["vessel_name"].widget.choices),
        )
        form = ParcelRegistrationForm(business=self.business, actor=self.user)
        self.assertEqual(form["vessel_name"].value(), "MV New")
        foreign = self.saved_service(business=self.other)
        choices = LogisticsChargeForm(business=self.business).fields["service"].queryset
        self.assertIn(service, choices)
        self.assertNotIn(foreign, choices)
        service.description = "Updated description"
        service.unit_price = 999
        service.tax_rate = 20
        service.save()
        self.assertEqual(type(charge).objects.filter(pk=charge.pk).values().get(), before_charge)
        self.assertEqual(list(invoice.lines.values()), before_line)
        parcel.refresh_from_db()
        self.assertEqual(parcel.vessel_name, "Historical vessel")
        self.membership.role = BusinessUser.Role.STAFF
        self.membership.save(update_fields=["role"])
        # Suggestions carry no configuration permission and are still available to operators.
        self.assertEqual(
            ShipmentForm(business=self.business, actor=self.user)["carrier_name"].value(),
            "Carrier New",
        )


class TransportDefaultsMigrationTests(TransactionTestCase):
    serialized_rollback = True
    setUp = test_billing.LogisticsBillingTests.setUp
    parcel = test_billing.LogisticsBillingTests.parcel
    shipment = test_billing.LogisticsBillingTests.shipment
    bill = test_billing.LogisticsBillingTests.bill

    def test_additive_migration_preserves_existing_operational_and_financial_records(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        from .models import LogisticsCharge, Parcel, ParcelEvent, Shipment

        parcel = self.parcel()
        self.shipment()
        charge = add_charge(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            description="Historical fee",
            unit_price=25,
            idempotency_key=uuid.uuid4(),
        )
        self.bill(charge)
        models = (Parcel, ParcelEvent, Shipment, LogisticsCharge, Invoice)
        snapshots = {model: list(model.objects.order_by("pk").values()) for model in models}
        executor = MigrationExecutor(connection)
        previous = [("businesses", "0033_business_cancellation_service_charge")]
        target = [("businesses", "0034_logistics_transport_defaults")]
        try:
            executor.migrate(previous)
            historical = executor.loader.project_state(previous).apps.get_model(
                "businesses", "Business"
            )
            business = historical.objects.get(pk=self.business.pk)
            self.assertEqual(business.name, self.business.name)
            self.assertEqual(business.currency, self.business.currency)
        finally:
            MigrationExecutor(connection).migrate(target)
        self.business.refresh_from_db()
        self.assertEqual(self.business.logistics_vessel_names, "")
        self.assertEqual(self.business.logistics_default_carrier, "")
        for model, rows in snapshots.items():
            self.assertEqual(list(model.objects.order_by("pk").values()), rows)
