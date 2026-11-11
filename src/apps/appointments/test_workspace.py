"""Integration boundaries for the standard Services appointments workspace."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.billings.models import Invoice, InvoiceLine, InvoicePayment
from apps.billings.services import create_invoice_for_client
from apps.businesses.models import Business, BusinessSubscription, ClarivoPlan
from apps.businesses.test_service_allowances import ServicesFixture
from apps.businesses.utils import get_business_usage_count
from apps.crm.models import ActivityLog, BusinessService, Client, Lead

from .models import Appointment


class UnifiedWorkspaceTests(ServicesFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def lead(self, **overrides):
        return Lead.objects.create(
            **{
                "business": self.business,
                "lead_type": "REQUEST",
                "status": "NEW",
                "first_name": "Request",
                "last_name": "Customer",
                "email": self.customer.email,
                "phone": self.customer.phone,
                "company_name": "Request company",
                "request_source": "public_booking",
                "requested_service": self.service,
                **overrides,
            }
        )

    def workspace(self, **filters):
        response = self.client.get(reverse("appointment_list"), filters)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "appointments/workspace.html")
        return response

    def keys(self, response):
        return {(row["kind"], row["pk"]) for row in response.context["workspace_page"]}

    def appointment_payload(self, **overrides):
        return {
            "operation_key": str(uuid4()),
            "title": "Internal visit",
            "client": self.customer.pk,
            "service": self.service.pk,
            "start_time": self.start.strftime("%Y-%m-%dT%H:%M"),
            "end_time": (self.start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            **overrides,
        }

    def test_internal_creation_reuses_form_and_operation_and_appears_once(self):
        from .forms import AppointmentForm

        for role in ("owner", "staff"):
            with self.subTest(role=role):
                self.member.role = role
                self.member.save(update_fields=["role"])
                self.assertContains(self.workspace(), ">New Appointment</a>")
                url = reverse("appointment_create")
                form_page = self.client.get(url)
                self.assertIsInstance(form_page.context["form"], AppointmentForm)
                self.assertContains(form_page, 'id="draftClientModal"')
                payload = self.appointment_payload(title=f"{role} visit")
                response = self.client.post(url, payload)
                appointment = Appointment.objects.get(title=payload["title"])
                self.assertRedirects(response, reverse("appointment_detail", args=[appointment.pk]))
                self.assertEqual(self.client.post(url, payload).status_code, 302)
                rows = list(self.workspace().context["workspace_page"])
                self.assertEqual(sum(row["pk"] == appointment.pk for row in rows), 1)
                self.assertEqual(Appointment.objects.filter(title=payload["title"]).count(), 1)
                self.assertEqual(appointment.client, self.customer)
        self.assertEqual(Lead.objects.count(), 0)

    def test_internal_follow_up_creation_returns_to_workspace_without_a_date(self):
        response = self.client.get(reverse("staff_lead_create"))
        self.assertEqual(response.context["form"].initial["lead_type"], "REQUEST")
        response = self.client.post(
            reverse("staff_lead_create"),
            {
                "lead_type": "REQUEST",
                "status": "NEW",
                "first_name": "Internal",
                "last_name": "Customer",
                "email": self.customer.email,
                "company_name": self.customer.company_name,
                "phone": self.customer.phone,
                "is_active": "on",
                "request_source": "public_booking",
            },
        )
        self.assertRedirects(response, reverse("appointment_list"))
        lead = Lead.objects.get()
        self.assertIsNone(lead.preferred_start_time)
        self.assertEqual(lead.request_source, "staff")
        self.assertEqual(self.keys(self.workspace(source="internal")), {("request", lead.pk)})
        self.assertFalse(Appointment.objects.exists())

    def test_scheduling_follow_up_preserves_client_classification_and_request_history(self):
        for classification in ("LEAD", "ACTIVE"):
            with self.subTest(classification=classification):
                self.customer.client_status = classification
                self.customer.save(update_fields=["client_status"])
                lead = self.lead(status="CONTACTED", notes="Original follow-up history")
                before = Lead.objects.filter(pk=lead.pk).values().get()
                payload = self.appointment_payload(title=f"Scheduled {classification}")
                response = self.client.post(
                    reverse("appointment_create_from_request", args=[lead.pk]), payload
                )
                appointment = Appointment.objects.get(source_lead=lead)
                self.assertRedirects(response, reverse("appointment_detail", args=[appointment.pk]))
                self.assertEqual(Lead.objects.filter(pk=lead.pk).values().get(), before)
                self.customer.refresh_from_db()
                self.assertEqual(self.customer.client_status, classification)
                self.assertEqual(appointment.client, self.customer)
                self.assertNotIn(("request", lead.pk), self.keys(self.workspace()))
                self.assertIn(("appointment", appointment.pk), self.keys(self.workspace()))
                self.assertEqual(
                    self.client.get(reverse("staff_lead_detail", args=[lead.pk])).status_code, 200
                )

    def test_public_follow_up_does_not_downgrade_active_client(self):
        self.customer.client_status = "ACTIVE"
        self.customer.save(update_fields=["client_status"])
        payload = self.payload(
            booking_intent="book_later",
            email=self.customer.email,
            preferred_date="",
            preferred_time="",
            staff_member="",
        )
        self.assertEqual(
            self.client.post(
                reverse("public_booking", args=[self.business.slug]), payload
            ).status_code,
            302,
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.client_status, "ACTIVE")
        self.assertEqual(Client.objects.filter(email=self.customer.email).count(), 1)
        self.assertEqual(len(self.workspace(state="needs_follow_up").context["workspace_page"]), 1)

    def test_appointment_entitlement_does_not_grant_request_entitlement(self):
        # Current plans include requests as a core module; exercise the independent
        # entitlement boundary without changing the catalog or capability policy.
        original = ClarivoPlan.allows_module

        def allows_module(plan, name):
            return name != "service_requests" and original(plan, name)

        self.lead()
        appointment = self.appointment()
        with patch.object(ClarivoPlan, "allows_module", allows_module):
            response = self.workspace()
            self.assertEqual(self.keys(response), {("appointment", appointment.pk)})
            self.assertNotContains(response, ">Create Request</a>")
            self.assertNotContains(response, ">Request history</a>")
            self.assertEqual(self.client.post(reverse("staff_lead_create"), {}).status_code, 302)

    def test_online_internal_and_undated_requests_share_workspace(self):
        scheduled_request = self.lead()
        online = self.appointment(source_lead=scheduled_request)
        direct = self.appointment(title="Internal appointment")
        callback = self.lead(email="callback@example.test")
        internal = self.lead(request_source="staff", preferred_start_time=None)
        response = self.workspace()
        self.assertEqual(
            self.keys(response),
            {
                ("appointment", online.pk),
                ("appointment", direct.pk),
                ("request", callback.pk),
                ("request", internal.pk),
            },
        )
        self.assertEqual(
            sum(row["state"] == "Needs follow-up" for row in response.context["workspace_page"]),
            2,
        )
        self.assertContains(response, "Not scheduled", count=2)
        callback.refresh_from_db()
        self.assertIsNone(callback.preferred_start_time)
        self.assertEqual(Appointment.objects.count(), 2)

    def test_multiple_appointments_survive_and_linked_request_is_not_duplicated(self):
        request = self.lead()
        first = self.appointment(source_lead=request)
        second = self.appointment(source_lead=request, status="cancelled")
        self.assertEqual(
            self.keys(self.workspace()),
            {
                ("appointment", first.pk),
                ("appointment", second.pk),
            },
        )
        self.assertFalse(self.keys(self.workspace(state="needs_follow_up")))

    def test_only_active_open_service_requests_require_follow_up(self):
        wanted = self.lead(status="CONTACTED")
        for attributes in (
            {"status": "CLOSED"},
            {"status": "INVOICED"},
            {"lead_type": "INTEREST"},
            {"is_active": False},
        ):
            self.lead(**attributes)
        self.assertEqual(self.keys(self.workspace()), {("request", wanted.pk)})

    def test_source_filters_do_not_invent_historical_provenance(self):
        online = self.lead(request_source="public_request")
        internal = self.lead(request_source="staff")
        blank = self.lead(request_source="")
        direct = self.appointment()
        linked = self.appointment(source_lead=internal)
        self.assertEqual(self.keys(self.workspace(source="online")), {("request", online.pk)})
        self.assertEqual(self.keys(self.workspace(source="internal")), {("appointment", linked.pk)})
        self.assertEqual(
            self.keys(self.workspace(source="unknown")),
            {
                ("request", blank.pk),
                ("appointment", direct.pk),
            },
        )

    def test_classification_uses_appointment_client_and_unambiguous_tenant_email(self):
        self.customer.client_status = "LEAD"
        self.customer.save(update_fields=["client_status"])
        request = self.lead(email=f"  {self.customer.email.upper()}  ")
        appointment = self.appointment()
        self.assertEqual(
            self.keys(self.workspace(classification="LEAD")),
            {
                ("request", request.pk),
                ("appointment", appointment.pk),
            },
        )
        self.new_client(email=self.customer.email, client_status="ACTIVE")
        self.assertEqual(
            self.keys(self.workspace(classification="LEAD")), {("appointment", appointment.pk)}
        )
        self.assertEqual(
            self.keys(self.workspace(classification="unknown")), {("request", request.pk)}
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.client_status, "LEAD")

    def test_staff_service_search_state_and_legacy_status_filters(self):
        request = self.lead()
        appointment = self.appointment(staff_member=self.owner, service=self.service)
        self.assertEqual(
            self.keys(self.workspace(staff=self.owner.pk)), {("appointment", appointment.pk)}
        )
        self.assertEqual(
            self.keys(self.workspace(service=self.service.pk)),
            {
                ("request", request.pk),
                ("appointment", appointment.pk),
            },
        )
        self.assertEqual(self.keys(self.workspace(q="Visit")), {("appointment", appointment.pk)})
        self.assertEqual(
            self.keys(self.workspace(status="scheduled")), {("appointment", appointment.pk)}
        )
        self.assertEqual(
            self.keys(self.workspace(state="needs_follow_up")), {("request", request.pk)}
        )

    def test_cross_tenant_records_choices_and_filter_ids_are_isolated(self):
        other = Business.objects.create(name="Other", slug="other-workspace")
        foreign_service = BusinessService.objects.create(
            business=other, name="Private foreign service"
        )
        self.lead(business=other, first_name="Foreign secret", requested_service=foreign_service)
        self.lead(requested_service=foreign_service)
        response = self.workspace()
        self.assertNotContains(response, "Foreign secret")
        self.assertNotContains(response, "Private foreign service")
        response = self.workspace(service=foreign_service.pk)
        self.assertFalse(self.keys(response))
        self.assertTrue(response.context["workspace_form"].errors)
        outsider = self.user()
        self.assertFalse(self.keys(self.workspace(staff=outsider.pk)))

    def test_public_booking_semantics_and_retry_are_unchanged(self):
        now = self.payload()
        url = reverse("public_booking", args=[self.business.slug])
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(url, now).status_code, 302)
        lead = Lead.objects.get(business=self.business, email=now["email"])
        appointment = Appointment.objects.get(source_lead=lead)
        sent = len(mail.outbox)
        self.assertEqual(lead.status, "NEW")
        self.assertEqual(appointment.status, "scheduled")
        self.assertEqual(self.keys(self.workspace()), {("appointment", appointment.pk)})
        self.assertEqual(self.client.post(url, now).status_code, 302)
        self.assertEqual(len(mail.outbox), sent)
        callback = self.payload(
            booking_intent="book_later",
            email="undated-public@example.test",
            preferred_date="",
            preferred_time="",
            staff_member="",
        )
        self.assertEqual(self.client.post(url, callback).status_code, 302)
        request = Lead.objects.get(email=callback["email"])
        self.assertIsNone(request.preferred_start_time)
        self.assertEqual(Client.objects.get(email=callback["email"]).client_status, "LEAD")
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(
            self.keys(self.workspace(state="needs_follow_up")), {("request", request.pk)}
        )

    def test_invalid_filters_fail_closed(self):
        self.lead()
        for filters in (
            {"state": "bad"},
            {"source": "bad"},
            {"staff": "bad"},
            {"classification": "bad"},
            {"service": "bad"},
        ):
            with self.subTest(filters=filters):
                self.assertFalse(self.keys(self.workspace(**filters)))

    def test_request_only_plan_retains_list_detail_edit_and_create_access(self):
        hidden = self.appointment()
        request = self.lead()
        self.limit(allow_appointments=False, allow_public_booking=False)
        response = self.workspace()
        self.assertEqual(self.keys(response), {("request", request.pk)})
        self.assertContains(response, "Create Request")
        self.assertNotContains(response, 'href="/appointments/create/"')
        self.assertNotContains(response, f"/appointments/{hidden.pk}/")
        self.assertContains(response, "All Bookings &amp; Requests")
        for name, args in (
            ("staff_lead_create", []),
            ("staff_lead_detail", [request.pk]),
            ("staff_lead_update", [request.pk]),
            ("staff_lead_list", []),
        ):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        self.assertEqual(self.client.get(reverse("appointment_create")).status_code, 302)
        self.assertEqual(
            self.client.get(reverse("appointment_detail", args=[hidden.pk])).status_code, 302
        )
        self.assertEqual(
            self.client.post(
                reverse("appointment_change_status", args=[hidden.pk]), {"status": "completed"}
            ).status_code,
            302,
        )
        hidden.refresh_from_db()
        self.assertEqual(hidden.status, "scheduled")

    def test_read_only_roles_see_work_without_mutation_controls(self):
        self.lead()
        appointment = self.appointment()
        for role in ("accountant", "viewer"):
            self.member.role = role
            self.member.save(update_fields=["role"])
            response = self.workspace()
            self.assertNotContains(response, ">Create Request</a>")
            self.assertNotContains(response, ">New Appointment</a>")
            self.assertNotContains(response, ">Edit</a>")
            self.assertEqual(
                self.client.post(
                    reverse("appointment_change_status", args=[appointment.pk]),
                    {"status": "completed"},
                ).status_code,
                302,
            )

    def test_staff_can_reuse_existing_request_and_scheduling_actions(self):
        self.member.role = "staff"
        self.member.save(update_fields=["role"])
        request = self.lead()
        response = self.workspace()
        self.assertContains(response, reverse("staff_lead_detail", args=[request.pk]))
        self.assertContains(response, reverse("staff_lead_update", args=[request.pk]))
        self.assertEqual(
            self.client.get(
                reverse("appointment_create_from_request", args=[request.pk])
            ).status_code,
            200,
        )

    def test_inactive_membership_and_anonymous_access_are_denied(self):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(reverse("appointment_list")).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("appointment_list")).status_code, 302)

    def test_restricted_subscription_cannot_write_and_unavailable_subscription_cannot_read(self):
        self.lead()
        self.subscription.status = "past_due"
        self.subscription.plan = ClarivoPlan.objects.get(slug="starter")
        self.subscription.payment_provider = "stripe"
        self.subscription.billing_interval = "monthly"
        self.subscription.billing_currency = BusinessSubscription.BillingCurrency.USD
        self.subscription.provider_customer_id = "cus_workspace_test"
        self.subscription.provider_subscription_id = "sub_workspace_test"
        self.subscription.provider_price_id = "price_workspace_test"
        self.subscription.past_due_since = timezone.now() - timedelta(days=10)
        self.subscription.grace_period_ends_at = timezone.now() - timedelta(days=3)
        self.subscription.save()
        self.assertTrue(
            self.subscription.has_restricted_access, self.subscription.effective_access_status
        )
        response = self.workspace()
        self.assertNotContains(response, ">Create Request</a>")
        self.assertEqual(self.client.post(reverse("staff_lead_create"), {}).status_code, 302)
        self.subscription.delete()
        self.assertEqual(self.client.get(reverse("appointment_list")).status_code, 302)

    def test_dashboard_counts_only_unlinked_open_work_and_retains_historical_totals(self):
        scheduled = self.lead()
        self.appointment(source_lead=scheduled)
        self.appointment(source_lead=scheduled, status="cancelled")
        self.lead()
        self.lead(request_source="staff", status="CONTACTED")
        self.lead(status="CLOSED")
        self.lead(is_active=False)
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.context["open_service_request_count"], 2)
        self.assertEqual(response.context["new_service_request_count"], 1)
        self.assertEqual(response.context["public_booking_pending_review_count"], 1)
        self.assertEqual(response.context["service_request_count"], 5)
        self.assertContains(response, "/appointments/?state=needs_follow_up")
        scheduled.refresh_from_db()
        self.assertEqual(scheduled.status, "NEW")

    def test_workspace_get_preserves_domain_records_notifications_and_quota_usage(self):
        request = self.lead()
        appointment = self.appointment(source_lead=request, service=self.service)
        invoice = create_invoice_for_client(
            actor=self.owner, client=self.customer, appointment=appointment
        )
        models = (
            Lead,
            Client,
            Appointment,
            Invoice,
            InvoiceLine,
            InvoicePayment,
            ActivityLog,
            BusinessSubscription,
            ClarivoPlan,
        )
        before = {model: list(model.objects.order_by("pk").values()) for model in models}
        usage = get_business_usage_count(self.business, "appointments_per_month")
        sent = len(mail.outbox)
        response = self.workspace()
        self.assertEqual(len(response.context["workspace_page"]), 1)
        for model in models:
            self.assertEqual(list(model.objects.order_by("pk").values()), before[model])
        self.assertEqual(len(mail.outbox), sent)
        self.assertEqual(get_business_usage_count(self.business, "appointments_per_month"), usage)
        detail = self.client.get(reverse("appointment_detail", args=[appointment.pk]))
        self.assertContains(detail, reverse("invoice_detail", args=[invoice.pk]))

    def test_pagination_preserves_filters(self):
        for index in range(51):
            self.lead(first_name=f"Request {index}")
        response = self.workspace(state="needs_follow_up", page=2)
        self.assertEqual(len(response.context["workspace_page"]), 1)
        self.assertContains(response, "state=needs_follow_up&amp;page=1")

    def test_logistics_cannot_access_workspace_and_keeps_navigation(self):
        self.business.vertical = "LOGISTICS"
        self.business.save(update_fields=["vertical"])
        plan = ClarivoPlan.objects.get(slug="logistics-core")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        self.subscription.plan = plan
        self.subscription.billing_interval = "yearly"
        self.subscription.save(update_fields=["plan", "billing_interval"])
        self.assertEqual(self.client.get(reverse("appointment_list")).status_code, 302)
        response = self.client.get(reverse("agent_dashboard"))
        self.assertNotContains(response, "All Bookings &amp; Requests")
        self.assertNotContains(response, "data-unified-workspace")

    def test_existing_legacy_lead_list_keeps_interest_and_closed_history(self):
        lead = self.lead(lead_type="INTEREST", status="CLOSED")
        response = self.client.get(reverse("staff_lead_list"), {"status_group": "all"})
        self.assertContains(response, reverse("staff_lead_detail", args=[lead.pk]))
        self.assertTemplateUsed(response, "crm/main/lead_list.html")
