import uuid
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from . import test_concurrency as concurrency_fixtures
from . import test_shipments as fixtures
from .models import ParcelEvent, Shipment
from .parcel_services import change_parcel_status
from .shipment_services import (
    assign_parcel,
    change_shipment_status,
    create_shipment,
    update_shipment,
)
from .test_concurrency import race


def hidden(form):
    return {field.name: field.value() for field in form.hidden_fields()}


class ShipmentWriteSafetyTests(TestCase):
    setUp = fixtures.ShipmentTests.setUp
    shipment = fixtures.ShipmentTests.shipment
    parcel = fixtures.ShipmentTests.parcel
    parcel_status = fixtures.ShipmentTests.parcel_status
    assign = fixtures.ShipmentTests.assign
    status = fixtures.ShipmentTests.status
    ready_shipment = fixtures.ShipmentTests.ready_shipment

    def form_data(self, shipment=None, **fields):
        url = (
            reverse("logistics_shipment_edit", args=[shipment.pk])
            if shipment
            else reverse("logistics_shipment_create")
        )
        form = self.client.get(url).context["form"]
        return {**hidden(form), "origin": "Miami", "destination": "Curacao", "notes": "", **fields}

    def detail_data(self, shipment, form="assignment_form", **fields):
        response = self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk]))
        return {**hidden(response.context[form]), **fields}

    def test_create_retry_returns_original_even_after_later_edit(self):
        key = uuid.uuid4()
        original = self.shipment(idempotency_key=key)
        update_shipment(
            business=self.business, actor=self.user, shipment=original, origin="Updated"
        )
        replay = self.shipment(idempotency_key=key)
        self.assertEqual(replay.pk, original.pk)
        self.assertEqual(replay.origin, "Updated")
        self.assertEqual(Shipment.objects.count(), 1)
        with self.assertRaisesMessage(ValidationError, "different shipment operation"):
            self.shipment(idempotency_key=key, origin="Different payload")

    def test_retry_payload_preserves_full_schedule_precision(self):
        key = uuid.uuid4()
        departure = timezone.now().replace(microsecond=123001)
        self.shipment(idempotency_key=key, departure_at=departure)
        with self.assertRaisesMessage(ValidationError, "different shipment operation"):
            self.shipment(idempotency_key=key, departure_at=departure.replace(microsecond=123002))

    def test_create_post_with_initial_parcel_replays_and_redirects_to_same_shipment(self):
        parcel = self.parcel()
        data = self.form_data(parcel=parcel.pk)
        url = reverse("logistics_shipment_create")
        first = self.client.post(url, data)
        second = self.client.post(url, data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(first.url, second.url)
        self.assertEqual(Shipment.objects.count(), 1)
        parcel.refresh_from_db()
        self.assertEqual(parcel.shipment_id, Shipment.objects.get().pk)
        self.assertEqual(parcel.events.count(), 1)

    def test_invalid_create_keeps_retry_token_for_successful_resubmission(self):
        data = self.form_data(destination="")
        response = self.client.post(reverse("logistics_shipment_create"), data)
        self.assertEqual(
            str(response.context["form"]["idempotency_key"].value()), str(data["idempotency_key"])
        )
        self.assertEqual(Shipment.objects.count(), 0)
        data["destination"] = "Curacao"
        self.assertEqual(
            self.client.post(reverse("logistics_shipment_create"), data).status_code, 302
        )
        self.assertEqual(
            self.client.post(reverse("logistics_shipment_create"), data).status_code, 302
        )
        self.assertEqual(Shipment.objects.count(), 1)

    def test_duplicate_assignment_post_is_successful_without_revision_or_event_duplication(self):
        shipment, parcel = self.shipment(), self.parcel()
        data = self.detail_data(shipment, parcel=parcel.pk)
        url = reverse("logistics_shipment_assign", args=[shipment.pk])
        for _ in range(2):
            self.assertEqual(self.client.post(url, data).status_code, 302)
        shipment.refresh_from_db()
        self.assertEqual(shipment.revision, 2)
        self.assertEqual(shipment.parcels.count(), 1)
        self.assertEqual(parcel.events.count(), 1)

    def test_repeated_departure_post_appends_each_parcel_event_once(self):
        shipment, parcels = self.ready_shipment(count=2)
        data = self.detail_data(shipment, form="status_form", status="IN_TRANSIT")
        url = reverse("logistics_shipment_status", args=[shipment.pk])
        for _ in range(2):
            self.assertEqual(self.client.post(url, data).status_code, 302)
        for parcel in parcels:
            parcel.refresh_from_db()
            self.assertEqual(parcel.current_status, "IN_TRANSIT")
            self.assertEqual(parcel.events.filter(status="IN_TRANSIT").count(), 1)

    def test_stale_edit_post_preserves_newer_data_and_shows_reload_error(self):
        shipment = self.shipment()
        data = self.form_data(shipment, origin="Stale origin")
        update_shipment(
            business=self.business, actor=self.user, shipment=shipment, origin="Newer origin"
        )
        response = self.client.post(reverse("logistics_shipment_edit", args=[shipment.pk]), data)
        self.assertContains(response, "Reload before saving")
        self.assertContains(response, "Stale origin")
        shipment.refresh_from_db()
        self.assertEqual(shipment.origin, "Newer origin")

    def test_edit_retry_does_not_restore_old_data_after_another_edit(self):
        shipment = self.shipment()
        url = reverse("logistics_shipment_edit", args=[shipment.pk])
        first = self.form_data(shipment, origin="First edit")
        self.assertEqual(self.client.post(url, first).status_code, 302)
        shipment.refresh_from_db()
        later = self.form_data(shipment, origin="Later edit")
        self.assertEqual(self.client.post(url, later).status_code, 302)
        self.assertEqual(self.client.post(url, first).status_code, 302)
        shipment.refresh_from_db()
        self.assertEqual((shipment.origin, shipment.revision), ("Later edit", 3))
        first["origin"] = "Changed retry payload"
        self.assertContains(self.client.post(url, first), "different shipment operation")

    def test_assignment_and_status_cycles_invalidate_old_edit_revision(self):
        shipment, parcel = self.shipment(), self.parcel()
        stale = self.form_data(shipment)
        self.assign(shipment, parcel)
        self.parcel_status(parcel, "RECEIVED")
        self.status(shipment, "READY")
        self.status(shipment, "DRAFT")
        self.assertContains(
            self.client.post(reverse("logistics_shipment_edit", args=[shipment.pk]), stale),
            "Reload before saving",
        )

    def test_removal_retry_cannot_remove_a_subsequent_reassignment(self):
        shipment, parcel = self.shipment(), self.parcel()
        self.assign(shipment, parcel)
        response = self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk]))
        data = hidden(list(response.context["parcels"])[0].shipment_remove_form)
        url = reverse("logistics_shipment_remove", args=[shipment.pk, parcel.pk])
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assign(shipment, parcel)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        parcel.refresh_from_db()
        self.assertEqual(parcel.shipment_id, shipment.pk)

    def test_terminal_shipment_accepts_only_known_no_op_replay_and_keeps_new_writes_frozen(self):
        shipment, parcels = self.ready_shipment()
        shipment.refresh_from_db()
        key, revision = uuid.uuid4(), shipment.revision
        for _ in range(2):
            change_shipment_status(
                business=self.business,
                actor=self.user,
                shipment=shipment,
                status="CANCELLED",
                expected_status="READY",
                expected_revision=revision,
                idempotency_key=key,
            )
        shipment.refresh_from_db()
        frozen = shipment.revision
        for operation in (
            lambda: update_shipment(
                business=self.business,
                actor=self.user,
                shipment=shipment,
                origin="Changed",
                expected_revision=frozen,
            ),
            lambda: assign_parcel(
                business=self.business, actor=self.user, shipment=shipment, parcel=parcels[0]
            ),
            lambda: change_shipment_status(
                business=self.business,
                actor=self.user,
                shipment=shipment,
                status="DRAFT",
                idempotency_key=uuid.uuid4(),
            ),
        ):
            with self.assertRaises(ValidationError):
                operation()
        shipment.refresh_from_db()
        self.assertEqual((shipment.status, shipment.revision), ("CANCELLED", frozen))
        self.assertEqual(parcels[0].events.count(), 2)

    def test_status_retry_after_cycle_does_not_repeat_old_transition(self):
        shipment, _ = self.ready_shipment()
        self.status(shipment, "DRAFT")
        shipment.refresh_from_db()
        key, revision = uuid.uuid4(), shipment.revision
        kwargs = dict(
            business=self.business,
            actor=self.user,
            shipment=shipment,
            status="READY",
            expected_status="DRAFT",
            expected_revision=revision,
            idempotency_key=key,
        )
        change_shipment_status(**kwargs)
        self.status(shipment, "DRAFT")
        replay = change_shipment_status(**kwargs)
        self.assertEqual(replay.status, "DRAFT")

    def test_tenant_scoped_creation_keys_and_replay_permission_checks(self):
        key = uuid.uuid4()
        local = self.shipment(idempotency_key=key)
        foreign = create_shipment(
            business=self.other,
            actor=self.other_user,
            idempotency_key=key,
            origin="Miami",
            destination="Curacao",
        )
        self.assertNotEqual(local.pk, foreign.pk)
        with self.assertRaises(ValidationError):
            update_shipment(
                business=self.business,
                actor=self.user,
                shipment=foreign,
                origin="Other",
                expected_revision=1,
                idempotency_key=key,
            )
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            self.shipment(idempotency_key=key)

    def test_failed_create_assignment_rolls_back_shipment_receipt_and_membership(self):
        parcel, key = self.parcel(), uuid.uuid4()
        with patch(
            "apps.logistics.shipment_services.assign_parcel",
            side_effect=ValidationError("Assignment failed"),
        ):
            with self.assertRaises(ValidationError):
                self.shipment(idempotency_key=key, parcel=parcel)
        self.assertFalse(Shipment.objects.exists())
        parcel.refresh_from_db()
        self.assertIsNone(parcel.shipment_id)
        self.shipment(idempotency_key=key, parcel=parcel)
        self.assertEqual(Shipment.objects.count(), 1)

    def test_failed_departure_rolls_back_receipt_revision_and_all_parcel_events(self):
        shipment, parcels = self.ready_shipment(count=2)
        shipment.refresh_from_db()
        revision, key = shipment.revision, uuid.uuid4()
        real_change = change_parcel_status
        calls = 0

        def fail_second(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValidationError("Parcel update failed")
            return real_change(**kwargs)

        with patch(
            "apps.logistics.shipment_services.change_parcel_status", side_effect=fail_second
        ):
            with self.assertRaises(ValidationError):
                change_shipment_status(
                    business=self.business,
                    actor=self.user,
                    shipment=shipment,
                    status="IN_TRANSIT",
                    expected_revision=revision,
                    idempotency_key=key,
                )
        shipment.refresh_from_db()
        self.assertEqual((shipment.status, shipment.revision), ("READY", revision))
        self.assertNotIn(str(key), shipment.write_receipts)
        for parcel in parcels:
            parcel.refresh_from_db()
            self.assertEqual(parcel.current_status, "RECEIVED")
            self.assertEqual(parcel.events.count(), 2)

    def test_missing_or_malformed_write_tokens_fail_closed(self):
        shipment = self.shipment()
        for data in (
            {"origin": "X", "destination": "Y"},
            {
                "origin": "X",
                "destination": "Y",
                "idempotency_key": "invalid",
                "expected_revision": 1,
            },
        ):
            self.assertEqual(
                self.client.post(
                    reverse("logistics_shipment_edit", args=[shipment.pk]), data
                ).status_code,
                200,
            )
        shipment.refresh_from_db()
        self.assertEqual((shipment.origin, shipment.revision), ("Miami", 1))


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency requires PostgreSQL")
class ShipmentWriteSafetyConcurrencyTests(TransactionTestCase):
    setUp = concurrency_fixtures.LogisticsOperationConcurrencyTests.setUp
    parcel = concurrency_fixtures.LogisticsOperationConcurrencyTests.parcel
    shipment = concurrency_fixtures.LogisticsOperationConcurrencyTests.shipment

    def test_create_retry_race_creates_one_shipment_and_one_assignment(self):
        key, parcel = uuid.uuid4(), self.parcel()
        results = race(
            [
                lambda: create_shipment(
                    business=self.business,
                    actor=self.user,
                    origin="A",
                    destination="B",
                    idempotency_key=key,
                    parcel=parcel,
                ).pk
            ]
            * 2
        )
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], "ok")
        self.assertEqual(Shipment.objects.count(), 1)
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_concurrent_edits_reject_the_stale_writer(self):
        shipment = self.shipment()
        results = race(
            [
                lambda origin=origin: update_shipment(
                    business=self.business,
                    actor=self.user,
                    shipment=shipment,
                    expected_revision=1,
                    idempotency_key=uuid.uuid4(),
                    origin=origin,
                ).origin
                for origin in ("First", "Second")
            ]
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        shipment.refresh_from_db()
        self.assertEqual(
            shipment.origin, next(value for status, value in results if status == "ok")
        )
        self.assertEqual(shipment.revision, 2)

    def test_same_assignment_retry_race_succeeds_once_without_extra_revision(self):
        shipment, parcel, key = self.shipment(), self.parcel(), uuid.uuid4()
        results = race(
            [
                lambda: assign_parcel(
                    business=self.business,
                    actor=self.user,
                    shipment=shipment,
                    parcel=parcel,
                    idempotency_key=key,
                    expected_revision=1,
                ).pk
            ]
            * 2
        )
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], "ok")
        shipment.refresh_from_db()
        self.assertEqual(shipment.revision, 2)

    def test_keyed_departure_race_records_one_event_per_parcel(self):
        shipment, parcel = self.shipment(), self.parcel()
        change_parcel_status(
            business=self.business, actor=self.user, parcel=parcel, status="RECEIVED"
        )
        assign_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=parcel)
        change_shipment_status(
            business=self.business, actor=self.user, shipment=shipment, status="READY"
        )
        shipment.refresh_from_db()
        key, revision = uuid.uuid4(), shipment.revision
        results = race(
            [
                lambda: change_shipment_status(
                    business=self.business,
                    actor=self.user,
                    shipment=shipment,
                    status="IN_TRANSIT",
                    expected_status="READY",
                    expected_revision=revision,
                    idempotency_key=key,
                ).pk
            ]
            * 2
        )
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], "ok")
        self.assertEqual(ParcelEvent.objects.filter(parcel=parcel, status="IN_TRANSIT").count(), 1)

    def test_assignment_racing_edit_never_overwrites_a_stale_revision(self):
        shipment, parcel = self.shipment(), self.parcel()
        results = race(
            [
                lambda: update_shipment(
                    business=self.business,
                    actor=self.user,
                    shipment=shipment,
                    origin="Edited",
                    expected_revision=1,
                ).pk,
                lambda: assign_parcel(
                    business=self.business, actor=self.user, shipment=shipment, parcel=parcel
                ).pk,
            ]
        )
        self.assertEqual(results[1][0], "ok")
        shipment.refresh_from_db()
        parcel.refresh_from_db()
        self.assertEqual(parcel.shipment_id, shipment.pk)
        self.assertEqual(shipment.origin, "Edited" if results[0][0] == "ok" else "Miami")

    def test_concurrent_conflicting_creation_payload_cannot_share_retry_key(self):
        key = uuid.uuid4()
        results = race(
            [
                lambda origin=origin: create_shipment(
                    business=self.business,
                    actor=self.user,
                    origin=origin,
                    destination="B",
                    idempotency_key=key,
                ).pk
                for origin in ("A", "Changed")
            ]
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        self.assertEqual(Shipment.objects.count(), 1)
