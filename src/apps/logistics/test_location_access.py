from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client as HttpClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.business_data_inventory import (
    build_business_data_inventory,
    find_unregistered_direct_business_relations,
)
from apps.businesses.demo_seed_reset import DemoSeedResetError, _validate_no_genuine_dependents
from apps.businesses.models import BusinessUser

from . import test_parcels
from .dashboard import get_logistics_dashboard_context
from .forms import ParcelEditForm, ParcelRegistrationForm
from .location_access_forms import LocationAssignmentForm
from .location_access_services import (
    review_location_access,
    select_work_location,
    set_handling_site,
    set_location_assignment,
)
from .models import (
    LogisticsHandlingSite,
    LogisticsLocation,
    LogisticsLocationAssignment,
    LogisticsProfile,
    Parcel,
    ParcelEvent,
    Shipment,
)
from .parcel_services import (
    change_parcel_status,
    edit_parcel,
    parcels_for_business,
    register_parcel,
)
from .scan import resolve_scanned_parcel
from .shipment_forms import ShipmentAssignmentForm, ShipmentForm
from .shipment_services import (
    assign_parcel,
    change_shipment_status,
    create_shipment,
    generate_manifest,
    shipments_for_business,
    update_shipment,
)


class LocationAccessTests(TestCase):
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch

    def setUp(self):
        self.setUp_base()
        self.a = LogisticsLocation.objects.create(
            business=self.business,
            name="Site A",
            code="SITE-A",
            location_type="HUB",
            country_code="US",
        )
        self.b = LogisticsLocation.objects.create(
            business=self.business,
            name="Site B",
            code="SITE-B",
            location_type="HUB",
            country_code="US",
        )
        self.c = LogisticsLocation.objects.create(
            business=self.business,
            name="Restricted C",
            code="SITE-C",
            location_type="HUB",
            country_code="US",
        )
        self.foreign = LogisticsLocation.objects.create(
            business=self.other,
            name="Foreign",
            code="FOREIGN",
            location_type="HUB",
            country_code="US",
        )
        self.staff = TaskIOUser.objects.create_user(
            email="worker@example.com", password="testpass123"
        )
        self.member = BusinessUser.objects.create(
            business=self.business, user=self.staff, role=BusinessUser.Role.STAFF
        )
        self.pa = self.parcel(self.a)
        self.pc = self.parcel(self.c)
        self.legacy = self.parcel(None)
        self.sa = self.shipment(self.a)
        self.sc = self.shipment(self.c)
        self.grant(self.a)
        review_location_access(business=self.business, actor=self.user)

    def parcel(self, site):
        return register_parcel(
            business=self.business,
            actor=self.user,
            client=self.customer,
            **self.fields,
            origin_location=site,
        )

    def shipment(self, site):
        return create_shipment(
            business=self.business,
            actor=self.user,
            origin="Miami",
            destination="Curacao",
            origin_location=site,
        )

    def grant(self, site, operate=True):
        return set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=self.member,
            location=site,
            can_operate=operate,
        )

    def login_worker(self):
        self.client.force_login(self.staff)
        self.switch(self.business)

    def parcels(self):
        return parcels_for_business(business=self.business, actor=self.staff)

    def shipments(self):
        return shipments_for_business(business=self.business, actor=self.staff)

    def test_single_site_and_unassigned_fail_closed_without_affecting_owner(self):
        self.assertEqual(set(self.parcels()), {self.pa})
        self.assertEqual(set(self.shipments()), {self.sa})
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=self.member,
            location=self.a,
            revoke=True,
        )
        self.assertFalse(self.parcels().exists())
        self.assertFalse(self.shipments().exists())
        self.assertEqual(parcels_for_business(business=self.business, actor=self.user).count(), 3)
        with self.assertRaises(PermissionDenied):
            register_parcel(
                business=self.business,
                actor=self.staff,
                client=self.customer,
                **self.fields,
                origin_location=self.a,
            )

    def test_pending_review_ignores_approved_grants_and_preserves_profile(self):
        profile = LogisticsProfile.objects.get(business=self.business)
        profile.operating_areas = ["TRANSPORTATION"]
        profile.transportation_modes = ["SEA", "ROAD", "AIR", "RAIL"]
        profile.location_access_reviewed_at = None
        profile.save()
        self.assertFalse(self.parcels().exists())
        with self.assertRaises(PermissionDenied):
            select_work_location(business=self.business, actor=self.staff, location=self.a)
        review_location_access(business=self.business, actor=self.user)
        profile.refresh_from_db()
        self.assertEqual(profile.operating_areas, ["TRANSPORTATION"])
        self.assertEqual(set(profile.transportation_modes), {"SEA", "ROAD", "AIR", "RAIL"})
        self.assertEqual(set(self.parcels()), {self.pa})

    def test_multi_location_selection_validates_each_write(self):
        self.grant(self.c)
        self.assertEqual(set(self.parcels()), {self.pa, self.pc})
        with self.assertRaises(PermissionDenied):
            change_parcel_status(
                business=self.business,
                actor=self.staff,
                parcel=self.pc,
                status=Parcel.Status.RECEIVED,
            )
        select_work_location(business=self.business, actor=self.staff, location=self.c)
        change_parcel_status(
            business=self.business, actor=self.staff, parcel=self.pc, status=Parcel.Status.RECEIVED
        )
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_status, Parcel.Status.RECEIVED)
        self.assertEqual(
            LogisticsLocationAssignment.objects.filter(
                membership=self.member, is_current=True
            ).count(),
            1,
        )
        for invalid in (self.b, self.foreign, "nonsense", None):
            with self.assertRaises(PermissionDenied):
                select_work_location(business=self.business, actor=self.staff, location=invalid)

    def test_read_only_grant_does_not_permit_transition_or_creation(self):
        self.grant(self.a, operate=False)
        self.assertTrue(self.parcels().filter(pk=self.pa.pk).exists())
        with self.assertRaises(PermissionDenied):
            change_parcel_status(
                business=self.business,
                actor=self.staff,
                parcel=self.pa,
                status=Parcel.Status.RECEIVED,
            )
        with self.assertRaises(PermissionDenied):
            create_shipment(
                business=self.business,
                actor=self.staff,
                origin="Miami",
                destination="Curacao",
                origin_location=self.a,
            )

    def test_creation_and_route_tampering_cannot_expand_access(self):
        good = register_parcel(
            business=self.business,
            actor=self.staff,
            client=self.customer,
            **self.fields,
            origin_location=self.a,
        )
        self.assertIn(good, self.parcels())
        for site in (None, self.c, self.foreign):
            with self.assertRaises(PermissionDenied):
                register_parcel(
                    business=self.business,
                    actor=self.staff,
                    client=self.customer,
                    **self.fields,
                    origin_location=site,
                )
        with self.assertRaises(PermissionDenied):
            edit_parcel(
                business=self.business, actor=self.staff, parcel=self.pc, origin_location=self.a
            )
        with self.assertRaises(PermissionDenied):
            edit_parcel(
                business=self.business,
                actor=self.staff,
                parcel=self.pa,
                destination_location=self.c,
            )
        edit_parcel(
            business=self.business,
            actor=self.staff,
            parcel=self.pa,
            package_description="Authorized edit",
        )
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.package_description, "Authorized edit")
        with self.assertRaises(PermissionDenied):
            update_shipment(
                business=self.business, actor=self.staff, shipment=self.sa, origin_location=self.c
            )

    def test_expected_current_and_stop_sites_grant_visibility(self):
        for kind in LogisticsHandlingSite.Kind.values:
            with self.subTest(kind=kind):
                set_handling_site(
                    business=self.business,
                    actor=self.user,
                    parcel=self.pc,
                    location=self.a,
                    kind=kind,
                )
                self.assertIn(self.pc, self.parcels())
                set_handling_site(
                    business=self.business,
                    actor=self.user,
                    parcel=self.pc,
                    location=self.a,
                    kind=kind,
                    remove=True,
                )
                self.assertNotIn(self.pc, self.parcels())
        set_handling_site(
            business=self.business, actor=self.user, shipment=self.sc, location=self.a, kind="STOP"
        )
        self.assertIn(self.sc, self.shipments())
        assign_parcel(business=self.business, actor=self.user, shipment=self.sc, parcel=self.pc)
        self.assertIn(self.pc, self.parcels())
        manifest = generate_manifest(business=self.business, actor=self.staff, shipment=self.sc)
        self.assertEqual(
            [row["tracking_code"] for row in manifest["parcels"]], [self.pc.tracking_code]
        )

    def test_shipment_cargo_expected_at_authorized_site_and_existing_lifecycle(self):
        assign_parcel(business=self.business, actor=self.user, shipment=self.sa, parcel=self.pc)
        self.assertIn(self.pc, self.parcels())
        change_parcel_status(
            business=self.business, actor=self.staff, parcel=self.pc, status=Parcel.Status.RECEIVED
        )
        change_shipment_status(
            business=self.business, actor=self.staff, shipment=self.sa, status=Shipment.Status.READY
        )
        self.sa.refresh_from_db()
        change_shipment_status(
            business=self.business,
            actor=self.staff,
            shipment=self.sa,
            status=Shipment.Status.IN_TRANSIT,
        )
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.current_status, Parcel.Status.IN_TRANSIT)
        self.assertEqual(ParcelEvent.objects.filter(parcel=self.pc, status="IN_TRANSIT").count(), 1)

    def test_scanner_and_direct_urls_exports_search_do_not_reveal_other_sites(self):
        self.login_worker()
        self.assertEqual(
            resolve_scanned_parcel(
                business=self.business, actor=self.staff, code=self.pa.tracking_code
            ).pk,
            self.pa.pk,
        )
        # Camera and manual input share this exact resolver.
        for code in (self.pc.tracking_code, self.legacy.tracking_code):
            self.assertIsNone(
                resolve_scanned_parcel(business=self.business, actor=self.staff, code=code)
            )
        for name, pk in (
            ("logistics_parcel_detail", self.pc.pk),
            ("logistics_shipment_detail", self.sc.pk),
            ("logistics_shipment_manifest", self.sc.pk),
        ):
            self.assertEqual(
                self.client.get(reverse(name, args=[pk]), {"download": "csv"}).status_code, 404
            )
        response = self.client.get(reverse("logistics_parcel_list"))
        self.assertContains(response, self.pa.tracking_code)
        self.assertNotContains(response, self.pc.tracking_code)
        response = self.client.get(reverse("logistics_parcel_list"), {"q": self.pc.tracking_code})
        self.assertFalse(response.context["page_obj"].object_list.exists())
        self.assertEqual(
            self.client.post(
                reverse("logistics_parcel_update", args=[self.pc.pk]), {"status": "RECEIVED"}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("logistics_shipment_manifest", args=[self.sa.pk]), {"download": "csv"}
            ).status_code,
            200,
        )

    def test_dashboard_counts_and_events_are_scoped(self):
        change_parcel_status(
            business=self.business, actor=self.user, parcel=self.pa, status="RECEIVED"
        )
        change_parcel_status(
            business=self.business, actor=self.user, parcel=self.pc, status="RECEIVED"
        )
        context = get_logistics_dashboard_context(
            business=self.business, actor=self.staff, membership=self.member, now=timezone.now()
        )
        self.assertEqual(context["parcel_count"], 1)
        self.assertEqual(context["shipment_count"], 1)
        self.assertTrue(
            all(event.parcel_id == self.pa.pk for event in context["recent_tracking_events"])
        )
        self.login_worker()
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.pc.tracking_code)

    def test_selectors_are_scoped_but_shared_clients_remain_available(self):
        form = ParcelRegistrationForm(business=self.business, actor=self.staff)
        self.assertEqual(set(form.fields["origin_location"].queryset), {self.a})
        self.assertIn(self.customer, form.fields["client"].queryset)
        form = ShipmentAssignmentForm(business=self.business, actor=self.staff)
        self.assertEqual(set(form.fields["parcel"].queryset), {self.pa})
        form = ShipmentForm(business=self.business, actor=self.staff, allow_assignment=True)
        self.assertEqual(set(form.fields["parcel"].queryset), {self.pa})
        form = ParcelEditForm(business=self.business, actor=self.staff, instance=self.pa)
        self.assertTrue(form.fields["origin_location"].disabled)

    def test_inactive_or_revoked_grants_and_memberships_fail_closed(self):
        self.a.is_active = False
        self.a.save()
        self.assertFalse(self.parcels().exists())
        with self.assertRaises(PermissionDenied):
            change_parcel_status(
                business=self.business, actor=self.staff, parcel=self.pa, status="RECEIVED"
            )
        self.a.is_active = True
        self.a.save()
        self.member.is_active = False
        self.member.save()
        with self.assertRaises(PermissionDenied):
            self.parcels()

    def test_only_owner_admin_manage_grants_review_and_stops(self):
        for operation in (
            lambda: self.grant(self.foreign),
            lambda: set_handling_site(
                business=self.business,
                actor=self.user,
                parcel=self.pc,
                location=self.foreign,
                kind="STOP",
            ),
        ):
            with self.assertRaises(ValidationError):
                operation()
        for operation in (
            lambda: set_location_assignment(
                business=self.business, actor=self.staff, membership=self.member, location=self.b
            ),
            lambda: review_location_access(business=self.business, actor=self.staff),
            lambda: set_handling_site(
                business=self.business,
                actor=self.staff,
                parcel=self.pc,
                location=self.a,
                kind="STOP",
            ),
        ):
            with self.assertRaises(PermissionDenied):
                operation()
        self.membership.role = BusinessUser.Role.ADMIN
        self.membership.save()
        self.grant(self.b)
        self.assertEqual(parcels_for_business(business=self.business, actor=self.user).count(), 3)

    def test_assignment_duplicate_constraints_and_tenant_validation(self):
        with self.assertRaises(ValidationError):
            LogisticsLocationAssignment(
                business=self.business, membership=self.member, location=self.foreign
            ).save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LogisticsLocationAssignment.objects.bulk_create(
                [
                    LogisticsLocationAssignment(
                        business=self.business, membership=self.member, location=self.a
                    )
                ]
            )
        with self.assertRaises(ValidationError):
            LogisticsHandlingSite(
                business=self.business,
                location=self.a,
                parcel=self.pa,
                shipment=self.sa,
                kind="STOP",
            ).save()
        self.assertFalse(find_unregistered_direct_business_relations())
        inventory = build_business_data_inventory(self.business)
        self.assertIsNotNone(inventory)

    def test_shared_client_page_hides_restricted_parcels(self):
        self.login_worker()
        response = self.client.get(reverse("staff_client_detail", args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.pa.tracking_code)
        self.assertNotContains(response, self.pc.tracking_code)

    def test_access_settings_csrf_and_work_location_server_validation(self):
        response = self.client.get(reverse("logistics_location_access"))
        self.assertEqual(response.status_code, 200)
        form = LocationAssignmentForm(business=self.business)
        self.assertNotIn(self.foreign, form.fields["location"].queryset)
        strict = HttpClient(enforce_csrf_checks=True)
        strict.force_login(self.user)
        session = strict.session
        from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.assertEqual(
            strict.post(
                reverse("logistics_location_access"), {"action": "review", "confirm_review": "yes"}
            ).status_code,
            403,
        )
        self.login_worker()
        self.assertEqual(self.client.get(reverse("logistics_location_access")).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("logistics_work_location"), {"location": self.foreign.pk}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("logistics_work_location"), {"location": self.a.pk}
            ).status_code,
            302,
        )

    def test_demo_reset_preserves_user_created_handling_associations(self):
        set_handling_site(
            business=self.business, actor=self.user, parcel=self.pa, location=self.a, kind="CURRENT"
        )
        with self.assertRaises(DemoSeedResetError):
            _validate_no_genuine_dependents(object_pks={"logistics.Parcel": (self.pa.pk,)})

    def test_service_staff_do_not_need_logistics_locations(self):
        BusinessUser.objects.create(
            business=self.service, user=self.staff, role=BusinessUser.Role.STAFF
        )
        self.login_worker()
        self.switch(self.service)
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Active work location")
        self.assertNotContains(response, "Logistics operational access requires")

    def test_shared_invoice_html_pdf_redact_only_restricted_operational_references(self):
        import uuid

        from apps.billings.models import InvoiceLine

        from .billing_services import add_charge, invoice_charges

        charge = add_charge(
            business=self.business,
            actor=self.user,
            parcel=self.pc,
            description="Handling",
            unit_price=25,
            idempotency_key=uuid.uuid4(),
        )
        invoice = invoice_charges(business=self.business, actor=self.user, charge_ids=[charge.pk])
        line = InvoiceLine.objects.get(invoice=invoice)
        original = line.description
        self.assertIn(self.pc.tracking_code, original)
        self.login_worker()
        response = self.client.get(reverse("invoice_detail", args=[invoice.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "25.00")
        self.assertNotContains(response, self.pc.tracking_code)
        self.assertNotContains(response, reverse("logistics_parcel_detail", args=[self.pc.pk]))
        response = self.client.get(reverse("invoice_pdf_download", args=[invoice.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.pc.tracking_code.encode(), response.content)
        line.refresh_from_db()
        self.assertEqual(line.description, original)
        self.client.force_login(self.user)
        response = self.client.get(reverse("invoice_detail", args=[invoice.pk]))
        self.assertContains(response, self.pc.tracking_code)

    def test_readers_still_have_finance_permissions_without_operational_grants(self):
        for role in (BusinessUser.Role.ACCOUNTANT, BusinessUser.Role.VIEWER):
            self.member.role = role
            self.member.save(update_fields=["role"])
            self.assertEqual(set(self.parcels()), {self.pa})
            with self.assertRaises(PermissionDenied):
                change_parcel_status(
                    business=self.business, actor=self.staff, parcel=self.pa, status="RECEIVED"
                )

    def test_registration_replay_after_site_revoke_is_denied(self):
        import uuid

        key = uuid.uuid4()
        data = dict(self.fields, origin_location=self.a)
        parcel = register_parcel(
            business=self.business,
            actor=self.staff,
            client=self.customer,
            idempotency_key=key,
            **data,
        )
        self.assertEqual(
            register_parcel(
                business=self.business,
                actor=self.staff,
                client=self.customer,
                idempotency_key=key,
                **data,
            ).pk,
            parcel.pk,
        )
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=self.member,
            location=self.a,
            revoke=True,
        )
        with self.assertRaises(PermissionDenied):
            register_parcel(
                business=self.business,
                actor=self.staff,
                client=self.customer,
                idempotency_key=key,
                **data,
            )

    def test_inactive_membership_grants_can_be_revoked_without_reactivation(self):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError):
            self.grant(self.b)
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=self.member,
            location=self.a,
            revoke=True,
        )
        self.assertFalse(
            LogisticsLocationAssignment.objects.filter(membership=self.member).exists()
        )
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
