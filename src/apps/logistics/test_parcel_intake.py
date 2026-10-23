"""Explicit hub intake composes registration and the existing receipt transition."""

import uuid
from unittest import skipUnless
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.billings.models import Invoice
from apps.businesses.models import BusinessUser

from . import (
    test_concurrency,
    test_location_operations,
    test_location_operations_concurrency,
    test_parcels,
)
from .location_access import assignments_for
from .models import (
    LogisticsCharge,
    LogisticsLocationAssignment,
    LogisticsProfile,
    Parcel,
    ParcelEvent,
)
from .parcel_services import (
    change_parcel_status,
    edit_parcel,
    register_and_receive_parcel,
    register_parcel,
)
from .public_tracking import lookup_public_tracking
from .shipment_services import assign_parcel


class ParcelIntakeTests(TestCase):
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    setUp = test_location_operations.LocationOperationsTests.setUp
    select = test_location_operations.LocationOperationsTests.select
    parcel = test_location_operations.LocationOperationsTests.parcel
    ship = test_location_operations.LocationOperationsTests.ship

    def intake(self, key=None, **changes):
        return register_and_receive_parcel(
            **{
                "business": self.business,
                "actor": self.staff,
                "client": self.customer,
                "idempotency_key": key or uuid.uuid4(),
                **self.fields,
                "origin_location": self.a,
                "destination_location": self.b,
                **changes,
            }
        )

    def post_data(self, **changes):
        return {
            "client": self.customer.pk,
            "origin_country_code": "US",
            "destination_country_code": "US",
            "origin_location": self.a.pk,
            "destination_location": self.b.pk,
            "package_description": "Books accepted at the hub",
            "idempotency_key": str(uuid.uuid4()),
            "save_and_receive": "1",
            **changes,
        }

    def test_staff_intake_keeps_registration_and_attributable_receipt(self):
        parcel = self.intake()
        registered, received = parcel.events.all()
        self.assertEqual(parcel.current_status, "RECEIVED")
        self.assertEqual([registered.status, received.status], ["REGISTERED", "RECEIVED"])
        self.assertEqual(
            (received.previous_status, received.resulting_status), ("REGISTERED", "RECEIVED")
        )
        for event in (registered, received):
            self.assertEqual(event.actor_id, self.staff.pk)
            self.assertEqual(event.operational_location_id, self.a.pk)
            self.assertEqual(event.business_id, self.business.pk)
        self.assertLessEqual(registered.timestamp, received.timestamp)
        self.assertNotEqual(registered.idempotency_key, received.idempotency_key)
        self.assertEqual(received.location_override_reason, "")

    def test_tracking_and_assignment_use_existing_receipt_without_financial_effects(self):
        parcel = self.intake()
        projection = lookup_public_tracking(parcel.tracking_code)
        self.assertEqual(projection["status"], "RECEIVED")
        self.assertEqual(
            [event["status"] for event in projection["events"]], ["REGISTERED", "RECEIVED"]
        )
        self.assertNotIn("operational_location", str(projection))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(LogisticsCharge.objects.count(), 0)
        shipment = self.ship()
        assign_parcel(business=self.business, actor=self.staff, parcel=parcel, shipment=shipment)
        parcel.refresh_from_db()
        self.assertEqual(parcel.shipment_id, shipment.pk)
        self.assertEqual(parcel.current_status, "RECEIVED")
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(LogisticsCharge.objects.count(), 0)

    def test_receipt_failure_rolls_back_creation_history_and_commit_callbacks(self):
        count = Parcel.objects.count()
        event_count = ParcelEvent.objects.count()
        effects = []
        save = ParcelEvent._domain_save

        def failing_receipt(event, *args, **kwargs):
            save(event, *args, **kwargs)
            transaction.on_commit(lambda: effects.append(event.status))
            if event.status == "RECEIVED":
                raise ValidationError("Receipt failed.")

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with patch.object(ParcelEvent, "_domain_save", failing_receipt):
                with self.assertRaisesMessage(ValidationError, "Receipt failed"):
                    self.intake()
        self.assertEqual(Parcel.objects.count(), count)
        self.assertEqual(ParcelEvent.objects.count(), event_count)
        self.assertEqual(callbacks, [])
        self.assertEqual(effects, [])

    def test_retries_do_not_repeat_events_or_commit_effects(self):
        key = uuid.uuid4()
        effects = []
        save = ParcelEvent._domain_save

        def queue_effect(event, *args, **kwargs):
            save(event, *args, **kwargs)
            transaction.on_commit(lambda: effects.append(event.status))

        with self.captureOnCommitCallbacks(execute=True):
            with patch.object(ParcelEvent, "_domain_save", queue_effect):
                parcel = self.intake(key)
                replay = self.intake(key)
        self.assertEqual(parcel.pk, replay.pk)
        self.assertEqual(parcel.events.count(), 2)
        self.assertEqual(effects, ["REGISTERED", "RECEIVED"])

    def test_retry_after_later_movement_does_not_receive_again_or_rewind(self):
        key = uuid.uuid4()
        parcel = self.intake(key)
        change_parcel_status(business=self.business, actor=self.staff, parcel=parcel, status="HOLD")
        replay = self.intake(key)
        self.assertEqual(replay.current_status, "HOLD")
        self.assertEqual(replay.events.filter(status="RECEIVED").count(), 1)
        self.assertEqual(replay.events.count(), 3)

    def test_changed_payload_and_employee_cannot_reuse_creation_key(self):
        key = uuid.uuid4()
        parcel = self.intake(key)
        for changes in ({"package_description": "Different goods"}, {"actor": self.user}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.intake(key, **changes)
        self.assertEqual(parcel.events.count(), 2)

    def test_destination_work_site_cannot_receive_at_origin(self):
        self.select(self.staff, self.b)
        count = Parcel.objects.count()
        with self.assertRaises(PermissionDenied):
            self.intake()
        self.assertEqual(Parcel.objects.count(), count)

    def test_legacy_admin_cannot_infer_receiving_hub_from_destination(self):
        LogisticsProfile.objects.filter(business=self.business).update(
            location_operations_enabled_at=None
        )
        self.select(self.user, self.b)
        count = Parcel.objects.count()
        with self.assertRaises(PermissionDenied):
            self.intake(actor=self.user)
        self.assertEqual(Parcel.objects.count(), count)
        # Legacy advance registration remains supported independently of intake.
        parcel = register_parcel(
            business=self.business, actor=self.user, client=self.customer, **self.fields
        )
        self.assertEqual(parcel.current_status, "REGISTERED")

    def test_foreign_client_route_and_actor_are_rejected_atomically(self):
        count = Parcel.objects.count()
        for changes, error in (
            ({"client": self.other_customer}, ValidationError),
            ({"origin_location": self.foreign}, PermissionDenied),
            ({"destination_location": self.foreign}, ValidationError),
            ({"actor": self.other_user}, PermissionDenied),
        ):
            with self.subTest(changes=changes), self.assertRaises(error):
                self.intake(**changes)
        self.assertEqual(Parcel.objects.count(), count)

    def test_read_only_unassigned_and_inactive_hub_are_rejected(self):
        assignment = LogisticsLocationAssignment.objects.get(
            membership=self.member, location=self.a
        )
        assignment.can_operate = False
        assignment.save()
        with self.assertRaises(PermissionDenied):
            self.intake()
        assignment.can_operate = True
        assignment.save()
        assignment.delete()
        with self.assertRaises(PermissionDenied):
            self.intake()
        self.a.is_active = False
        self.a.save()
        with self.assertRaises(PermissionDenied):
            self.intake(actor=self.user)

    def test_non_hub_and_missing_current_site_do_not_offer_or_allow_intake(self):
        self.a.location_type = "WAREHOUSE"
        self.a.save()
        self.assertNotContains(
            self.client.get(reverse("logistics_parcel_register")), 'name="save_and_receive"'
        )
        with self.assertRaises(PermissionDenied):
            self.intake()
        LogisticsProfile.objects.filter(business=self.business).update(
            location_operations_enabled_at=None
        )
        LogisticsLocationAssignment.objects.filter(membership=self.membership).update(
            is_current=False
        )
        with self.assertRaises(PermissionDenied):
            self.intake(actor=self.user)

    def test_receiving_does_not_require_or_grant_destination_access(self):
        LogisticsLocationAssignment.objects.filter(membership=self.member, location=self.b).delete()
        parcel = self.intake()
        self.assertEqual(parcel.current_status, "RECEIVED")
        self.assertFalse(
            assignments_for(self.business, self.staff).filter(location=self.b).exists()
        )

    def test_non_operational_roles_cannot_intake(self):
        for role in (BusinessUser.Role.VIEWER, BusinessUser.Role.ACCOUNTANT):
            self.member.role = role
            self.member.save(update_fields=["role"])
            with self.subTest(role=role), self.assertRaises(PermissionDenied):
                self.intake()

    def test_explicit_ui_action_and_repeated_posts_receive_once(self):
        self.client.force_login(self.staff)
        url = reverse("logistics_parcel_register")
        page = self.client.get(url)
        self.assertContains(page, 'name="save_and_receive"', count=1)
        self.assertContains(page, ">Register Parcel</button>", count=1)
        self.assertNotContains(page, "Save &amp; receive")
        data = self.post_data()
        first = self.client.post(url, data)
        self.assertEqual(first.status_code, 302)
        parcel = Parcel.objects.exclude(pk=self.item.pk).get()
        self.assertEqual(first.url, reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertEqual(parcel.current_status, "RECEIVED")
        self.assertEqual(self.client.post(url, data).url, first.url)
        self.assertEqual(parcel.events.count(), 2)

    def test_non_hub_register_parcel_still_registers_and_opens_details(self):
        self.a.location_type = "WAREHOUSE"
        self.a.save()
        url = reverse("logistics_parcel_register")
        self.assertNotContains(self.client.get(url), 'name="save_and_receive"')
        response = self.client.post(url, self.post_data(save_and_receive=""))
        parcel = Parcel.objects.exclude(pk=self.item.pk).get()
        self.assertEqual(response.url, reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertEqual(parcel.current_status, "REGISTERED")
        self.assertEqual(parcel.events.count(), 1)

    def test_view_receipt_failure_keeps_form_key_and_creates_nothing(self):
        data = self.post_data(save_and_receive="", continue_registration="1")
        count = Parcel.objects.count()
        with patch(
            "apps.logistics.parcel_services.change_parcel_status",
            side_effect=ValidationError("Receipt failed"),
        ):
            response = self.client.post(reverse("logistics_parcel_register"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Receipt failed")
        self.assertEqual(
            response.context["form"]["idempotency_key"].value(), data["idempotency_key"]
        )
        self.assertEqual(Parcel.objects.count(), count)

    def test_hub_continue_receives_for_owner_admin_and_staff_with_exact_retries(self):
        for role, actor in (("owner", self.user), ("admin", self.user), ("staff", self.staff)):
            if actor == self.user:
                self.membership.role = role
                self.membership.save(update_fields=["role"])
            self.client.force_login(actor)
            data = self.post_data(save_and_receive="", continue_registration="1")
            response = self.client.post(reverse("logistics_parcel_register"), data)
            self.assertEqual(response.status_code, 302)
            created = Parcel.objects.get(events__idempotency_key=data["idempotency_key"])
            self.assertEqual(created.current_status, "RECEIVED")
            self.assertEqual(
                list(created.events.values_list("status", flat=True)), ["REGISTERED", "RECEIVED"]
            )
            self.assertEqual(created.events.last().actor_id, actor.pk)
            self.assertEqual(created.events.last().operational_location_id, self.a.pk)
            self.assertEqual(
                self.client.post(reverse("logistics_parcel_register"), data).url, response.url
            )
            self.assertEqual(created.events.count(), 2)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_registration_buttons_and_metadata_edit_stay_separate(self):
        url = reverse("logistics_parcel_register")
        for continue_registration in ("", "1"):
            data = self.post_data(save_and_receive="", continue_registration=continue_registration)
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, 302)
            created = Parcel.objects.get(events__idempotency_key=data["idempotency_key"])
            expected_view = (
                "logistics_parcel_registration"
                if continue_registration
                else "logistics_parcel_detail"
            )
            self.assertEqual(response.url, reverse(expected_view, args=[created.pk]))
        for parcel in Parcel.objects.exclude(pk=self.item.pk):
            self.assertEqual(parcel.current_status, "RECEIVED")
            self.assertEqual(parcel.events.count(), 2)
        parcel = self.intake()
        edited = edit_parcel(
            business=self.business, actor=self.staff, parcel=parcel, sender_name="Updated sender"
        )
        self.assertEqual(edited.current_status, "RECEIVED")
        self.assertEqual(edited.events.filter(status="RECEIVED").count(), 1)
        self.assertEqual(edited.events.last().event_type, "NOTE")
        self.assertNotContains(
            self.client.get(reverse("logistics_parcel_edit", args=[parcel.pk])),
            'name="save_and_receive"',
        )

    def test_missing_retry_key_cannot_create_an_intake(self):
        count = Parcel.objects.count()
        with self.assertRaises(ValidationError):
            register_and_receive_parcel(
                business=self.business, actor=self.staff, client=self.customer, **self.fields
            )
        self.assertEqual(Parcel.objects.count(), count)


@skipUnless(connection.vendor == "postgresql", "Hub intake concurrency requires PostgreSQL")
class ParcelIntakeConcurrencyTests(TransactionTestCase):
    setUp_base = test_location_operations_concurrency.VerifiedOperationConcurrencyTests.setUp_base
    setUp = test_location_operations_concurrency.VerifiedOperationConcurrencyTests.setUp

    def test_simultaneous_intake_retries_create_one_parcel_and_one_receipt(self):
        key = uuid.uuid4()

        def intake():
            return register_and_receive_parcel(
                business=self.business,
                actor=self.staff,
                client=self.customer,
                origin="Miami",
                destination="Sint Maarten",
                origin_location=self.a,
                destination_location=self.b,
                package_description="Books",
                idempotency_key=key,
            ).pk

        results = test_concurrency.race([intake, intake])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], "ok")
        parcel = Parcel.objects.get(pk=results[0][1])
        self.assertEqual(Parcel.objects.exclude(pk=self.item.pk).count(), 1)
        self.assertEqual(parcel.current_status, "RECEIVED")
        self.assertEqual(
            list(parcel.events.values_list("status", flat=True)), ["REGISTERED", "RECEIVED"]
        )
