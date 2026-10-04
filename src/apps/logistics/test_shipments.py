from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db.models import QuerySet
from django.test import Client as WebClient
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.business_data_inventory import (
    build_business_data_inventory,
    find_unregistered_direct_business_relations,
)
from apps.businesses.business_data_purge import (
    PURGE_DELETION_ORDER,
    BusinessPurgeError,
    plan_business_purge,
    purge_business,
)
from apps.businesses.models import (
    Business,
    BusinessDataOperation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
)
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client

from .admin import ShipmentAdmin
from .models import Parcel, Shipment
from .parcel_services import change_parcel_status, register_parcel
from .shipment_policy import ALLOWED_TRANSITIONS
from .shipment_services import (
    assign_parcel,
    change_shipment_status,
    create_shipment,
    generate_manifest,
    remove_parcel,
    shipments_for_business,
    update_shipment,
)


class ShipmentTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Courier", slug="ship-courier", vertical="LOGISTICS"
        )
        self.other = Business.objects.create(name="Other", slug="ship-other", vertical="LOGISTICS")
        self.service = Business.objects.create(name="Service", slug="ship-service")
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        for business in (self.business, self.other, self.service):
            BusinessSubscription.objects.create(
                business=business,
                plan=plan if business != self.service else ClarivoPlan.objects.get(slug="pro"),
                status="active",
                billing_interval="yearly",
            )
        self.user = TaskIOUser.objects.create_user(email="ship@example.com", password="testpass123")
        self.other_user = TaskIOUser.objects.create_user(
            email="ship-other@example.com", password="testpass123"
        )
        self.membership = BusinessUser.objects.create(
            business=self.business, user=self.user, role="owner"
        )
        BusinessUser.objects.create(business=self.other, user=self.other_user, role="owner")
        BusinessUser.objects.create(business=self.service, user=self.user, role="owner")
        self.customer = Client.objects.create(
            business=self.business,
            first_name="Parcel",
            last_name="Customer",
            email="private@example.com",
            phone="PRIVATE-PHONE",
            street_address="PRIVATE-ADDRESS",
            notes="PRIVATE-NOTES",
            communication_notes="PRIVATE-COMMS",
            registration_number="PRIVATE-REGISTRATION",
        )
        self.other_customer = Client.objects.create(
            business=self.other, first_name="Other", last_name="Client"
        )
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()

    def shipment(self, **fields):
        return create_shipment(
            business=self.business,
            actor=self.user,
            **{"origin": "Miami", "destination": "Curacao", **fields},
        )

    def parcel(self, **fields):
        return register_parcel(
            business=self.business,
            client=self.customer,
            actor=self.user,
            **{
                "origin": "Miami",
                "destination": "Curacao",
                "package_description": "Books",
                **fields,
            },
        )

    def parcel_status(self, parcel, status):
        return change_parcel_status(
            business=self.business, parcel=parcel, actor=self.user, status=status
        )

    def status(self, shipment, status, **kwargs):
        return change_shipment_status(
            business=self.business, shipment=shipment, actor=self.user, status=status, **kwargs
        )

    def assign(self, shipment, parcel):
        return assign_parcel(
            business=self.business, shipment=shipment, parcel=parcel, actor=self.user
        )

    def remove(self, shipment, parcel):
        return remove_parcel(
            business=self.business, shipment=shipment, parcel=parcel, actor=self.user
        )

    def manifest(self, shipment):
        return generate_manifest(business=self.business, shipment=shipment, actor=self.user)

    def ready_shipment(self, count=1):
        shipment = self.shipment()
        parcels = [self.parcel() for _ in range(count)]
        for parcel in parcels:
            self.parcel_status(parcel, "RECEIVED")
            self.assign(shipment, parcel)
        self.status(shipment, "READY")
        return shipment, parcels

    def test_logistics_creation_and_immutable_reference(self):
        first, second = self.shipment(), self.shipment()
        self.assertEqual(first.status, "DRAFT")
        self.assertEqual(first.created_by, self.user)
        self.assertEqual(first.business, self.business)
        self.assertNotEqual(first.reference, second.reference)
        self.assertTrue(first.reference.startswith("SHP-"))
        changed = update_shipment(
            business=self.business, shipment=first, actor=self.user, origin="Orlando"
        )
        self.assertEqual(changed.origin, "Orlando")
        self.assertEqual(changed.reference, first.reference)
        for fields in ({"created_by": self.other_user}, {"reference": "NEW"}, {"status": "READY"}):
            with self.assertRaises(ValidationError):
                update_shipment(business=self.business, shipment=first, actor=self.user, **fields)
        with self.assertRaises(ValidationError):
            self.shipment(
                departure_at=timezone.now(), estimated_arrival_at=timezone.now() - timedelta(days=1)
            )

    def test_service_vertical_rejected_in_services_and_every_ui_route(self):
        shipment = self.shipment()
        parcel = self.parcel()
        for operation, kwargs in (
            (create_shipment, {"origin": "Miami", "destination": "Curacao"}),
            (update_shipment, {"shipment": shipment, "origin": "Other"}),
            (assign_parcel, {"shipment": shipment, "parcel": parcel}),
            (remove_parcel, {"shipment": shipment, "parcel": parcel}),
            (change_shipment_status, {"shipment": shipment, "status": "READY"}),
            (generate_manifest, {"shipment": shipment}),
            (shipments_for_business, {}),
        ):
            with self.subTest(operation=operation.__name__), self.assertRaises(PermissionDenied):
                operation(business=self.service, actor=self.user, **kwargs)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.service.pk
        session.save()
        for route, args, method in self.routes(shipment, parcel):
            response = getattr(self.client, method)(
                reverse(route, args=args), HTTP_ACCEPT="application/json"
            )
            self.assertEqual(response.status_code, 403, route)

    @staticmethod
    def routes(shipment, parcel):
        return (
            ("logistics_shipment_list", [], "get"),
            ("logistics_shipment_create", [], "get"),
            ("logistics_shipment_detail", [shipment.pk], "get"),
            ("logistics_shipment_edit", [shipment.pk], "get"),
            ("logistics_shipment_assign", [shipment.pk], "post"),
            ("logistics_shipment_remove", [shipment.pk, parcel.pk], "post"),
            ("logistics_shipment_status", [shipment.pk], "post"),
            ("logistics_shipment_manifest", [shipment.pk], "get"),
        )

    def test_cross_tenant_objects_and_stale_ownership_rejected(self):
        shipment, parcel = self.shipment(), self.parcel()
        foreign = create_shipment(
            business=self.other, actor=self.other_user, origin="Other", destination="Elsewhere"
        )
        foreign_parcel = register_parcel(
            business=self.other,
            client=self.other_customer,
            actor=self.other_user,
            origin="Other",
            destination="Elsewhere",
            package_description="FOREIGN",
        )
        for group, item in ((shipment, foreign_parcel), (foreign, parcel)):
            with self.assertRaises(ValidationError):
                self.assign(group, item)
            with self.assertRaises(ValidationError):
                self.remove(group, item)
        for operation, kwargs in (
            (update_shipment, {}),
            (change_shipment_status, {"status": "CANCELLED"}),
            (generate_manifest, {}),
        ):
            with self.assertRaises(ValidationError):
                operation(business=self.business, actor=self.user, shipment=foreign, **kwargs)
        Client.objects.filter(pk=self.customer.pk).update(business=self.other)
        with self.assertRaises(ValidationError):
            self.assign(shipment, parcel)

    def test_duplicate_assignment_is_idempotent_and_move_requires_removal(self):
        first, second, parcel = self.shipment(), self.shipment(), self.parcel()
        self.assign(first, parcel)
        self.assign(first, parcel)
        self.assertEqual(first.parcels.count(), 1)
        self.assertEqual(parcel.events.count(), 1)
        with self.assertRaises(ValidationError):
            self.assign(second, parcel)
        with self.assertRaises(ValidationError):
            self.remove(second, parcel)
        self.remove(first, parcel)
        self.assign(second, parcel)
        parcel.refresh_from_db()
        self.assertEqual(parcel.shipment, second)
        self.assertFalse(first.parcels.exists())
        self.assertEqual(parcel.current_status, "REGISTERED")

    def test_assignment_to_ready_and_removal_before_departure(self):
        shipment, parcels = self.ready_shipment()
        extra = self.parcel()
        self.assign(shipment, extra)
        with self.assertRaises(ValidationError):
            self.status(shipment, "IN_TRANSIT")
        self.remove(shipment, extra)
        self.status(shipment, "IN_TRANSIT")
        for operation, parcel in ((self.assign, extra), (self.remove, parcels[0])):
            with self.assertRaises(ValidationError):
                operation(shipment, parcel)
        other = self.shipment()
        with self.assertRaises(ValidationError):
            self.assign(other, parcels[0])

    def test_terminal_and_advanced_parcels_cannot_be_assigned(self):
        shipment = self.shipment()
        for status in ("DELIVERED", "CANCELLED", "IN_TRANSIT", "ARRIVED", "READY", "HOLD"):
            parcel = self.parcel()
            if status == "CANCELLED":
                self.parcel_status(parcel, status)
            elif status == "HOLD":
                self.parcel_status(parcel, status)
            else:
                for step in ("RECEIVED", "IN_TRANSIT", "ARRIVED", "READY", "DELIVERED"):
                    self.parcel_status(parcel, step)
                    if step == status:
                        break
            with self.subTest(status=status), self.assertRaises(ValidationError):
                self.assign(shipment, parcel)

    def test_complete_lifecycle_records_existing_parcel_events(self):
        shipment, parcels = self.ready_shipment(count=2)
        from . import shipment_services

        with patch(
            "apps.logistics.shipment_services.change_parcel_status",
            wraps=shipment_services.change_parcel_status,
        ) as change:
            self.status(shipment, "IN_TRANSIT")
            self.status(shipment, "ARRIVED")
            self.assertEqual(change.call_count, 4)
        for parcel in parcels:
            parcel.refresh_from_db()
            self.assertEqual(parcel.current_status, "ARRIVED")
            self.assertEqual(
                list(parcel.events.values_list("status", flat=True)),
                ["REGISTERED", "RECEIVED", "IN_TRANSIT", "ARRIVED"],
            )
            self.assertTrue(
                parcel.events.filter(
                    status="IN_TRANSIT", actor=self.user, internal_note__contains=shipment.reference
                ).exists()
            )
        with self.assertRaises(ValidationError):
            self.status(shipment, "COMPLETED")
        for parcel in parcels:
            self.parcel_status(parcel, "READY")
            self.parcel_status(parcel, "DELIVERED")
        self.status(shipment, "COMPLETED")
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, "COMPLETED")
        self.assertEqual(shipment.parcels.count(), 2)

    def test_ready_can_return_to_draft_and_cancel_releases_parcels(self):
        shipment, parcels = self.ready_shipment()
        self.status(shipment, "DRAFT")
        self.status(shipment, "CANCELLED")
        parcels[0].refresh_from_db()
        self.assertIsNone(parcels[0].shipment_id)
        self.assertEqual(parcels[0].current_status, "RECEIVED")
        self.assertEqual(parcels[0].events.count(), 2)
        self.assign(self.shipment(), parcels[0])
        with self.assertRaises(ValidationError):
            self.assign(shipment, self.parcel())
        ready, items = self.ready_shipment()
        self.status(ready, "CANCELLED")
        items[0].refresh_from_db()
        self.assertIsNone(items[0].shipment_id)

    def test_invalid_transition_matrix_has_no_effects(self):
        shipment = self.shipment()
        for current, allowed in ALLOWED_TRANSITIONS.items():
            QuerySet(model=Shipment).filter(pk=shipment.pk).update(status=current)
            for target in [*Shipment.Status.values, "UNKNOWN"]:
                if target in allowed:
                    continue
                with (
                    self.subTest(current=current, target=target),
                    self.assertRaises(ValidationError),
                ):
                    self.status(shipment, target)
                shipment.refresh_from_db()
                self.assertEqual(shipment.status, current)

    def test_ready_departure_and_arrival_require_consistent_parcel_states(self):
        shipment = self.shipment()
        with self.assertRaises(ValidationError):
            self.status(shipment, "READY")
        parcel = self.parcel()
        self.assign(shipment, parcel)
        with self.assertRaises(ValidationError):
            self.status(shipment, "READY")
        self.parcel_status(parcel, "RECEIVED")
        self.status(shipment, "READY")
        self.parcel_status(parcel, "HOLD")
        with self.assertRaises(ValidationError):
            self.status(shipment, "IN_TRANSIT")
        self.parcel_status(parcel, "RECEIVED")
        self.status(shipment, "IN_TRANSIT")
        self.parcel_status(parcel, "HOLD")
        with self.assertRaises(ValidationError):
            self.status(shipment, "ARRIVED")
        self.parcel_status(parcel, "IN_TRANSIT")
        self.status(shipment, "ARRIVED")

    def test_status_and_edit_reload_persisted_status(self):
        shipment, _ = self.ready_shipment()
        self.assertEqual(shipment.status, "DRAFT")  # Caller holds an old instance.
        with self.assertRaises(ValidationError):
            update_shipment(
                business=self.business, shipment=shipment, actor=self.user, origin="Changed"
            )
        with self.assertRaises(ValidationError):
            self.status(shipment, "IN_TRANSIT", expected_status="DRAFT")
        self.status(shipment, "IN_TRANSIT", expected_status="READY")
        with self.assertRaises(ValidationError):
            self.status(shipment, "IN_TRANSIT", expected_status="READY")

    def test_departure_failure_rolls_back_all_events_and_statuses(self):
        shipment, parcels = self.ready_shipment(count=2)
        from . import shipment_services

        change = shipment_services.change_parcel_status
        calls = 0

        def fail_second(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValidationError("Event failure")
            return change(**kwargs)

        with patch(
            "apps.logistics.shipment_services.change_parcel_status", side_effect=fail_second
        ):
            with self.assertRaises(ValidationError):
                self.status(shipment, "IN_TRANSIT")
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, "READY")
        for parcel in parcels:
            parcel.refresh_from_db()
            self.assertEqual(parcel.current_status, "RECEIVED")
            self.assertEqual(parcel.events.count(), 2)

    def test_manifest_allowlist_totals_and_tenant_scope(self):
        shipment, other = self.shipment(notes="PRIVATE-SHIPMENT-NOTE"), self.shipment()
        first = self.parcel(
            quantity=2, weight_kg="1.500", declared_value="999", dimensions="PRIVATE-DIMENSIONS"
        )
        second = self.parcel(quantity=3)
        excluded = self.parcel(package_description="OTHER-SHIPMENT")
        self.assign(shipment, first)
        self.assign(shipment, second)
        self.assign(other, excluded)
        manifest = self.manifest(shipment)
        self.assertEqual(manifest["parcel_count"], 2)
        self.assertEqual(manifest["total_quantity"], 5)
        self.assertEqual(manifest["total_known_weight_kg"], Decimal("1.500"))
        self.assertEqual(manifest["unknown_weight_count"], 1)
        self.assertEqual(
            {row["tracking_code"] for row in manifest["parcels"]},
            {first.tracking_code, second.tracking_code},
        )
        self.assertEqual(manifest["parcels"][0]["client_name"], "Parcel Customer")
        for route in ("", "?download=csv"):
            response = self.client.get(
                reverse("logistics_shipment_manifest", args=[shipment.pk]) + route
            )
            self.assertEqual(response.status_code, 200)
            for private in (
                "private@example.com",
                "PRIVATE-PHONE",
                "PRIVATE-ADDRESS",
                "PRIVATE-NOTES",
                "PRIVATE-COMMS",
                "PRIVATE-REGISTRATION",
                "PRIVATE-SHIPMENT-NOTE",
                "PRIVATE-DIMENSIONS",
                "OTHER-SHIPMENT",
                excluded.tracking_code,
            ):
                self.assertNotContains(response, private)
            self.assertContains(response, first.tracking_code)
            self.assertIn("no-store", response["Cache-Control"])
            if route:
                self.assertIn("attachment", response["Content-Disposition"])

    def test_manifest_excludes_corrupt_foreign_parcel_and_foreign_client(self):
        shipment = self.shipment()
        local = self.parcel()
        self.assign(shipment, local)
        foreign = register_parcel(
            business=self.other,
            client=self.other_customer,
            actor=self.other_user,
            origin="Other",
            destination="Other",
            package_description="FOREIGN",
        )
        QuerySet(model=Parcel).filter(pk=foreign.pk).update(shipment=shipment)
        self.assertEqual(self.manifest(shipment)["parcel_count"], 1)
        with self.assertRaises(ValidationError):
            self.status(shipment, "CANCELLED")
        Client.objects.filter(pk=self.customer.pk).update(business=self.other)
        self.assertEqual(self.manifest(shipment)["parcel_count"], 0)

    def test_csv_formula_neutralization_and_html_escaping(self):
        shipment = self.shipment(origin="=FORMULA", destination="<script>destination</script>")
        parcel = self.parcel(package_description="=FORMULA")
        self.customer.first_name = "@FORMULA"
        self.customer.save(update_fields=["first_name"])
        self.assign(shipment, parcel)
        url = reverse("logistics_shipment_manifest", args=[shipment.pk])
        csv_response = self.client.get(url + "?download=csv")
        self.assertContains(csv_response, "'=FORMULA")
        self.assertContains(csv_response, "'@FORMULA")
        html = self.client.get(url)
        self.assertContains(html, "&lt;script&gt;destination&lt;/script&gt;")
        self.assertNotContains(html, "<script>destination</script>")

    def test_staff_ui_creation_edit_assignment_status_manifest_and_association(self):
        response = self.client.post(
            reverse("logistics_shipment_create"),
            {
                "origin": "Miami",
                "destination": "Curacao",
                "notes": "Draft note",
            },
        )
        self.assertEqual(response.status_code, 302)
        shipment = Shipment.objects.get()
        self.assertContains(self.client.get(reverse("logistics_shipment_list")), shipment.reference)
        self.assertEqual(
            self.client.post(
                reverse("logistics_shipment_edit", args=[shipment.pk]),
                {
                    "origin": "Orlando",
                    "destination": "Curacao",
                    "notes": "Updated",
                },
            ).status_code,
            302,
        )
        parcel = self.parcel()
        assign_url = reverse("logistics_shipment_assign", args=[shipment.pk])
        self.assertEqual(self.client.post(assign_url, {"parcel": parcel.pk}).status_code, 302)
        self.assertContains(
            self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk])),
            shipment.reference,
        )
        self.assertContains(
            self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk])),
            parcel.tracking_code,
        )
        remove_url = reverse("logistics_shipment_remove", args=[shipment.pk, parcel.pk])
        self.assertEqual(self.client.post(remove_url).status_code, 302)
        self.assertEqual(self.client.post(assign_url, {"parcel": parcel.pk}).status_code, 302)
        status_url = reverse("logistics_shipment_status", args=[shipment.pk])
        self.assertEqual(
            self.client.post(
                status_url, {"status": "READY", "expected_status": "DRAFT"}
            ).status_code,
            400,
        )
        self.parcel_status(parcel, "RECEIVED")
        self.assertEqual(
            self.client.post(
                status_url, {"status": "READY", "expected_status": "DRAFT"}
            ).status_code,
            302,
        )
        self.assertEqual(
            self.client.get(reverse("logistics_shipment_edit", args=[shipment.pk])).status_code, 400
        )

    def test_ui_url_and_post_object_tampering(self):
        shipment, parcel = self.shipment(), self.parcel()
        foreign = create_shipment(
            business=self.other, actor=self.other_user, origin="Other", destination="Other"
        )
        foreign_parcel = register_parcel(
            business=self.other,
            client=self.other_customer,
            actor=self.other_user,
            origin="Other",
            destination="Other",
            package_description="FOREIGN",
        )
        for route, args, method in self.routes(foreign, foreign_parcel):
            if args:
                self.assertEqual(
                    getattr(self.client, method)(reverse(route, args=args)).status_code, 404, route
                )
        self.assertEqual(
            self.client.post(
                reverse("logistics_shipment_assign", args=[shipment.pk]),
                {"parcel": foreign_parcel.pk},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                reverse("logistics_shipment_remove", args=[shipment.pk, foreign_parcel.pk])
            ).status_code,
            404,
        )
        self.assign(shipment, parcel)
        self.assertEqual(
            self.client.get(reverse("logistics_shipment_status", args=[shipment.pk])).status_code,
            405,
        )
        self.assertEqual(
            self.client.get(
                reverse("logistics_shipment_remove", args=[shipment.pk, parcel.pk])
            ).status_code,
            405,
        )

    def test_roles_membership_and_user_activity_in_services_and_ui(self):
        shipment = self.shipment()
        for role in ("owner", "admin", "staff"):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            self.shipment()
        for role in ("accountant", "viewer"):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            with self.assertRaises(PermissionDenied):
                self.shipment()
            with self.assertRaises(PermissionDenied):
                self.status(shipment, "CANCELLED")
            self.assertEqual(self.manifest(shipment)["parcel_count"], 0)
            self.assertEqual(self.client.get(reverse("logistics_shipment_create")).status_code, 403)
            self.assertEqual(self.client.get(reverse("logistics_shipment_list")).status_code, 200)
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            self.manifest(shipment)
        self.membership.is_active = True
        self.membership.save(update_fields=["is_active"])
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            self.manifest(shipment)
        with self.assertRaises(PermissionDenied):
            generate_manifest(business=self.business, shipment=shipment, actor=self.other_user)

    def test_subscription_plan_capability_and_business_activity_rechecked(self):
        shipment = self.shipment()
        for status in ("pending_checkout", "cancelled", "expired", "suspended"):
            BusinessSubscription.objects.filter(business=self.business).update(status=status)
            with self.assertRaises(PermissionDenied):
                self.shipment()
            with self.assertRaises(PermissionDenied):
                self.manifest(shipment)
        BusinessSubscription.objects.filter(business=self.business).update(
            status="active", plan=ClarivoPlan.objects.get(slug="pro")
        )
        with self.assertRaises(PermissionDenied):
            self.shipment()
        BusinessSubscription.objects.filter(business=self.business).update(
            plan=ClarivoPlan.objects.get(slug="logistics")
        )
        with patch.object(
            BusinessSubscription,
            "can_view_module",
            side_effect=lambda module: module != "manifests",
        ):
            with self.assertRaises(PermissionDenied):
                self.manifest(shipment)
        with patch.object(
            BusinessSubscription, "can_use_module", side_effect=lambda module: module != "shipments"
        ):
            with self.assertRaises(PermissionDenied):
                self.shipment()
        self.business.is_active = False
        self.business.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            self.shipment()

    def test_restricted_subscription_reads_manifest_but_rejects_writes(self):
        shipment = self.shipment()
        now = timezone.now()
        BusinessSubscription.objects.filter(business=self.business).update(
            status="past_due",
            payment_provider="stripe",
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_ship_test",
            provider_subscription_id="sub_ship_test",
            provider_price_id="price_ship_test",
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )
        self.assertEqual(self.manifest(shipment)["parcel_count"], 0)
        for route in (
            "logistics_shipment_list",
            "logistics_shipment_detail",
            "logistics_shipment_manifest",
        ):
            args = [] if route.endswith("list") else [shipment.pk]
            self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 200)
        with self.assertRaises(PermissionDenied):
            self.status(shipment, "CANCELLED")
        self.assertEqual(
            self.client.get(
                reverse("logistics_shipment_create"), HTTP_ACCEPT="application/json"
            ).status_code,
            403,
        )

    def test_csrf_anonymous_access_and_domain_write_guards(self):
        self.assertEqual(WebClient().get(reverse("logistics_shipment_list")).status_code, 302)
        csrf_client = WebClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        session = csrf_client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.assertEqual(
            csrf_client.post(
                reverse("logistics_shipment_create"), {"origin": "X", "destination": "Y"}
            ).status_code,
            403,
        )
        shipment, parcel = self.shipment(), self.parcel()
        for operation in (
            lambda: shipment.save(),
            lambda: shipment.delete(),
            lambda: Shipment.objects.filter(pk=shipment.pk).update(status="IN_TRANSIT"),
            lambda: Shipment.objects.bulk_create(
                [Shipment(business=self.business, origin="X", destination="Y")]
            ),
            lambda: Shipment.objects.bulk_update([shipment], ["status"]),
            lambda: Shipment.objects.filter(pk=shipment.pk).delete(),
            lambda: Parcel.objects.filter(pk=parcel.pk).update(shipment=shipment),
        ):
            with self.assertRaises(ValidationError):
                operation()
        with self.assertRaises(ValidationError):
            Shipment(business=self.service, origin="X", destination="Y").full_clean()
        with self.assertRaises(ValidationError):
            Shipment(
                business=self.business, created_by=self.other_user, origin="X", destination="Y"
            ).full_clean()

    def test_inventory_inspection_and_ordered_purge_preserve_other_tenant(self):
        shipment, parcel = self.shipment(), self.parcel()
        self.assign(shipment, parcel)
        foreign = create_shipment(
            business=self.other, actor=self.other_user, origin="Other", destination="Other"
        )
        inventory = build_business_data_inventory(self.business)
        records = {row.key: row for row in inventory.records}
        self.assertEqual(records["shipments"].total_count, 1)
        self.assertEqual(records["shipments"].active_count, 1)
        self.assertTrue(records["shipments"].explicit_deletion_required)
        self.assertFalse(find_unregistered_direct_business_relations())
        self.assertLess(
            PURGE_DELETION_ORDER.index("parcels"), PURGE_DELETION_ORDER.index("shipments")
        )
        out = StringIO()
        call_command("inspect_business_data", business_id=str(self.business.pk), stdout=out)
        self.assertIn("shipments", out.getvalue())
        with self.assertRaises(BusinessPurgeError):
            purge_business(business_id=self.business.pk, reason_reference="BLOCK8-ACTIVE")
        self.business.is_active = False
        self.business.save(update_fields=["is_active"])
        self.assertFalse(plan_business_purge(self.business.pk).blocking_error_codes)
        self.assertTrue(Shipment.objects.filter(pk=shipment.pk).exists())
        result = purge_business(business_id=self.business.pk, reason_reference="BLOCK8-TEST")
        self.assertEqual(result.deletion_counts["shipments"], 1)
        self.assertEqual(result.deletion_counts["parcels"], 1)
        self.assertFalse(Shipment.objects.filter(pk=shipment.pk).exists())
        self.assertTrue(Shipment.objects.filter(pk=foreign.pk).exists())

    def test_corrupt_shipment_relation_blocks_both_tenant_purges(self):
        shipment = create_shipment(
            business=self.other, actor=self.other_user, origin="Other", destination="Other"
        )
        parcel = self.parcel()
        QuerySet(model=Parcel).filter(pk=parcel.pk).update(shipment=shipment)
        for business in (self.business, self.other):
            business.is_active = False
            business.save(update_fields=["is_active"])
            self.assertIn(
                "cross_tenant_integrity_blockers",
                plan_business_purge(business.pk).blocking_error_codes,
            )
            with self.assertRaises(BusinessPurgeError):
                purge_business(business_id=business.pk, reason_reference="BLOCK8-CORRUPT")
        self.assertTrue(Shipment.objects.filter(pk=shipment.pk).exists())
        self.assertTrue(Parcel.objects.filter(pk=parcel.pk).exists())

    def test_cross_business_shipment_creator_preserves_user(self):
        foreign = create_shipment(
            business=self.other, actor=self.other_user, origin="Other", destination="Other"
        )
        QuerySet(model=Shipment).filter(pk=foreign.pk).update(created_by=self.user)
        self.business.is_active = False
        self.business.save(update_fields=["is_active"])
        decision = next(
            d
            for d in plan_business_purge(
                self.business.pk, delete_eligible_users=True
            ).user_decisions
            if d.user_id == self.user.pk
        )
        self.assertFalse(decision.delete)
        self.assertIn("cross_business_operational_references", decision.reason_codes)
        checks = {
            check.check_code: check
            for check in build_business_data_inventory(self.business).integrity_checks
        }
        self.assertEqual(checks["cross_tenant_user_shipments"].affected_count, 1)

    def test_purge_rollback_restores_grouping_and_failed_audit(self):
        shipment, parcel = self.shipment(), self.parcel()
        self.assign(shipment, parcel)
        self.business.is_active = False
        self.business.save(update_fields=["is_active"])
        with patch(
            "apps.businesses.business_data_purge._verify_purge_complete",
            side_effect=RuntimeError("failure"),
        ):
            with self.assertRaises(BusinessPurgeError):
                purge_business(business_id=self.business.pk, reason_reference="BLOCK8-ROLLBACK")
        parcel.refresh_from_db()
        self.assertEqual(parcel.shipment_id, shipment.pk)
        self.assertEqual(parcel.events.count(), 1)
        self.assertTrue(Shipment.objects.filter(pk=shipment.pk).exists())
        self.assertEqual(
            BusinessDataOperation.objects.get(business_id_snapshot=self.business.pk).status,
            "failed",
        )

    def test_admin_is_readonly_scoped_with_scoped_business_filter(self):
        shipment = self.shipment()
        create_shipment(
            business=self.other, actor=self.other_user, origin="Other", destination="Other"
        )
        request = RequestFactory().get("/admin/")
        request.user = self.user
        request.session = {CURRENT_BUSINESS_SESSION_KEY: self.business.pk}
        model_admin = ShipmentAdmin(Shipment, AdminSite())
        self.assertEqual(list(model_admin.get_queryset(request)), [shipment])
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, shipment))
        self.assertFalse(model_admin.has_delete_permission(request, shipment))
        from django.contrib.admin import RelatedOnlyFieldListFilter

        business_filter = RelatedOnlyFieldListFilter(
            Shipment._meta.get_field("business"), request, {}, Shipment, model_admin, "business"
        )
        self.assertEqual(business_filter.lookup_choices, [(self.business.pk, str(self.business))])
