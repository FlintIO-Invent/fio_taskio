"""Catalogue presentation contracts against a verified disposable PostgreSQL DB."""

import os
import re
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.businesses.models import Business, BusinessSubscription, ClarivoPlan
from apps.businesses.test_service_allowances import ServicesFixture
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.forms import BusinessServiceForm
from apps.crm.models import BusinessService, ServiceCategory
from apps.crm.test_services_dashboard_ui import assert_disposable


class Fields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.names = set()
        self.in_form = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and "data-catalogue-form" in a:
            self.in_form = True
        if self.in_form and tag in {"input", "select", "textarea"} and a.get("name"):
            self.names.add(a["name"])

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False


class CataloguePresentationTests(ServicesFixture, TestCase):
    def setUp(self):
        assert_disposable()
        super().setUp()
        self.login()

    def values(self, **changes):
        result = {
            "name": "Native catalogue service",
            "unit_price": "88.75",
            "tax_rate": "",
            "is_active": "on",
            "is_bookable_online": "on",
            "default_duration_minutes": "45",
            "booking_buffer_minutes": "10",
            "requires_manual_confirmation": "on",
            "public_description": "A public description",
            "description": "Internal description",
            "external_code": "CAT-NATIVE",
        }
        result.update(changes)
        return result

    def test_form_preserves_complete_bound_fields_and_errors(self):
        response = self.client.get(reverse("business_service_create"))
        fields = Fields()
        fields.feed(response.content.decode())
        self.assertEqual(
            fields.names,
            set(BusinessServiceForm(business=self.business).fields) | {"csrfmiddlewaretoken"},
        )
        before = BusinessService.objects.count()
        invalid = self.client.post(reverse("business_service_create"), self.values(unit_price="-4"))
        self.assertContains(invalid, "Price cannot be negative.")
        self.assertContains(invalid, 'value="Native catalogue service"')
        self.assertEqual(BusinessService.objects.count(), before)

    def test_native_create_edit_and_soft_archive_preserve_tax_and_category(self):
        self.business.tax_rate = Decimal("6.50")
        self.business.save(update_fields=["tax_rate"])
        response = self.client.post(
            reverse("business_service_create"), self.values(new_category_name="Native new category")
        )
        self.assertRedirects(response, reverse("business_service_list"))
        service = BusinessService.objects.get(external_code="CAT-NATIVE")
        self.assertEqual(service.category.business_id, self.business.pk)
        self.assertEqual(service.tax_rate, Decimal("6.50"))
        self.assertEqual(service.default_duration_minutes, 45)
        response = self.client.post(
            reverse("business_service_update", args=[service.pk]),
            self.values(category=service.category_id, unit_price="90.00"),
        )
        self.assertRedirects(response, reverse("business_service_list"))
        service.refresh_from_db()
        self.assertEqual(service.tax_rate, Decimal("6.50"))
        self.assertEqual(
            self.client.get(reverse("business_service_archive", args=[service.pk])).status_code, 405
        )
        self.client.post(reverse("business_service_archive", args=[service.pk]))
        service.refresh_from_db()
        self.assertFalse(service.is_active)
        self.assertEqual(service.category.name, "Native new category")

    def test_category_conflict_keeps_draft_and_does_not_write(self):
        category = ServiceCategory.objects.create(business=self.business, name="Existing")
        before = ServiceCategory.objects.count()
        response = self.client.post(
            reverse("business_service_create"),
            self.values(category=category.pk, new_category_name="Conflicting"),
        )
        self.assertContains(
            response, "Choose an existing category or enter a new category, not both."
        )
        self.assertEqual(ServiceCategory.objects.count(), before)
        self.assertFalse(BusinessService.objects.filter(external_code="CAT-NATIVE").exists())

    def test_foreign_service_and_category_never_cross_tenant(self):
        other = Business.objects.create(name="Other", slug="catalogue-other")
        BusinessSubscription.objects.create(
            business=other, plan=self.plan, status="active", payment_provider="local"
        )
        foreign = BusinessService.objects.create(
            business=other, name="Foreign record", unit_price=42
        )
        category = ServiceCategory.objects.create(business=other, name="Foreign category")
        self.assertNotContains(self.client.get(reverse("business_service_list")), "Foreign record")
        self.assertEqual(
            self.client.get(reverse("business_service_update", args=[foreign.pk])).status_code, 404
        )
        self.client.post(reverse("business_service_create"), self.values(category=category.pk))
        self.assertFalse(BusinessService.objects.filter(external_code="CAT-NATIVE").exists())

    def test_csrf_is_required_and_get_does_not_archive(self):
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        session = guarded.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.assertEqual(
            guarded.post(reverse("business_service_archive", args=[self.service.pk])).status_code,
            403,
        )
        self.service.refresh_from_db()
        self.assertTrue(self.service.is_active)

    def test_roles_keep_server_management_boundary(self):
        for role in ["owner", "admin", "staff", "accountant", "viewer"]:
            self.member.role = role
            self.member.save(update_fields=["role"])
            response = self.client.get(reverse("business_service_list"))
            if role in {"owner", "admin"}:
                self.assertContains(response, "mm-services-catalogue")
            else:
                self.assertEqual(response.status_code, 302)

    def test_verified_grace_expiry_allows_read_but_blocks_catalogue_mutation(self):
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        sub = self.subscription
        sub.plan = ClarivoPlan.objects.get(slug="starter")
        sub.status = "past_due"
        sub.payment_provider = "stripe"
        sub.billing_currency = "usd"
        sub.billing_interval = "monthly"
        sub.provider_customer_id = "cus_cataloguefixture"
        sub.provider_subscription_id = "sub_cataloguefixture"
        sub.provider_price_id = "price_cataloguefixture"
        sub.past_due_since = now - timedelta(days=8)
        sub.grace_period_ends_at = now - timedelta(days=1)
        sub.save()
        self.assertEqual(sub.effective_access_state.code, "past_due_grace_expired")
        response = self.client.get(reverse("business_service_list"))
        self.assertContains(response, "mm-services-catalogue")
        self.assertContains(response, "Read-only")
        count = BusinessService.objects.count()
        self.client.post(reverse("business_service_create"), self.values())
        self.assertEqual(BusinessService.objects.count(), count)

    def test_logistics_fallback_renders_identically_to_frozen_before(self):
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        self.business.vertical = "LOGISTICS"
        self.business.save(update_fields=["vertical"])
        self.subscription.plan = plan
        self.subscription.billing_interval = "yearly"
        self.subscription.save()
        before = Path(os.environ["SERVICES_CATALOGUE_BEFORE"]) / "src/templates"
        templates = [
            {**settings.TEMPLATES[0], "DIRS": [str(before), *settings.TEMPLATES[0]["DIRS"]]}
        ]

        def clean(value):
            tokens = re.sub(
                r'name="csrfmiddlewaretoken" value="[^"]+"',
                'name="csrfmiddlewaretoken" value="NORMALIZED"',
                value.decode(),
            )
            return re.sub(r">\s+<", "><", tokens).strip()

        for route, args in [
            ("business_service_list", []),
            ("business_service_create", []),
            ("business_service_update", [self.service.pk]),
            ("business_service_category_create", []),
        ]:
            with self.subTest(route=route):
                current = self.client.get(reverse(route, args=args))
                with override_settings(TEMPLATES=templates):
                    original = self.client.get(reverse(route, args=args))
                self.assertEqual(current.status_code, 200)
                self.assertNotContains(current, "services-catalogue.css")
                self.assertEqual(clean(current.content), clean(original.content))
