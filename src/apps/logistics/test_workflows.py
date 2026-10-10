"""Connected Logistics workflows with tenant, lifecycle and access regressions."""

import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.businesses.models import BusinessSubscription, BusinessUser, ClarivoPlan
from apps.crm.models import Client

from . import test_shipments as shipment_fixtures
from . import test_workspace as fixtures
from .models import Parcel, Shipment
from .parcel_services import register_parcel
from .shipment_forms import ShipmentAssignmentForm


class LogisticsWorkflowTests(TestCase):
    setUp = fixtures.LogisticsWorkspaceTests.setUp
    switch = fixtures.LogisticsWorkspaceTests.switch
    parcel = fixtures.LogisticsWorkspaceTests.parcel
    shipment = fixtures.LogisticsWorkspaceTests.shipment
    dashboard = fixtures.LogisticsWorkspaceTests.dashboard
    write_post = shipment_fixtures.ShipmentTests.write_post

    def client_data(self, **overrides):
        return {
            "workflow": "parcel",
            "new_client-first_name": "New",
            "new_client-last_name": "Customer",
            "new_client-company_name": "New Company",
            "new_client-email": "new-client@example.com",
            "new_client-phone": "+599 1234567",
            "new_client-street_address": "10 Main Street",
            **overrides,
        }

    def test_inline_client_creation_reuses_crm_and_returns_selected_same_tenant_client(self):
        response = self.client.get(reverse("logistics_parcel_register"))
        self.assertContains(response, "data-parcel-client-form")
        self.assertContains(response, reverse("staff_client_create"))
        response = self.client.post(
            reverse("staff_client_create"), self.client_data(business=self.other.pk, created_by=999)
        )
        self.assertEqual(response.status_code, 201)
        customer = Client.objects.get(email="new-client@example.com")
        self.assertEqual(customer.business_id, self.business.pk)
        self.assertContains(
            response, f'value="{customer.pk}" selected data-created-client', status_code=201
        )
        self.assertEqual(Parcel.objects.count(), 0)
        response = self.client.post(
            reverse("logistics_parcel_register"),
            {
                "client": customer.pk,
                "idempotency_key": uuid.uuid4(),
                "origin": "Saved origin",
                "destination": "Saved destination",
                "quantity": 2,
                "package_description": "Saved details",
            },
        )
        self.assertEqual(response.status_code, 302)
        parcel = Parcel.objects.get()
        self.assertEqual(parcel.client_id, customer.pk)
        self.assertEqual(parcel.business_id, self.business.pk)
        self.assertEqual(parcel.package_description, "Saved details")

    def test_inline_client_validation_preserves_values_and_creates_nothing(self):
        count = Client.objects.count()
        response = self.client.post(
            reverse("staff_client_create"),
            self.client_data(**{"new_client-email": "invalid", "new_client-phone": ""}),
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "data-client-fields", status_code=400)
        self.assertContains(response, 'value="New Company"', status_code=400)
        self.assertContains(response, "invalid-feedback d-block", status_code=400)
        self.assertEqual(Client.objects.count(), count)
        self.assertEqual(Parcel.objects.count(), 0)

    def test_inline_client_creation_rechecks_capacity_under_the_existing_lock(self):
        count = Client.objects.count()
        for limits in ([True], [False, True]):
            with patch("apps.crm.views.business_limit_reached", side_effect=limits):
                response = self.client.post(reverse("staff_client_create"), self.client_data())
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, "alert alert-danger", status_code=400)
            self.assertEqual(Client.objects.count(), count)

    def test_inline_client_flow_respects_roles_vertical_and_subscription(self):
        count = Client.objects.count()
        for role, status in ((BusinessUser.Role.ACCOUNTANT, 403), (BusinessUser.Role.VIEWER, 302)):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            self.assertEqual(
                self.client.post(reverse("staff_client_create"), self.client_data()).status_code,
                status,
            )
        self.membership.role = BusinessUser.Role.OWNER
        self.membership.save(update_fields=["role"])
        self.switch(self.service)
        self.assertEqual(
            self.client.post(reverse("staff_client_create"), self.client_data()).status_code, 403
        )
        self.switch(self.business)
        BusinessSubscription.objects.filter(business=self.business).update(status="suspended")
        self.assertEqual(
            self.client.post(reverse("staff_client_create"), self.client_data()).status_code, 302
        )
        self.assertEqual(Client.objects.count(), count)

    def test_client_preselection_is_tenant_scoped_and_survives_invalid_registration(self):
        url = reverse("logistics_parcel_register")
        response = self.client.get(url, {"client": self.customer.pk})
        self.assertEqual(response.context["form"]["client"].value(), self.customer.pk)
        for value in (self.other_customer.pk, "invalid", 999999):
            self.assertEqual(self.client.get(url, {"client": value}).status_code, 404)
        response = self.client.post(
            url,
            {
                "client": self.customer.pk,
                "idempotency_key": uuid.uuid4(),
                "origin": "Keep this",
                "quantity": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Keep this"')
        self.assertEqual(str(response.context["form"]["client"].value()), str(self.customer.pk))
        self.assertEqual(Parcel.objects.count(), 0)

    def test_logistics_client_detail_shows_scoped_recent_open_parcels_and_actions(self):
        parcel = self.parcel()
        delivered = self.parcel(status=Parcel.Status.DELIVERED)
        foreign = self.parcel(business=self.other, customer=self.other_customer)
        response = self.client.get(reverse("staff_client_detail", args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["client_parcel_count"], 2)
        self.assertEqual(list(response.context["client_open_parcels"]), [parcel])
        self.assertEqual(set(response.context["client_recent_parcels"]), {parcel, delivered})
        self.assertContains(
            response, f"{reverse('logistics_parcel_register')}?client={self.customer.pk}"
        )
        self.assertNotContains(response, foreign.tracking_code)
        self.assertEqual(
            self.client.get(
                reverse("staff_client_detail", args=[self.other_customer.pk])
            ).status_code,
            404,
        )
        from .location_test_support import approve_test_site

        approve_test_site(business=self.business, membership=self.membership, parcel=parcel)
        self.membership.role = BusinessUser.Role.VIEWER
        self.membership.save(update_fields=["role"])
        response = self.client.get(reverse("staff_client_detail", args=[self.customer.pk]))
        self.assertNotContains(
            response, f"{reverse('logistics_parcel_register')}?client={self.customer.pk}"
        )
        self.assertContains(response, parcel.tracking_code)

    def test_service_client_detail_is_unchanged_and_does_not_query_parcels(self):
        self.switch(self.service)
        customer = Client.objects.create(
            business=self.service, first_name="Service", last_name="Client"
        )
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("staff_client_detail", args=[customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get("logistics_client_parcels", False))
        self.assertNotContains(response, reverse("logistics_parcel_register"))
        self.assertFalse(any('"logistics_parcel"' in q["sql"] for q in queries))
        self.assertContains(response, "Appointments")

    def test_parcel_search_and_combined_filters_are_tenant_scoped(self):
        parcel = self.parcel()
        received = self.parcel(status=Parcel.Status.RECEIVED)
        foreign = self.parcel(business=self.other, customer=self.other_customer)
        url = reverse("logistics_parcel_list")
        for query in (parcel.tracking_code, "Miami", "Parcel", self.customer.email, "Books"):
            response = self.client.get(url, {"q": query})
            self.assertIn(parcel, response.context["page_obj"])
            self.assertNotContains(response, foreign.tracking_code)
        response = self.client.get(
            url, {"q": "Miami", "status": "RECEIVED", "client": self.customer.pk}
        )
        self.assertEqual(list(response.context["page_obj"]), [received])
        for filters in (
            {"q": foreign.tracking_code},
            {"client": self.other_customer.pk},
            {"client": "bad"},
            {"status": "NOT_A_STATUS"},
        ):
            response = self.client.get(url, filters)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(list(response.context["page_obj"]), [])
            self.assertNotContains(
                response, f'href="{reverse("logistics_parcel_detail", args=[foreign.pk])}"'
            )
        choices = response.context["filter_form"].fields["client"].queryset
        self.assertNotIn(self.other_customer, choices)

    def test_parcel_pagination_preserves_search_status_and_client_filters(self):
        for index in range(51):
            register_parcel(
                business=self.business,
                actor=self.user,
                client=self.customer,
                origin="Miami",
                destination="Curaçao",
                package_description=f"Parcel {index}",
            )
        response = self.client.get(
            reverse("logistics_parcel_list"),
            {"q": "Miami", "status": "REGISTERED", "client": self.customer.pk, "page": 2},
        )
        self.assertEqual(len(response.context["page_obj"]), 1)
        self.assertContains(
            response, f"?q=Miami&amp;status=REGISTERED&amp;client={self.customer.pk}&amp;page=1"
        )

    def test_shipment_assignment_choices_are_eligible_tenant_scoped_and_contextual(self):
        registered = self.parcel()
        received = self.parcel(status=Parcel.Status.RECEIVED)
        transit = self.parcel(status=Parcel.Status.IN_TRANSIT)
        foreign = self.parcel(business=self.other, customer=self.other_customer)
        assigned = self.parcel()
        shipment = self.shipment()
        self.write_post("logistics_shipment_assign", {"parcel": assigned.pk}, shipment=shipment)
        form = ShipmentAssignmentForm(business=self.business)
        self.assertEqual(set(form.fields["parcel"].queryset), {registered, received})
        response = self.client.get(
            reverse("logistics_shipment_detail", args=[shipment.pk]), {"parcel": received.pk}
        )
        self.assertEqual(response.context["assignment_form"]["parcel"].value(), received.pk)
        self.assertContains(response, received.tracking_code)
        self.assertContains(response, self.customer.first_name)
        self.assertNotContains(response, transit.tracking_code)
        self.assertNotContains(response, foreign.tracking_code)
        for value in (foreign.pk, assigned.pk, transit.pk, "bad"):
            self.assertEqual(
                self.client.get(
                    reverse("logistics_shipment_create"), {"parcel": value}
                ).status_code,
                404,
            )
            response = self.write_post(
                "logistics_shipment_assign", {"parcel": value}, shipment=shipment
            )
            self.assertEqual(response.status_code, 302 if value == assigned.pk else 400)
        self.assertEqual(Parcel.objects.get(pk=foreign.pk).shipment_id, None)

    def test_create_and_edit_shipment_assign_using_existing_services(self):
        parcel = self.parcel()
        response = self.client.get(reverse("logistics_shipment_create"), {"parcel": parcel.pk})
        self.assertEqual(response.context["form"]["parcel"].value(), parcel.pk)
        self.assertEqual(response.context["form"]["origin"].value(), parcel.origin)
        response = self.write_post(
            "logistics_shipment_create",
            {"origin": "Miami", "destination": "Curaçao", "parcel": parcel.pk},
        )
        self.assertEqual(response.status_code, 302)
        shipment = Shipment.objects.get()
        parcel.refresh_from_db()
        self.assertEqual(parcel.shipment_id, shipment.pk)
        extra = self.parcel()
        response = self.write_post(
            "logistics_shipment_edit",
            {"origin": "Updated", "destination": "Curaçao", "parcel": extra.pk},
            shipment=shipment,
        )
        self.assertEqual(response.status_code, 302)
        extra.refresh_from_db()
        self.assertEqual(extra.shipment_id, shipment.pk)
        shipment.refresh_from_db()
        self.assertEqual(shipment.origin, "Updated")

    def test_assignment_failure_rolls_back_create_and_preserves_values(self):
        parcel = self.parcel()
        with patch(
            "apps.logistics.shipment_services.assign_parcel",
            side_effect=ValidationError("Parcel changed. Reload and try again."),
        ):
            response = self.write_post(
                "logistics_shipment_create",
                {
                    "origin": "Keep origin",
                    "destination": "Keep destination",
                    "notes": "Keep notes",
                    "parcel": parcel.pk,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parcel changed.")
        self.assertContains(response, 'value="Keep origin"')
        self.assertContains(response, "Keep notes")
        self.assertEqual(Shipment.objects.count(), 0)
        parcel.refresh_from_db()
        self.assertIsNone(parcel.shipment_id)

    def test_shipment_forms_reject_foreign_or_ineligible_parcels_atomically(self):
        foreign = self.parcel(business=self.other, customer=self.other_customer)
        transit = self.parcel(status=Parcel.Status.IN_TRANSIT)
        for parcel in (foreign, transit):
            response = self.write_post(
                "logistics_shipment_create",
                {"origin": "Miami", "destination": "Curaçao", "parcel": parcel.pk},
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
            self.assertEqual(Shipment.objects.count(), 0)
            parcel.refresh_from_db()
            self.assertIsNone(parcel.shipment_id)

    def test_assignment_failure_rolls_back_shipment_edit(self):
        shipment, parcel = self.shipment(), self.parcel()
        with patch(
            "apps.logistics.shipment_services.assign_parcel",
            side_effect=ValidationError("Parcel changed."),
        ):
            response = self.write_post(
                "logistics_shipment_edit",
                {
                    "origin": "Keep entered origin",
                    "destination": "Keep destination",
                    "parcel": parcel.pk,
                },
                shipment=shipment,
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Keep entered origin"')
        shipment.refresh_from_db()
        self.assertEqual(shipment.origin, "Miami")
        self.assertEqual(shipment.destination, "Curacao")
        parcel.refresh_from_db()
        self.assertIsNone(parcel.shipment_id)

    def test_stale_parcel_preselection_preserves_posted_shipment_values(self):
        parcel, shipment = self.parcel(), self.shipment()
        self.write_post("logistics_shipment_assign", {"parcel": parcel.pk}, shipment=shipment)
        response = self.client.post(
            f"{reverse('logistics_shipment_create')}?parcel={parcel.pk}",
            {"origin": "Keep this origin", "destination": "Keep destination", "parcel": parcel.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertContains(response, 'value="Keep this origin"')
        self.assertEqual(Shipment.objects.count(), 1)

    def test_assignment_actions_recheck_module_access_on_the_server(self):
        parcel = self.parcel()
        original = ClarivoPlan.allows_module
        with patch.object(
            ClarivoPlan,
            "allows_module",
            autospec=True,
            side_effect=lambda plan, module: (
                False if module == "parcels" else original(plan, module)
            ),
        ):
            response = self.client.get(reverse("logistics_shipment_create"))
            self.assertNotIn("parcel", response.context["form"].fields)
            response = self.write_post(
                "logistics_shipment_create",
                {"origin": "Miami", "destination": "Curacao", "parcel": parcel.pk},
            )
            self.assertEqual(response.status_code, 302)
            shipment = Shipment.objects.get()
            self.assertEqual(
                self.client.post(
                    reverse("logistics_shipment_assign", args=[shipment.pk]), {"parcel": parcel.pk}
                ).status_code,
                302,
            )
            self.assertEqual(
                self.client.post(reverse("staff_client_create"), self.client_data()).status_code,
                403,
            )
        parcel.refresh_from_db()
        self.assertIsNone(parcel.shipment_id)

    def test_empty_states_and_cross_links_are_actionable(self):
        response = self.client.get(reverse("logistics_shipment_create"))
        self.assertContains(response, "No parcels are currently eligible for this shipment.")
        parcel, shipment = self.parcel(), self.shipment()
        response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertContains(response, reverse("staff_client_detail", args=[self.customer.pk]))
        self.assertContains(response, f"{reverse('logistics_shipment_create')}?parcel={parcel.pk}")
        self.assertContains(response, f"{reverse('logistics_shipment_list')}?parcel={parcel.pk}")
        self.assertContains(response, 'method="post" action="/logistics/track/"')
        response = self.client.get(reverse("logistics_shipment_list"), {"parcel": parcel.pk})
        self.assertContains(
            response,
            f"{reverse('logistics_shipment_detail', args=[shipment.pk])}?parcel={parcel.pk}#assign-parcel",
        )
        self.write_post("logistics_shipment_assign", {"parcel": parcel.pk}, shipment=shipment)
        response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertContains(response, reverse("logistics_shipment_detail", args=[shipment.pk]))
        self.assertNotContains(
            response, f"{reverse('logistics_shipment_create')}?parcel={parcel.pk}"
        )
        response = self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk]))
        self.assertContains(response, reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertContains(response, "Weight (kg)")
        self.assertContains(response, "No parcels are currently eligible for this shipment.")

    def test_parcel_state_and_roles_control_actions_without_changing_lifecycle(self):
        parcel = self.parcel(status=Parcel.Status.DELIVERED)
        response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertNotContains(
            response, f"{reverse('logistics_shipment_create')}?parcel={parcel.pk}"
        )
        response = self.client.get(reverse("logistics_parcel_update", args=[parcel.pk]))
        self.assertEqual(
            response.context["form"].fields["status"].choices, [("", "Tracking note (keep status)")]
        )
        from .location_test_support import approve_test_site

        approve_test_site(business=self.business, membership=self.membership, parcel=parcel)
        self.membership.role = BusinessUser.Role.VIEWER
        self.membership.save(update_fields=["role"])
        response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertNotContains(response, reverse("logistics_parcel_update", args=[parcel.pk]))
        self.assertEqual(
            self.client.post(
                reverse("logistics_shipment_create"),
                {"origin": "Miami", "destination": "Curaçao", "parcel": parcel.pk},
            ).status_code,
            403,
        )

    def test_dashboard_keeps_the_three_quick_workflows(self):
        response = self.dashboard()
        for route in (
            "logistics_parcel_register",
            "logistics_shipment_create",
            "staff_client_create",
        ):
            self.assertContains(response, reverse(route))

    def test_logistics_pages_skip_service_dashboard_charts_and_service_loading_is_unchanged(self):
        for route, args in (
            ("logistics_parcel_register", []),
            ("logistics_shipment_create", []),
            ("staff_client_detail", [self.customer.pk]),
        ):
            response = self.client.get(reverse(route, args=args))
            self.assertNotContains(response, "assets/js/dashboards/crm-dashboard.js")
            if route != "staff_client_detail":
                self.assertContains(response, "assets/js/logistics-workflows.js")
        self.switch(self.service)
        customer = Client.objects.create(
            business=self.service, first_name="Service", last_name="Client"
        )
        response = self.client.get(reverse("staff_client_detail", args=[customer.pk]))
        self.assertContains(response, "assets/js/dashboards/crm-dashboard.js")
        self.assertNotContains(response, "assets/js/logistics-workflows.js")
