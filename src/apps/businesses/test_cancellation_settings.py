"""Tenant-owned fixed cancellation fees reuse the existing settings permissions."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.logistics import test_cancellation_settlement as fixtures

from .forms import BusinessSettingsForm
from .utils import CURRENT_BUSINESS_SESSION_KEY


class CancellationServiceChargeSettingsTests(TestCase):
    setUp = fixtures.CancellationSettlementTests.setUp

    def data(self):
        form = self.client.get(reverse("business_settings")).context["form"]
        return {
            name: form[name].value() if form[name].value() is not None else ""
            for name in form.fields
        } | {"country": "US"}

    def test_owner_and_admin_can_save_fee_only_for_active_business(self):
        for role, fee in (("owner", "12.50"), ("admin", "20.00")):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            data = self.data() | {"cancellation_service_charge": fee, "business_id": self.other.pk}
            self.assertRedirects(
                self.client.post(reverse("business_settings"), data), reverse("business_settings")
            )
            self.business.refresh_from_db()
            self.other.refresh_from_db()
            self.assertEqual(self.business.cancellation_service_charge, Decimal(fee))
            self.assertEqual(self.other.cancellation_service_charge, 0)

    def test_negative_fee_is_invalid_and_older_forms_preserve_fee(self):
        data = self.data()
        response = self.client.post(
            reverse("business_settings"), data | {"cancellation_service_charge": "-1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("cancellation_service_charge", response.context["form"].errors)
        self.business.cancellation_service_charge = Decimal("10")
        self.business.save(update_fields=["cancellation_service_charge"])
        data.pop("cancellation_service_charge")
        self.assertRedirects(
            self.client.post(reverse("business_settings"), data), reverse("business_settings")
        )
        self.business.refresh_from_db()
        self.assertEqual(self.business.cancellation_service_charge, 10)

    def test_accountant_staff_and_viewer_cannot_change_global_fee(self):
        for role in ("accountant", "staff", "viewer"):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            response = self.client.post(
                reverse("business_settings"), {"cancellation_service_charge": "10"}
            )
            self.assertEqual(response.status_code, 403)
        self.business.refresh_from_db()
        self.assertEqual(self.business.cancellation_service_charge, 0)

    def test_service_workspace_keeps_existing_settings_fields(self):
        self.assertNotIn(
            "cancellation_service_charge", BusinessSettingsForm(instance=self.service).fields
        )
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.service.pk
        session.save()
        data = self.data() | {"cancellation_service_charge": "10"}
        self.assertRedirects(
            self.client.post(reverse("business_settings"), data), reverse("business_settings")
        )
        self.service.refresh_from_db()
        self.assertEqual(self.service.cancellation_service_charge, 0)
