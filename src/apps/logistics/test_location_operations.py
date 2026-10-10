"""Action-site authorization, audit and scanner adapters under reviewed rollout."""

import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.models import BusinessUser

from . import test_parcels
from .location_access_services import (
    enable_location_operations,
    review_location_access,
    select_work_location,
    set_handling_site,
    set_location_assignment,
)
from .models import (
    LogisticsLocation,
    LogisticsLocationAssignment,
    LogisticsProfile,
    ParcelEvent,
)
from .parcel_services import change_parcel_status, edit_parcel, register_parcel
from .public_tracking import lookup_public_tracking
from .scan import resolve_scanned_parcel
from .shipment_services import assign_parcel, change_shipment_status, create_shipment


class LocationOperationsTests(TestCase):
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch

    def setUp(self):
        self.setUp_base()
        self.sites = [
            LogisticsLocation.objects.create(
                business=self.business, code=code, name=code, location_type="HUB", country_code="US"
            )
            for code in ("ORIGIN", "DESTINATION", "STOP", "UNRELATED")
        ]
        self.a, self.b, self.stop, self.unrelated = self.sites
        self.foreign = LogisticsLocation.objects.create(
            business=self.other,
            code="FOREIGN",
            name="Foreign",
            location_type="HUB",
            country_code="US",
        )
        self.staff = TaskIOUser.objects.create_user(
            email="operator@example.test", password="testpass123"
        )
        self.member = BusinessUser.objects.create(
            business=self.business, user=self.staff, role="staff"
        )
        for site in self.sites[:3]:
            set_location_assignment(
                business=self.business,
                actor=self.user,
                membership=self.member,
                location=site,
                can_operate=True,
            )
        review_location_access(business=self.business, actor=self.user)
        self.select(self.user, self.a)
        enable_location_operations(business=self.business, actor=self.user)
        self.item = self.parcel()

    def select(self, actor, site):
        return select_work_location(business=self.business, actor=actor, location=site)

    def parcel(self, **fields):
        return register_parcel(
            business=self.business,
            actor=self.user,
            client=self.customer,
            **{**self.fields, "origin_location": self.a, "destination_location": self.b, **fields},
        )

    def act(self, status, *, item=None, actor=None, **kwargs):
        return change_parcel_status(
            business=self.business,
            parcel=item or self.item,
            actor=actor or self.staff,
            status=status,
            **kwargs,
        )

    def arrive(self):
        self.act("RECEIVED")
        self.act("IN_TRANSIT")
        self.select(self.staff, self.b)
        self.act("ARRIVED")

    def ship(self, **fields):
        return create_shipment(
            business=self.business,
            actor=self.user,
            origin="Miami",
            destination="Curacao",
            origin_location=self.a,
            destination_location=self.b,
            **fields,
        )

    def ship_act(self, shipment, status, *, actor=None, **kwargs):
        return change_shipment_status(
            business=self.business,
            actor=actor or self.staff,
            shipment=shipment,
            status=status,
            **kwargs,
        )

    def test_valid_lifecycle_records_actor_site_and_before_after_state(self):
        self.arrive()
        self.act("READY")
        event = self.act("DELIVERED")
        self.assertEqual(
            (
                event.actor_id,
                event.business_id,
                event.parcel_id,
                event.operational_location_id,
                event.previous_status,
                event.resulting_status,
            ),
            (self.staff.pk, self.business.pk, self.item.pk, self.b.pk, "READY", "DELIVERED"),
        )
        self.assertIsNotNone(event.timestamp)
        self.assertEqual(event.location, "")
        with self.assertRaises(ValidationError):
            event.save()

    def test_wrong_origin_intake_changes_nothing_even_when_visible(self):
        self.select(self.staff, self.b)
        before = self.item.events.count()
        with self.assertRaises(PermissionDenied):
            self.act("RECEIVED")
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_status, "REGISTERED")
        self.assertEqual(self.item.events.count(), before)

    def test_departure_requires_last_handling_site(self):
        self.act("RECEIVED")
        self.select(self.staff, self.b)
        with self.assertRaises(PermissionDenied):
            self.act("IN_TRANSIT")
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_status, "RECEIVED")

    def test_hold_cannot_move_an_unreceived_parcel_to_another_visible_site(self):
        self.select(self.staff, self.b)
        with self.assertRaises(PermissionDenied):
            self.act("HOLD")
        self.assertEqual(self.item.events.count(), 1)

    def test_scanner_buttons_hide_wrong_site_actions_without_mutating(self):
        self.client.force_login(self.staff)
        self.switch(self.business)
        self.select(self.staff, self.b)
        response = self.client.post(
            reverse("logistics_parcel_scan"),
            {
                "tracking_code": self.item.tracking_code,
            },
        )
        self.assertEqual(response.status_code, 200)
        values = {value for value, _ in response.context["scan_actions"]}
        self.assertNotIn("RECEIVED", values)
        self.assertNotIn("HOLD", values)
        self.assertEqual(self.item.events.count(), 1)

    def test_arrival_requires_next_site_and_cannot_arrive_at_departure_site(self):
        self.act("RECEIVED")
        self.act("IN_TRANSIT")
        with self.assertRaises(PermissionDenied):
            self.act("ARRIVED")
        self.select(self.staff, self.b)
        self.act("ARRIVED")

    def test_multi_stop_uses_explicit_next_site_without_rewriting_lifecycle(self):
        set_handling_site(
            business=self.business,
            actor=self.user,
            parcel=self.item,
            location=self.stop,
            kind="EXPECTED",
        )
        self.act("RECEIVED")
        self.act("IN_TRANSIT")
        self.select(self.staff, self.b)
        with self.assertRaises(PermissionDenied):
            self.act("ARRIVED")
        self.select(self.staff, self.stop)
        self.act("ARRIVED")
        self.act("HOLD")
        self.act("IN_TRANSIT")
        self.select(self.staff, self.b)
        self.act("ARRIVED")
        self.act("READY")
        self.act("DELIVERED")

    def test_stop_visibility_does_not_authorize_arrival(self):
        set_handling_site(
            business=self.business,
            actor=self.user,
            parcel=self.item,
            location=self.stop,
            kind="STOP",
        )
        self.act("RECEIVED")
        self.act("IN_TRANSIT")
        self.select(self.staff, self.stop)
        self.assertIsNotNone(
            resolve_scanned_parcel(
                business=self.business, actor=self.staff, code=self.item.tracking_code
            )
        )
        with self.assertRaises(PermissionDenied):
            self.act("ARRIVED")

    def test_ambiguous_expected_sites_reject_arrival_atomically(self):
        for site in (self.b, self.stop):
            set_handling_site(
                business=self.business,
                actor=self.user,
                parcel=self.item,
                location=site,
                kind="EXPECTED",
            )
        self.act("RECEIVED")
        self.act("IN_TRANSIT")
        self.select(self.staff, self.b)
        with self.assertRaises(ValidationError):
            self.act("ARRIVED")
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_status, "IN_TRANSIT")

    def test_delivery_requires_current_eligible_site(self):
        self.arrive()
        self.act("READY")
        self.select(self.staff, self.a)
        with self.assertRaises(PermissionDenied):
            self.act("DELIVERED")

    def test_hold_at_destination_can_resume_arrival_from_original_departure(self):
        self.act("RECEIVED")
        self.act("IN_TRANSIT")
        self.select(self.staff, self.b)
        self.act("HOLD")
        self.act("ARRIVED")
        self.assertEqual(self.item.events.latest("pk").operational_location_id, self.b.pk)

    def test_duplicate_receipt_is_one_event_and_bound_to_site(self):
        key = uuid.uuid4()
        event = self.act("RECEIVED", idempotency_key=key, expected_status="REGISTERED")
        replay = self.act("RECEIVED", idempotency_key=key, expected_status="REGISTERED")
        self.assertEqual(replay.pk, event.pk)
        self.select(self.staff, self.b)
        with self.assertRaises(ValidationError):
            self.act("RECEIVED", idempotency_key=key, expected_status="REGISTERED")
        self.assertEqual(self.item.events.count(), 2)

    def test_stale_status_and_duplicate_without_key_make_no_success_event(self):
        self.act("RECEIVED")
        for kwargs in ({}, {"expected_status": "REGISTERED"}):
            with self.assertRaises(ValidationError):
                self.act("RECEIVED", **kwargs)
        self.assertEqual(self.item.events.count(), 2)

    def test_tampered_foreign_inactive_and_unassigned_sites_are_denied(self):
        for site in (self.foreign, self.unrelated, "bad-id"):
            with self.assertRaises(PermissionDenied):
                self.select(self.staff, site)
        self.a.is_active = False
        self.a.save()
        with self.assertRaises(PermissionDenied):
            self.act("RECEIVED")
        self.assertEqual(self.item.events.count(), 1)

    def test_persisted_revocation_overrules_cached_actor_and_membership(self):
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=self.member,
            location=self.a,
            revoke=True,
        )
        with self.assertRaises(PermissionDenied):
            self.act("RECEIVED")

    def test_administrator_needs_selected_site_and_explicit_override(self):
        self.select(self.user, self.b)
        with self.assertRaises(PermissionDenied):
            self.act("RECEIVED", actor=self.user)
        event = self.act(
            "RECEIVED", actor=self.user, location_override_reason="Approved reroute at intake"
        )
        self.assertEqual(event.operational_location_id, self.b.pk)
        self.assertEqual(event.location_override_reason, "Approved reroute at intake")
        with self.assertRaises(ValidationError):
            self.act(
                "DELIVERED", actor=self.user, location_override_reason="Cannot bypass lifecycle"
            )

    def test_staff_cannot_request_override_or_forge_context_by_public_text(self):
        self.select(self.staff, self.b)
        for kwargs in ({"location_override_reason": "I approve"}, {"location": self.a.code}):
            with self.assertRaises(PermissionDenied):
                self.act("RECEIVED", **kwargs)
        self.assertEqual(self.item.events.count(), 1)

    def test_administrator_context_is_not_a_worker_grant_after_demotion(self):
        self.membership.role = "staff"
        self.membership.save(update_fields=["role"])
        with self.assertRaises(PermissionDenied):
            self.act("RECEIVED", actor=self.user)
        self.assertIsNone(
            resolve_scanned_parcel(
                business=self.business, actor=self.user, code=self.item.tracking_code
            )
        )

    def test_administrator_loses_write_context_when_selected_site_is_deactivated(self):
        self.a.is_active = False
        self.a.save()
        with self.assertRaises(PermissionDenied):
            self.act("RECEIVED", actor=self.user)

    def test_registration_and_edit_use_verified_context(self):
        self.assertEqual(self.item.events.get().operational_location_id, self.a.pk)
        with self.assertRaises(PermissionDenied):
            self.parcel(origin_location=self.b)
        edit_parcel(
            business=self.business,
            actor=self.user,
            parcel=self.item,
            internal_reference="Reviewed details",
        )
        self.assertEqual(self.item.events.latest("pk").operational_location_id, self.a.pk)

    def test_manual_camera_and_wedge_lookup_are_read_only(self):
        before = self.item.events.count()
        for code in (
            self.item.tracking_code,
            self.item.tracking_code.lower(),
            "\t" + self.item.tracking_code + "\r\n",
        ):
            self.assertEqual(
                resolve_scanned_parcel(business=self.business, actor=self.staff, code=code).pk,
                self.item.pk,
            )
        self.assertEqual(self.item.events.count(), before)
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_status, "REGISTERED")

    def test_scanner_action_revalidates_site_and_ignores_tampered_location_id(self):
        self.client.force_login(self.staff)
        self.switch(self.business)
        self.select(self.staff, self.b)
        response = self.client.post(
            reverse("logistics_parcel_scan_action", args=[self.item.pk]),
            {
                "status": "RECEIVED",
                "expected_status": "REGISTERED",
                "idempotency_key": uuid.uuid4(),
                "operational_location": self.a.pk,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.item.events.count(), 1)

    def test_unauthorized_scan_resolves_nothing(self):
        outsider = TaskIOUser.objects.create_user(email="unassigned@example.test")
        BusinessUser.objects.create(business=self.business, user=outsider, role="staff")
        self.assertIsNone(
            resolve_scanned_parcel(
                business=self.business, actor=outsider, code=self.item.tracking_code
            )
        )

    def test_shipment_propagation_records_matching_actor_site_and_history(self):
        shipment = self.ship()
        assign_parcel(business=self.business, shipment=shipment, parcel=self.item, actor=self.staff)
        self.act("RECEIVED")
        self.ship_act(shipment, "READY")
        self.ship_act(shipment, "IN_TRANSIT")
        self.select(self.staff, self.b)
        shipment = self.ship_act(shipment, "ARRIVED")
        event = self.item.events.latest("pk")
        self.assertEqual(
            (event.status, event.operational_location_id, event.actor_id),
            ("ARRIVED", self.b.pk, self.staff.pk),
        )
        entry = shipment.operation_history[-1]
        self.assertEqual(
            (entry["actor_id"], entry["location_id"], entry["previous_state"], entry["new_state"]),
            (self.staff.pk, self.b.pk, "IN_TRANSIT", "ARRIVED"),
        )
        self.assertEqual(shipment.operation_history[1]["action"], "assign")

    def test_shipment_departure_rejects_one_invalid_parcel_before_any_write(self):
        shipment = self.ship()
        self.select(self.user, self.stop)
        other = self.parcel(origin_location=self.stop)
        self.act("RECEIVED", item=other, actor=self.user)
        self.select(self.user, self.a)
        for item in (self.item, other):
            assign_parcel(business=self.business, shipment=shipment, parcel=item, actor=self.user)
        self.act("RECEIVED")
        with self.assertRaises(PermissionDenied):
            self.ship_act(shipment, "READY")
        shipment = self.ship_act(
            shipment, "READY", actor=self.user, location_override_reason="Approved readiness review"
        )
        before = ParcelEvent.objects.count()
        with self.assertRaises(PermissionDenied):
            self.ship_act(shipment, "IN_TRANSIT")
        shipment.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual((shipment.status, self.item.current_status), ("READY", "RECEIVED"))
        self.assertEqual(ParcelEvent.objects.count(), before)
        self.assertEqual(shipment.operation_history[-1]["new_state"], "READY")

    def test_shipment_next_stop_can_be_approved_intermediate_site_for_cargo(self):
        shipment = self.ship()
        set_handling_site(
            business=self.business,
            actor=self.user,
            shipment=shipment,
            location=self.stop,
            kind="EXPECTED",
        )
        assign_parcel(business=self.business, shipment=shipment, parcel=self.item, actor=self.staff)
        self.act("RECEIVED")
        self.ship_act(shipment, "READY")
        self.ship_act(shipment, "IN_TRANSIT")
        self.select(self.staff, self.stop)
        self.ship_act(shipment, "ARRIVED")
        self.assertEqual(self.item.events.latest("pk").operational_location_id, self.stop.pk)

    def test_caller_supplied_shipment_route_is_reloaded_not_trusted(self):
        shipment = self.ship()
        assign_parcel(business=self.business, shipment=shipment, parcel=self.item, actor=self.staff)
        self.act("RECEIVED")
        self.ship_act(shipment, "READY")
        shipment = self.ship_act(shipment, "IN_TRANSIT")
        set_handling_site(
            business=self.business,
            actor=self.user,
            shipment=shipment,
            location=self.stop,
            kind="STOP",
        )
        self.select(self.staff, self.stop)
        shipment.destination_location = self.stop
        with self.assertRaises(PermissionDenied):
            self.act("ARRIVED", _shipment_context=shipment)
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_status, "IN_TRANSIT")

    def test_shipment_override_and_duplicate_submission_do_not_duplicate_audits(self):
        shipment = self.ship()
        assign_parcel(business=self.business, shipment=shipment, parcel=self.item, actor=self.user)
        self.act("RECEIVED")
        self.ship_act(shipment, "READY")
        self.select(self.user, self.b)
        key = uuid.uuid4()
        kwargs = {
            "actor": self.user,
            "idempotency_key": key,
            "location_override_reason": "Approved alternate departure",
        }
        shipment = self.ship_act(shipment, "IN_TRANSIT", **kwargs)
        count = len(shipment.operation_history)
        again = self.ship_act(shipment, "IN_TRANSIT", **kwargs)
        self.assertEqual(len(again.operation_history), count)
        self.assertEqual(
            self.item.events.latest("pk").location_override_reason, "Approved alternate departure"
        )
        self.select(self.user, self.a)
        with self.assertRaises(ValidationError):
            self.ship_act(shipment, "IN_TRANSIT", **kwargs)

    def test_membership_audit_and_cancel_release_preserve_previous_state(self):
        shipment = self.ship()
        assign_parcel(business=self.business, shipment=shipment, parcel=self.item, actor=self.user)
        shipment = self.ship_act(shipment, "CANCELLED", actor=self.user)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.shipment_id)
        self.assertEqual(
            [entry["action"] for entry in shipment.operation_history],
            ["create", "assign", "remove", "status"],
        )
        self.assertEqual(shipment.operation_history[-1]["previous_state"], "DRAFT")
        self.assertEqual(self.item.current_status, "REGISTERED")

    def test_tenant_isolation_applies_to_override_and_audit_reference(self):
        with self.assertRaises(PermissionDenied):
            self.select(self.user, self.foreign)
        with self.assertRaises(PermissionDenied):
            change_parcel_status(
                business=self.other,
                actor=self.user,
                parcel=self.item,
                status="RECEIVED",
                location_override_reason="Not a bypass",
            )
        event = ParcelEvent(
            business=self.business,
            parcel=self.item,
            actor=self.user,
            event_type="NOTE",
            internal_note="Test",
            operational_location=self.foreign,
        )
        with self.assertRaises(ValidationError):
            event._domain_save(force_insert=True)

    @override_settings(LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE=False)
    def test_public_projection_excludes_structured_location_actor_and_private_override(self):
        self.select(self.user, self.b)
        event = self.act(
            "RECEIVED",
            actor=self.user,
            public_message="Received safely",
            location_override_reason="Private override reason",
        )
        projection = json.dumps(lookup_public_tracking(self.item.tracking_code), default=str)
        for private in (
            "operational_location",
            "actor",
            "previous_status",
            "location_override_reason",
            self.b.name,
            event.location_override_reason,
            str(self.user),
        ):
            self.assertNotIn(private, projection)
        self.assertIn("Received safely", projection)

    def test_rollout_requires_review_context_and_explicit_confirmation(self):
        profile = LogisticsProfile.objects.get(business=self.business)
        enabled = profile.location_operations_enabled_at
        enable_location_operations(business=self.business, actor=self.user)
        profile.refresh_from_db()
        self.assertEqual(profile.location_operations_enabled_at, enabled)
        self.client.post(reverse("logistics_location_access"), {"action": "enable_operations"})
        profile.refresh_from_db()
        self.assertEqual(profile.location_operations_enabled_at, enabled)
        with self.assertRaises(PermissionDenied):
            enable_location_operations(business=self.business, actor=self.staff)

    def test_rollout_rejects_missing_review_or_selected_context(self):
        profile = LogisticsProfile.objects.get(business=self.business)
        profile.location_operations_enabled_at = None
        profile.location_access_reviewed_at = None
        profile.save(
            update_fields=["location_operations_enabled_at", "location_access_reviewed_at"]
        )
        with self.assertRaises(ValidationError):
            enable_location_operations(business=self.business, actor=self.user)
        review_location_access(business=self.business, actor=self.user)
        LogisticsLocationAssignment.objects.filter(membership=self.membership).delete()
        with self.assertRaises(ValidationError):
            enable_location_operations(business=self.business, actor=self.user)
        profile.refresh_from_db()
        self.assertIsNone(profile.location_operations_enabled_at)

    def test_pre_rollout_preserves_admin_operations_without_creating_site_context(self):
        profile = LogisticsProfile.objects.get(business=self.business)
        profile.location_operations_enabled_at = None
        profile.save(update_fields=["location_operations_enabled_at"])
        LogisticsLocationAssignment.objects.filter(membership=self.membership).delete()
        event = self.act("RECEIVED", actor=self.user)
        self.assertIsNone(event.operational_location_id)
        self.assertEqual(event.actor_id, self.user.pk)
        self.assertEqual(event.previous_status, "REGISTERED")

    def test_approved_handling_stop_is_eligible_for_delivery(self):
        for kind in ("EXPECTED", "STOP"):
            set_handling_site(
                business=self.business,
                actor=self.user,
                parcel=self.item,
                location=self.stop,
                kind=kind,
            )
        self.act("RECEIVED")
        self.act("IN_TRANSIT")
        self.select(self.staff, self.stop)
        self.act("ARRIVED")
        self.act("READY")
        self.act("DELIVERED")
        self.assertEqual(self.item.events.latest("pk").operational_location_id, self.stop.pk)

    def test_single_site_worker_can_complete_an_explicit_same_facility_route(self):
        for site in (self.b, self.stop):
            set_location_assignment(
                business=self.business,
                actor=self.user,
                membership=self.member,
                location=site,
                revoke=True,
            )
        item = self.parcel(destination="Miami", destination_location=self.a)
        for status in ("RECEIVED", "IN_TRANSIT", "ARRIVED", "READY", "DELIVERED"):
            self.act(status, item=item)
        item.refresh_from_db()
        self.assertEqual(item.current_status, "DELIVERED")
        self.assertFalse(item.events.exclude(operational_location=self.a).exists())

    def test_service_operations_do_not_require_or_accept_logistics_context(self):
        with self.assertRaises(PermissionDenied):
            select_work_location(business=self.service, actor=self.user, location=self.a)
        self.assertFalse(LogisticsProfile.objects.filter(business=self.service).exists())
