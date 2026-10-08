import uuid
from io import StringIO
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db.models import QuerySet
from django.test import RequestFactory, TestCase
from django.urls import reverse

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

from .admin import ParcelAdmin, ParcelEventAdmin
from .forms import ParcelRegistrationForm
from .models import Parcel, ParcelEvent
from .parcel_policy import ALLOWED_TRANSITIONS
from .parcel_services import (
    change_parcel_status,
    parcels_for_business,
    record_parcel_event,
    register_parcel,
)


class ParcelTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Courier", slug="parcel-courier", vertical=Business.Vertical.LOGISTICS
        )
        self.other = Business.objects.create(
            name="Other", slug="parcel-other", vertical=Business.Vertical.LOGISTICS
        )
        self.service = Business.objects.create(name="Service", slug="parcel-service")
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        for business in (self.business, self.other):
            BusinessSubscription.objects.create(
                business=business,
                plan=plan,
                status=BusinessSubscription.Status.ACTIVE,
                billing_interval=BusinessSubscription.BillingInterval.YEARLY,
            )
        BusinessSubscription.objects.create(
            business=self.service,
            plan=ClarivoPlan.objects.get(slug="pro"),
            status=BusinessSubscription.Status.ACTIVE,
        )
        self.user = TaskIOUser.objects.create_user(
            email="parcel@example.com", password="testpass123"
        )
        self.other_user = TaskIOUser.objects.create_user(
            email="parcel-other@example.com", password="testpass123"
        )
        self.membership = BusinessUser.objects.create(
            business=self.business, user=self.user, role=BusinessUser.Role.OWNER
        )
        BusinessUser.objects.create(
            business=self.service, user=self.user, role=BusinessUser.Role.OWNER
        )
        BusinessUser.objects.create(
            business=self.other, user=self.other_user, role=BusinessUser.Role.OWNER
        )
        self.customer = Client.objects.create(
            business=self.business,
            first_name="Parcel",
            last_name="Customer",
            email="customer@example.com",
        )
        self.other_customer = Client.objects.create(
            business=self.other, first_name="Other", last_name="Customer", email="other@example.com"
        )
        self.unowned = Client.objects.create(
            first_name="Legacy", last_name="Customer", email="legacy@example.com"
        )
        self.fields = {
            "origin": "Miami",
            "destination": "Curacao",
            "package_description": "Books",
            "quantity": 2,
        }
        self.client.force_login(self.user)
        self.switch(self.business)

    def switch(self, business):
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = business.pk
        session.save()

    def register(self, **kwargs):
        return register_parcel(
            business=self.business,
            client=self.customer,
            actor=self.user,
            **{**self.fields, **kwargs},
        )

    def change(self, parcel, status, **kwargs):
        return change_parcel_status(
            business=self.business, parcel=parcel, actor=self.user, status=status, **kwargs
        )

    def test_registration_creates_authoritative_initial_event(self):
        parcel = self.register(
            weight_kg="1.500", dimensions="20 × 10 × 5 cm", declared_value="50.00"
        )
        self.assertEqual(parcel.business, self.business)
        self.assertEqual(parcel.client, self.customer)
        self.assertEqual(parcel.created_by, self.user)
        self.assertEqual(parcel.current_status, Parcel.Status.REGISTERED)
        event = parcel.events.get()
        self.assertEqual(
            (event.business_id, event.status, event.actor_id),
            (self.business.pk, Parcel.Status.REGISTERED, self.user.pk),
        )

    def test_service_business_denied_by_service_and_all_routes(self):
        self.switch(self.service)
        for route in ("logistics_parcel_list", "logistics_parcel_register"):
            response = self.client.get(reverse(route), HTTP_ACCEPT="application/json")
            self.assertEqual(response.status_code, 403)
        with self.assertRaises(PermissionDenied):
            register_parcel(
                business=self.service, client=self.customer, actor=self.user, **self.fields
            )
        parcel = self.register()
        for route in ("logistics_parcel_detail", "logistics_parcel_update"):
            self.assertEqual(
                self.client.get(
                    reverse(route, args=[parcel.pk]), HTTP_ACCEPT="application/json"
                ).status_code,
                403,
            )
        self.assertEqual(Parcel.objects.count(), 1)

    def test_null_unowned_and_cross_tenant_clients_rejected(self):
        for customer in (None, self.unowned, self.other_customer):
            with self.subTest(customer=customer), self.assertRaises(ValidationError):
                register_parcel(
                    business=self.business, client=customer, actor=self.user, **self.fields
                )
        self.assertEqual(Parcel.objects.count(), 0)
        # Even an object whose cached business was tampered with is rechecked.
        self.other_customer.business = self.business
        with self.assertRaises(ValidationError):
            register_parcel(
                business=self.business, client=self.other_customer, actor=self.user, **self.fields
            )

    def test_tracking_codes_are_random_unique_and_immutable(self):
        parcels = [self.register() for _ in range(5)]
        self.assertEqual(len({parcel.tracking_code for parcel in parcels}), 5)
        for parcel in parcels:
            self.assertRegex(parcel.tracking_code, r"\A[A-F0-9]{48}\Z")
            self.assertNotEqual(parcel.tracking_code, str(parcel.pk))
        with patch("secrets.token_hex", return_value="a" * 48) as random_source:
            parcel = self.register()
        random_source.assert_called_with(24)
        self.assertEqual(parcel.tracking_code, "A" * 48)
        parcel.tracking_code = "B" * 48
        with self.assertRaises(ValidationError):
            parcel.save()
        with self.assertRaises(ValidationError):
            parcel._domain_save()

    def test_central_lifecycle_and_history_preserved(self):
        parcel = self.register()
        self.assertEqual(set(ALLOWED_TRANSITIONS), set(Parcel.Status.values))
        for status in ("RECEIVED", "IN_TRANSIT", "ARRIVED", "READY", "DELIVERED"):
            event = self.change(parcel, status, public_message=f"Parcel {status.lower()}.")
            parcel.refresh_from_db()
            self.assertEqual(parcel.current_status, status)
            self.assertEqual(event.status, status)
        self.assertEqual(
            list(parcel.events.values_list("status", flat=True)),
            ["REGISTERED", "RECEIVED", "IN_TRANSIT", "ARRIVED", "READY", "DELIVERED"],
        )
        with self.assertRaises(ValidationError):
            self.change(parcel, "RECEIVED")
        self.assertEqual(parcel.events.count(), 6)

    def test_invalid_unknown_and_repeated_status_rejected(self):
        parcel = self.register()
        for status in ("DELIVERED", "UNKNOWN", "REGISTERED", ""):
            with self.subTest(status=status), self.assertRaises(ValidationError):
                self.change(parcel, status)
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "REGISTERED")
        self.assertEqual(parcel.events.count(), 1)

    def test_hold_and_cancellation(self):
        parcel = self.register()
        self.change(parcel, "HOLD")
        self.change(parcel, "RECEIVED")
        self.change(parcel, "CANCELLED")
        with self.assertRaises(ValidationError):
            self.change(parcel, "RECEIVED")

    def test_note_keeps_status_and_public_private_content_separate(self):
        parcel = self.register()
        event = record_parcel_event(
            business=self.business,
            parcel=parcel,
            actor=self.user,
            public_message="At collection point.",
            internal_note="Staff-only handling instruction.",
            location="Depot",
        )
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "REGISTERED")
        self.assertEqual((event.event_type, event.status), ("NOTE", ""))
        self.assertEqual(event.public_message, "At collection point.")
        self.assertEqual(event.internal_note, "Staff-only handling instruction.")
        with self.assertRaises(ValidationError):
            record_parcel_event(business=self.business, parcel=parcel, actor=self.user)

    def test_status_and_registration_rollback_on_event_failure(self):
        with patch.object(ParcelEvent, "_domain_save", side_effect=RuntimeError("storage failure")):
            with self.assertRaises(RuntimeError):
                self.register()
        self.assertEqual(Parcel.objects.count(), 0)
        parcel = self.register()
        with patch.object(ParcelEvent, "_domain_save", side_effect=RuntimeError("storage failure")):
            with self.assertRaises(RuntimeError):
                self.change(parcel, "RECEIVED")
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "REGISTERED")
        self.assertEqual(parcel.events.count(), 1)

    def test_registration_and_status_retries_are_idempotent(self):
        registration_key = uuid.uuid4()
        with patch("secrets.token_hex", return_value="c" * 48):
            parcel = self.register(idempotency_key=registration_key)
            self.assertEqual(self.register(idempotency_key=registration_key).pk, parcel.pk)
        key = uuid.uuid4()
        event = self.change(parcel, "RECEIVED", idempotency_key=key, expected_status="REGISTERED")
        self.change(parcel, "IN_TRANSIT")
        replay = self.change(parcel, "RECEIVED", idempotency_key=key, expected_status="REGISTERED")
        self.assertEqual(event.pk, replay.pk)
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "IN_TRANSIT")
        self.assertEqual(parcel.events.count(), 3)
        self.assertEqual(Parcel.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.register(idempotency_key=registration_key, destination="Elsewhere")
        with self.assertRaises(ValidationError):
            self.change(parcel, "ARRIVED", idempotency_key=key)

    def test_note_retry_and_retry_key_collision_across_parcels(self):
        parcel, second = self.register(), self.register()
        key = uuid.uuid4()
        args = dict(
            business=self.business, actor=self.user, idempotency_key=key, public_message="Update"
        )
        event = record_parcel_event(parcel=parcel, **args)
        self.assertEqual(record_parcel_event(parcel=parcel, **args).pk, event.pk)
        with self.assertRaises(ValidationError):
            record_parcel_event(parcel=second, **args)
        self.assertEqual(parcel.events.count(), 2)

    def test_stale_status_and_invalid_retry_key_rejected(self):
        parcel = self.register()
        self.change(parcel, "RECEIVED")
        with self.assertRaises(ValidationError):
            self.change(parcel, "IN_TRANSIT", expected_status="REGISTERED")
        with self.assertRaises(ValidationError):
            self.change(parcel, "IN_TRANSIT", idempotency_key="bad")
        self.assertEqual(parcel.events.count(), 2)

    def test_orm_cannot_bypass_history_or_delete_events(self):
        parcel = self.register()
        event = parcel.events.get()
        operations = [
            lambda: Parcel.objects.filter(pk=parcel.pk).update(current_status="DELIVERED"),
            lambda: Parcel.objects.bulk_update([parcel], ["current_status"]),
            lambda: Parcel.objects.bulk_create(
                [Parcel(business=self.business, client=self.customer, **self.fields)]
            ),
            lambda: Parcel.objects.create(
                business=self.business, client=self.customer, **self.fields
            ),
            lambda: ParcelEvent.objects.create(
                business=self.business, parcel=parcel, event_type="STATUS", status="DELIVERED"
            ),
            lambda: ParcelEvent.objects.bulk_create(
                [ParcelEvent(business=self.business, parcel=parcel)]
            ),
            lambda: ParcelEvent.objects.all().update(public_message="Rewritten"),
            lambda: ParcelEvent.objects.bulk_update([event], ["public_message"]),
            lambda: event.save(),
            lambda: event.delete(),
            lambda: parcel.delete(),
            lambda: parcel.events.all().delete(),
            lambda: Parcel.objects.all().delete(),
        ]
        for operation in operations:
            with self.assertRaises(ValidationError):
                operation()
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_cross_tenant_access_and_event_creation_denied(self):
        parcel = register_parcel(
            business=self.other, client=self.other_customer, actor=self.other_user, **self.fields
        )
        for route in ("logistics_parcel_detail", "logistics_parcel_update"):
            self.assertEqual(self.client.get(reverse(route, args=[parcel.pk])).status_code, 404)
            if route.endswith("update"):
                self.assertEqual(
                    self.client.post(
                        reverse(route, args=[parcel.pk]), {"status": "RECEIVED"}
                    ).status_code,
                    404,
                )
        self.assertNotIn(parcel, parcels_for_business(business=self.business, actor=self.user))
        with self.assertRaises(ValidationError):
            self.change(parcel, "RECEIVED")
        with self.assertRaises(ValidationError):
            record_parcel_event(
                business=self.business, parcel=parcel, actor=self.user, public_message="Tamper"
            )
        with self.assertRaises(ValidationError):
            ParcelEvent(
                business=self.business, parcel=parcel, event_type="STATUS", status="RECEIVED"
            ).full_clean()
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_moved_client_blocks_further_operations(self):
        parcel = self.register()
        Client.objects.filter(pk=self.customer.pk).update(business=None)
        with self.assertRaises(ValidationError):
            self.change(parcel, "RECEIVED")
        self.assertEqual(
            self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk])).status_code, 404
        )

    def test_forms_filter_tenant_and_post_cannot_assign_other_client(self):
        form = ParcelRegistrationForm(business=self.business)
        self.assertEqual(list(form.fields["client"].queryset), [self.customer])
        for customer in (self.other_customer, self.unowned):
            response = self.client.post(
                reverse("logistics_parcel_register"),
                {
                    **self.fields,
                    "client": customer.pk,
                    "idempotency_key": uuid.uuid4(),
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.assertEqual(Parcel.objects.count(), 0)

    def test_staff_ui_registration_detail_update_and_replay(self):
        data = {
            **self.fields,
            "client": self.customer.pk,
            "idempotency_key": str(uuid.uuid4()),
            "business": self.other.pk,
            "current_status": "DELIVERED",
            "tracking_code": "chosen",
        }
        response = self.client.post(reverse("logistics_parcel_register"), data)
        self.assertEqual(response.status_code, 302)
        parcel = Parcel.objects.get()
        self.assertEqual(parcel.business_id, self.business.pk)
        self.assertEqual(parcel.current_status, "REGISTERED")
        self.assertNotEqual(parcel.tracking_code, "chosen")
        self.assertEqual(
            self.client.post(reverse("logistics_parcel_register"), data).status_code, 302
        )
        for route in (
            "logistics_parcel_list",
            "logistics_parcel_detail",
            "logistics_parcel_update",
        ):
            args = [] if route.endswith("list") else [parcel.pk]
            self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 200)
        update = {
            "status": "RECEIVED",
            "expected_status": "REGISTERED",
            "idempotency_key": str(uuid.uuid4()),
            "public_message": "Received",
            "internal_note": "Private",
        }
        url = reverse("logistics_parcel_update", args=[parcel.pk])
        self.assertEqual(self.client.post(url, update).status_code, 302)
        self.assertEqual(self.client.post(url, update).status_code, 302)
        self.assertEqual(parcel.events.count(), 2)
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "RECEIVED")

    def test_roles_and_membership_enforced_in_services_and_ui(self):
        for role in (BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN, BusinessUser.Role.STAFF):
            self.membership.role = role
            self.membership.save()
            self.register()
        for role in (BusinessUser.Role.ACCOUNTANT, BusinessUser.Role.VIEWER):
            self.membership.role = role
            self.membership.save()
            with self.assertRaises(PermissionDenied):
                self.register()
            self.assertEqual(self.client.get(reverse("logistics_parcel_register")).status_code, 403)
            self.assertEqual(self.client.get(reverse("logistics_parcel_list")).status_code, 200)
        self.membership.is_active = False
        self.membership.save()
        with self.assertRaises(PermissionDenied):
            parcels_for_business(business=self.business, actor=self.user)
        with self.assertRaises(PermissionDenied):
            register_parcel(
                business=self.business, client=self.customer, actor=self.other_user, **self.fields
            )

    def test_subscription_and_plan_guards_rechecked(self):
        for status in ("pending_checkout", "cancelled", "expired", "suspended"):
            BusinessSubscription.objects.filter(business=self.business).update(status=status)
            with self.assertRaises(PermissionDenied):
                self.register()
            self.assertEqual(
                self.client.get(
                    reverse("logistics_parcel_register"), HTTP_ACCEPT="application/json"
                ).status_code,
                403,
            )
        BusinessSubscription.objects.filter(business=self.business).update(
            status="active", plan=ClarivoPlan.objects.get(slug="pro")
        )
        with self.assertRaises(PermissionDenied):
            self.register()

    def test_inventory_counts_command_and_dependency_registry(self):
        parcel = self.register()
        self.change(parcel, "RECEIVED")
        inventory = build_business_data_inventory(self.business)
        records = {row.key: row for row in inventory.records}
        self.assertEqual(records["parcels"].total_count, 1)
        self.assertEqual(records["parcel_events"].total_count, 2)
        self.assertTrue(records["parcels"].explicit_deletion_required)
        self.assertFalse(find_unregistered_direct_business_relations())
        self.assertLess(
            PURGE_DELETION_ORDER.index("parcel_events"), PURGE_DELETION_ORDER.index("parcels")
        )
        self.assertLess(
            PURGE_DELETION_ORDER.index("parcels"), PURGE_DELETION_ORDER.index("clients")
        )
        out = StringIO()
        call_command("inspect_business_data", business_id=str(self.business.pk), stdout=out)
        self.assertIn("parcel_events", out.getvalue())

    def test_gated_purge_deletes_parcel_history_and_preserves_other_business(self):
        parcel = self.register()
        other_parcel = register_parcel(
            business=self.other, client=self.other_customer, actor=self.other_user, **self.fields
        )
        self.business.is_active = False
        self.business.save(update_fields=["is_active"])
        result = purge_business(business_id=self.business.pk, reason_reference="BLOCK6-TEST")
        self.assertEqual(result.deletion_counts["parcels"], 1)
        self.assertEqual(result.deletion_counts["parcel_events"], 1)
        self.assertFalse(Parcel.objects.filter(pk=parcel.pk).exists())
        self.assertTrue(Parcel.objects.filter(pk=other_parcel.pk).exists())
        self.assertEqual(ParcelEvent.objects.count(), 1)
        self.assertTrue(TaskIOUser.objects.filter(pk=self.user.pk).exists())

    def test_corrupt_cross_tenant_parcel_relation_blocks_both_purges(self):
        parcel = self.register()
        # Simulate legacy/database corruption without using the guarded manager.
        QuerySet(model=Parcel).filter(pk=parcel.pk).update(client=self.other_customer)
        for business in (self.business, self.other):
            business.is_active = False
            business.save(update_fields=["is_active"])
            plan = plan_business_purge(business.pk)
            self.assertIn("cross_tenant_integrity_blockers", plan.blocking_error_codes)
            with self.assertRaises(BusinessPurgeError):
                purge_business(business_id=business.pk, reason_reference="BLOCK6-CORRUPT")
        self.assertTrue(Parcel.objects.filter(pk=parcel.pk).exists())

    def test_cross_business_event_actor_protects_user_from_deletion(self):
        parcel = register_parcel(
            business=self.other, client=self.other_customer, actor=self.other_user, **self.fields
        )
        QuerySet(model=ParcelEvent).filter(parcel=parcel).update(actor=self.user)
        self.business.is_active = False
        self.business.save(update_fields=["is_active"])
        plan = plan_business_purge(self.business.pk, delete_eligible_users=True)
        decision = next(item for item in plan.user_decisions if item.user_id == self.user.pk)
        self.assertFalse(decision.delete)
        self.assertIn("cross_business_operational_references", decision.reason_codes)
        checks = {check.check_code: check for check in plan.inventory.integrity_checks}
        self.assertEqual(checks["cross_tenant_user_parcel_events"].affected_count, 1)

    def test_purge_rollback_restores_event_history_and_failed_audit(self):
        parcel = self.register()
        self.business.is_active = False
        self.business.save(update_fields=["is_active"])
        with patch(
            "apps.businesses.business_data_purge._verify_purge_complete",
            side_effect=RuntimeError("verification failure"),
        ):
            with self.assertRaises(BusinessPurgeError):
                purge_business(business_id=self.business.pk, reason_reference="BLOCK6-ROLLBACK")
        self.assertTrue(Parcel.objects.filter(pk=parcel.pk).exists())
        self.assertEqual(parcel.events.count(), 1)
        self.assertEqual(
            BusinessDataOperation.objects.get(business_id_snapshot=self.business.pk).status,
            BusinessDataOperation.Status.FAILED,
        )

    def test_admin_is_tenant_scoped_and_readonly(self):
        parcel = self.register()
        register_parcel(
            business=self.other, client=self.other_customer, actor=self.other_user, **self.fields
        )
        request = RequestFactory().get("/admin/")
        request.user = self.user
        request.session = {CURRENT_BUSINESS_SESSION_KEY: self.business.pk}
        for model, admin_class in ((Parcel, ParcelAdmin), (ParcelEvent, ParcelEventAdmin)):
            model_admin = admin_class(model, AdminSite())
            self.assertEqual(model_admin.get_queryset(request).count(), 1)
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request, parcel))
            self.assertFalse(model_admin.has_delete_permission(request, parcel))

    def test_negative_values_rejected(self):
        for fields in ({"quantity": 0}, {"weight_kg": -1}, {"declared_value": -1}):
            with self.assertRaises(ValidationError):
                self.register(**fields)
        self.assertEqual(Parcel.objects.count(), 0)

    def test_restricted_subscription_allows_reads_and_rejects_writes(self):
        from datetime import timedelta

        from django.utils import timezone

        parcel = self.register()
        now = timezone.now()
        BusinessSubscription.objects.filter(business=self.business).update(
            status="past_due",
            payment_provider="stripe",
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_parcel_test",
            provider_subscription_id="sub_parcel_test",
            provider_price_id="price_parcel_test",
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )
        subscription = BusinessSubscription.objects.get(business=self.business)
        response = self.client.get(reverse("logistics_parcel_list"))
        self.assertEqual(
            response.status_code,
            200,
            f"{response.get('Location')}: {subscription.effective_access_state}",
        )
        self.assertEqual(
            self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk])).status_code, 200
        )
        for route, args in (
            ("logistics_parcel_register", []),
            ("logistics_parcel_update", [parcel.pk]),
        ):
            response = self.client.get(reverse(route, args=args), HTTP_ACCEPT="application/json")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"], "subscription_restricted")
        with self.assertRaises(PermissionDenied):
            self.change(parcel, "RECEIVED")
        self.assertEqual(parcel.events.count(), 1)

    def test_inactive_business_user_and_plan_rejected(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            self.register()
        self.user.is_active = True
        self.user.save(update_fields=["is_active"])
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = False
        plan.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            self.register()
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        self.business.is_active = False
        self.business.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            self.register()

    def test_authenticated_ui_csrf_and_history_escaping(self):
        from django.test import Client as WebClient

        anonymous = WebClient()
        self.assertEqual(anonymous.get(reverse("logistics_parcel_list")).status_code, 302)
        csrf_client = WebClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        session = csrf_client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.assertEqual(
            csrf_client.post(reverse("logistics_parcel_register"), self.fields).status_code, 403
        )
        parcel = self.register()
        record_parcel_event(
            business=self.business,
            parcel=parcel,
            actor=self.user,
            public_message="<script>alert('test')</script>",
            internal_note="<b>Internal</b>",
        )
        response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert")
        self.assertContains(response, "&lt;b&gt;Internal&lt;/b&gt;")

    def test_database_unique_tracking_constraint(self):
        parcel = self.register()
        with patch("secrets.token_hex", return_value=parcel.tracking_code.lower()):
            with self.assertRaises(ValidationError):
                self.register()
        self.assertEqual(Parcel.objects.count(), 1)

    def test_corrupt_event_tenant_blocks_outgoing_and_incoming_purge(self):
        parcel = self.register()
        QuerySet(model=ParcelEvent).filter(parcel=parcel).update(business=self.other)
        response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Parcel registered.")
        for business in (self.business, self.other):
            business.is_active = False
            business.save(update_fields=["is_active"])
            self.assertIn(
                "cross_tenant_integrity_blockers",
                plan_business_purge(business.pk).blocking_error_codes,
            )

    def test_history_survives_actor_deletion(self):
        parcel = self.register()
        self.user.delete()
        parcel.refresh_from_db()
        self.assertIsNone(parcel.created_by_id)
        self.assertIsNone(parcel.events.get().actor_id)
        self.assertEqual(parcel.events.count(), 1)

    def test_model_validation_rejects_foreign_actors(self):
        parcel = self.register()
        with self.assertRaises(ValidationError):
            Parcel(
                business=self.business,
                client=self.customer,
                created_by=self.other_user,
                **self.fields,
            ).full_clean()
        with self.assertRaises(ValidationError):
            ParcelEvent(
                business=self.business,
                parcel=parcel,
                actor=self.other_user,
                event_type="NOTE",
                public_message="Update",
            ).full_clean()

    def test_purge_still_refuses_active_business(self):
        parcel = self.register()
        with self.assertRaises(BusinessPurgeError):
            purge_business(business_id=self.business.pk, reason_reference="BLOCK6-ACTIVE")
        self.assertEqual(parcel.events.count(), 1)

    def test_admin_business_filters_only_list_current_tenant(self):
        self.register()
        register_parcel(
            business=self.other, client=self.other_customer, actor=self.other_user, **self.fields
        )
        request = RequestFactory().get("/admin/")
        request.user = self.user
        request.session = {CURRENT_BUSINESS_SESSION_KEY: self.business.pk}
        for model, admin_class in ((Parcel, ParcelAdmin), (ParcelEvent, ParcelEventAdmin)):
            model_admin = admin_class(model, AdminSite())
            from django.contrib.admin import RelatedOnlyFieldListFilter

            business_filter = RelatedOnlyFieldListFilter(
                model._meta.get_field("business"), request, {}, model, model_admin, "business"
            )
            self.assertEqual(
                business_filter.lookup_choices, [(self.business.pk, str(self.business))]
            )

    def test_registration_retry_cannot_return_foreign_parcel_from_corrupt_history(self):
        parcel = register_parcel(
            business=self.other, client=self.other_customer, actor=self.other_user, **self.fields
        )
        key = uuid.uuid4()
        QuerySet(model=ParcelEvent).filter(parcel=parcel).update(
            business=self.business,
            actor=self.user,
            idempotency_key=key,
        )
        with self.assertRaises(ValidationError):
            self.register(idempotency_key=key)
        self.assertEqual(Parcel.objects.count(), 1)
