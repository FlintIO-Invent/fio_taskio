from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import BusinessService, Client

from .forms import AppointmentForm
from .models import Appointment


class AppointmentModelAndFormTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Alpha Workspace",
            slug="alpha-workspace",
        )
        self.other_business = Business.objects.create(
            name="Bravo Workspace",
            slug="bravo-workspace",
        )
        self.owner = TaskIOUser.objects.create_user(
            email="owner@example.com",
            password="testpass123",
            first_name="Owner",
            last_name="User",
        )
        self.staff_user = TaskIOUser.objects.create_user(
            email="staff@example.com",
            password="testpass123",
            first_name="Staff",
            last_name="User",
        )
        self.other_staff_user = TaskIOUser.objects.create_user(
            email="other-staff@example.com",
            password="testpass123",
            first_name="Other",
            last_name="Staff",
        )
        self.viewer_user = TaskIOUser.objects.create_user(
            email="viewer@example.com",
            password="testpass123",
            first_name="Viewer",
            last_name="User",
        )

        BusinessUser.objects.create(
            user=self.owner,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        BusinessUser.objects.create(
            user=self.staff_user,
            business=self.business,
            role=BusinessUser.Role.STAFF,
        )
        BusinessUser.objects.create(
            user=self.viewer_user,
            business=self.business,
            role=BusinessUser.Role.VIEWER,
        )
        BusinessUser.objects.create(
            user=self.other_staff_user,
            business=self.other_business,
            role=BusinessUser.Role.STAFF,
        )

        self.client_record = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="jamie@example.com",
            phone="+1 721 555 1000",
            company_name="Alpha Client Co",
            street_address="12 Main Street",
        )
        self.other_client_record = Client.objects.create(
            business=self.other_business,
            first_name="Taylor",
            last_name="Client",
            email="taylor@example.com",
            phone="+1 721 555 2000",
            company_name="Bravo Client Co",
            street_address="34 Side Street",
        )
        self.legacy_client_record = Client.objects.create(
            business=None,
            first_name="Legacy",
            last_name="Client",
            email="legacy@example.com",
            phone="+1 721 555 3000",
            company_name="Legacy Co",
            street_address="56 Archive Road",
        )
        self.service = BusinessService.objects.create(
            business=self.business,
            name="Septic Pumping",
            description="Routine pumping",
            unit_price=Decimal("150.00"),
            tax_rate=Decimal("6.50"),
        )
        self.inactive_service = BusinessService.objects.create(
            business=self.business,
            name="Inactive Pumping",
            description="Inactive service",
            unit_price=Decimal("99.00"),
            tax_rate=Decimal("6.50"),
            is_active=False,
        )
        self.other_service = BusinessService.objects.create(
            business=self.other_business,
            name="Roof Inspection",
            description="Roof inspection",
            unit_price=Decimal("225.00"),
            tax_rate=Decimal("10.00"),
        )
        self.start_time = timezone.now().replace(second=0, microsecond=0)
        self.end_time = self.start_time + timedelta(hours=2)

    def _appointment_payload(self, **overrides):
        payload = {
            "client": self.client_record.pk,
            "service": self.service.pk,
            "staff_member": self.staff_user.pk,
            "title": "Client site visit",
            "start_time": self.start_time.strftime("%Y-%m-%dT%H:%M"),
            "end_time": self.end_time.strftime("%Y-%m-%dT%H:%M"),
            "location": "Client office",
            "notes": "Bring service checklist.",
        }
        payload.update(overrides)
        return payload

    def test_appointment_requires_end_time_after_start_time(self):
        appointment = Appointment(
            business=self.business,
            client=self.client_record,
            title="Broken schedule",
            start_time=self.start_time,
            end_time=self.start_time,
        )

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_appointment_rejects_legacy_null_business_client(self):
        appointment = Appointment(
            business=self.business,
            client=self.legacy_client_record,
            title="Legacy client visit",
            start_time=self.start_time,
            end_time=self.end_time,
        )

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_appointment_stores_service_name_snapshot(self):
        appointment = Appointment.objects.create(
            business=self.business,
            client=self.client_record,
            service=self.service,
            staff_member=self.staff_user,
            title="Client site visit",
            start_time=self.start_time,
            end_time=self.end_time,
        )

        self.assertEqual(appointment.service_name, "Septic Pumping")

    def test_appointment_keeps_existing_service_name_when_service_name_changes_later(self):
        appointment = Appointment.objects.create(
            business=self.business,
            client=self.client_record,
            service=self.service,
            title="Client site visit",
            start_time=self.start_time,
            end_time=self.end_time,
        )

        self.service.name = "Updated Service Name"
        self.service.save()
        appointment.refresh_from_db()

        self.assertEqual(appointment.service_name, "Septic Pumping")

    def test_appointment_form_rejects_other_business_client(self):
        form = AppointmentForm(
            data=self._appointment_payload(client=self.other_client_record.pk),
            current_business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("client", form.errors)

    def test_appointment_form_rejects_other_business_service(self):
        form = AppointmentForm(
            data=self._appointment_payload(service=self.other_service.pk),
            current_business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("service", form.errors)

    def test_appointment_form_rejects_staff_member_from_other_business(self):
        form = AppointmentForm(
            data=self._appointment_payload(staff_member=self.other_staff_user.pk),
            current_business=self.business,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("staff_member", form.errors)

    def test_appointment_form_allows_current_business_records(self):
        form = AppointmentForm(
            data=self._appointment_payload(staff_member=self.viewer_user.pk),
            current_business=self.business,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_appointment_form_limits_client_queryset_to_active_current_business_clients(self):
        inactive_client = Client.objects.create(
            business=self.business,
            first_name="Inactive",
            last_name="Client",
            email="inactive@example.com",
            phone="+1 721 555 4000",
            company_name="Inactive Co",
            street_address="78 Hidden Lane",
            is_active=False,
        )

        form = AppointmentForm(current_business=self.business)

        self.assertIn(self.client_record, form.fields["client"].queryset)
        self.assertNotIn(self.other_client_record, form.fields["client"].queryset)
        self.assertNotIn(inactive_client, form.fields["client"].queryset)

    def test_appointment_form_limits_service_queryset_to_active_current_business_services(self):
        form = AppointmentForm(current_business=self.business)

        self.assertIn(self.service, form.fields["service"].queryset)
        self.assertNotIn(self.other_service, form.fields["service"].queryset)
        self.assertNotIn(self.inactive_service, form.fields["service"].queryset)

    def test_appointment_form_limits_staff_queryset_to_active_current_business_members(self):
        inactive_member_user = TaskIOUser.objects.create_user(
            email="inactive-member@example.com",
            password="testpass123",
            first_name="Inactive",
            last_name="Member",
        )
        BusinessUser.objects.create(
            user=inactive_member_user,
            business=self.business,
            role=BusinessUser.Role.STAFF,
            is_active=False,
        )

        form = AppointmentForm(current_business=self.business)

        self.assertIn(self.owner, form.fields["staff_member"].queryset)
        self.assertIn(self.staff_user, form.fields["staff_member"].queryset)
        self.assertIn(self.viewer_user, form.fields["staff_member"].queryset)
        self.assertNotIn(self.other_staff_user, form.fields["staff_member"].queryset)
        self.assertNotIn(inactive_member_user, form.fields["staff_member"].queryset)


class AppointmentViewTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Alpha Workspace",
            slug="alpha-workspace-view",
        )
        self.other_business = Business.objects.create(
            name="Bravo Workspace",
            slug="bravo-workspace-view",
        )
        self.appointments_plan = ClarivoPlan.objects.create(
            name="Appointments Enabled",
            slug="appointments-enabled-tests",
            allow_appointments=True,
        )
        self.locked_plan = ClarivoPlan.objects.create(
            name="Appointments Locked",
            slug="appointments-locked-tests",
            allow_appointments=False,
        )
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.appointments_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        BusinessSubscription.objects.create(
            business=self.other_business,
            plan=self.appointments_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        self.owner = TaskIOUser.objects.create_user(
            email="owner@example.com",
            password="testpass123",
            first_name="Owner",
            last_name="User",
        )
        self.admin_user = TaskIOUser.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
        )
        self.staff_user = TaskIOUser.objects.create_user(
            email="staff@example.com",
            password="testpass123",
            first_name="Staff",
            last_name="User",
        )
        self.accountant_user = TaskIOUser.objects.create_user(
            email="accountant@example.com",
            password="testpass123",
            first_name="Accountant",
            last_name="User",
        )
        self.viewer_user = TaskIOUser.objects.create_user(
            email="viewer@example.com",
            password="testpass123",
            first_name="Viewer",
            last_name="User",
        )
        self.other_owner = TaskIOUser.objects.create_user(
            email="other-owner@example.com",
            password="testpass123",
            first_name="Other",
            last_name="Owner",
        )

        BusinessUser.objects.create(
            user=self.owner,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        BusinessUser.objects.create(
            user=self.admin_user,
            business=self.business,
            role=BusinessUser.Role.ADMIN,
        )
        BusinessUser.objects.create(
            user=self.staff_user,
            business=self.business,
            role=BusinessUser.Role.STAFF,
        )
        BusinessUser.objects.create(
            user=self.accountant_user,
            business=self.business,
            role=BusinessUser.Role.ACCOUNTANT,
        )
        BusinessUser.objects.create(
            user=self.viewer_user,
            business=self.business,
            role=BusinessUser.Role.VIEWER,
        )
        BusinessUser.objects.create(
            user=self.other_owner,
            business=self.other_business,
            role=BusinessUser.Role.OWNER,
        )

        self.client_record = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="jamie@example.com",
            phone="+1 721 555 1000",
            company_name="Alpha Client Co",
            street_address="12 Main Street",
        )
        self.other_client_record = Client.objects.create(
            business=self.other_business,
            first_name="Taylor",
            last_name="Client",
            email="taylor@example.com",
            phone="+1 721 555 2000",
            company_name="Bravo Client Co",
            street_address="34 Side Street",
        )
        self.service = BusinessService.objects.create(
            business=self.business,
            name="Septic Pumping",
            description="Routine pumping",
            unit_price=Decimal("150.00"),
            tax_rate=Decimal("6.50"),
        )
        self.other_service = BusinessService.objects.create(
            business=self.other_business,
            name="Roof Inspection",
            description="Roof inspection",
            unit_price=Decimal("225.00"),
            tax_rate=Decimal("10.00"),
        )

        self.start_time = timezone.now().replace(second=0, microsecond=0)
        self.end_time = self.start_time + timedelta(hours=2)
        self.appointment = Appointment.objects.create(
            business=self.business,
            client=self.client_record,
            service=self.service,
            staff_member=self.staff_user,
            title="Client site visit",
            start_time=self.start_time,
            end_time=self.end_time,
            location="Client office",
        )
        self.other_appointment = Appointment.objects.create(
            business=self.other_business,
            client=self.other_client_record,
            service=self.other_service,
            staff_member=self.other_owner,
            title="Other workspace visit",
            start_time=self.start_time,
            end_time=self.end_time,
            location="Other office",
        )

    def _set_current_business_session(self, business):
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = business.id
        session.save()

    def _login_as(self, user, business):
        self._set_current_business_session(business)
        self.client.force_login(user)

    def _appointment_payload(self, **overrides):
        payload = {
            "client": self.client_record.pk,
            "service": self.service.pk,
            "staff_member": self.staff_user.pk,
            "title": "Scheduled service visit",
            "start_time": self.start_time.strftime("%Y-%m-%dT%H:%M"),
            "end_time": self.end_time.strftime("%Y-%m-%dT%H:%M"),
            "location": "Client warehouse",
            "notes": "Bring inspection notes.",
        }
        payload.update(overrides)
        return payload

    def test_appointment_list_only_shows_current_business_appointments(self):
        self._login_as(self.owner, self.business)

        response = self.client.get(reverse("appointment_list"))

        self.assertEqual(response.status_code, 200)
        appointments = list(response.context["appointments"])
        self.assertEqual(appointments, [self.appointment])

    def test_appointment_detail_blocks_other_business_appointment(self):
        self._login_as(self.owner, self.business)

        response = self.client.get(reverse("appointment_detail", args=[self.other_appointment.id]))

        self.assertEqual(response.status_code, 404)

    def test_appointment_update_blocks_other_business_appointment(self):
        self._login_as(self.owner, self.business)

        response = self.client.get(reverse("appointment_update", args=[self.other_appointment.id]))

        self.assertEqual(response.status_code, 404)

    def test_appointment_change_status_blocks_other_business_appointment(self):
        self._login_as(self.owner, self.business)

        response = self.client.post(
            reverse("appointment_change_status", args=[self.other_appointment.id]),
            data={"status": Appointment.Status.CANCELLED},
        )

        self.assertEqual(response.status_code, 404)

    def test_plan_with_appointments_enabled_can_access_appointment_routes(self):
        self._login_as(self.owner, self.business)

        response = self.client.get(reverse("appointment_list"))

        self.assertEqual(response.status_code, 200)

    def test_owner_is_redirected_to_subscription_when_appointments_are_locked(self):
        subscription = BusinessSubscription.objects.get(business=self.business)
        subscription.plan = self.locked_plan
        subscription.save(update_fields=["plan", "updated_at"])
        self._login_as(self.owner, self.business)

        response = self.client.get(reverse("appointment_list"), follow=True)

        self.assertRedirects(response, reverse("business_subscription"))
        self.assertContains(response, "Appointments is not included in the current workspace plan")

    def test_viewer_is_redirected_to_dashboard_when_appointments_are_locked(self):
        subscription = BusinessSubscription.objects.get(business=self.business)
        subscription.plan = self.locked_plan
        subscription.save(update_fields=["plan", "updated_at"])
        self._login_as(self.viewer_user, self.business)

        response = self.client.get(reverse("appointment_list"), follow=True)

        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertContains(response, "Appointments is not included in the current workspace plan")

    def test_owner_can_create_update_and_change_status(self):
        self._login_as(self.owner, self.business)

        create_response = self.client.post(
            reverse("appointment_create"),
            data=self._appointment_payload(business=self.other_business.pk),
        )
        created_appointment = Appointment.objects.get(title="Scheduled service visit")

        self.assertRedirects(
            create_response,
            reverse("appointment_detail", args=[created_appointment.id]),
        )
        self.assertEqual(created_appointment.business, self.business)

        update_response = self.client.post(
            reverse("appointment_update", args=[created_appointment.id]),
            data=self._appointment_payload(title="Updated service visit"),
        )
        created_appointment.refresh_from_db()

        self.assertRedirects(
            update_response,
            reverse("appointment_detail", args=[created_appointment.id]),
        )
        self.assertEqual(created_appointment.title, "Updated service visit")

        status_response = self.client.post(
            reverse("appointment_change_status", args=[created_appointment.id]),
            data={"status": Appointment.Status.COMPLETED},
        )
        created_appointment.refresh_from_db()

        self.assertRedirects(
            status_response,
            reverse("appointment_detail", args=[created_appointment.id]),
        )
        self.assertEqual(created_appointment.status, Appointment.Status.COMPLETED)

    def test_admin_can_create_update_and_change_status(self):
        self._login_as(self.admin_user, self.business)

        create_response = self.client.post(reverse("appointment_create"), data=self._appointment_payload(title="Admin visit"))
        appointment = Appointment.objects.get(title="Admin visit")
        self.assertRedirects(create_response, reverse("appointment_detail", args=[appointment.id]))

        update_response = self.client.post(
            reverse("appointment_update", args=[appointment.id]),
            data=self._appointment_payload(title="Admin updated visit"),
        )
        appointment.refresh_from_db()
        self.assertRedirects(update_response, reverse("appointment_detail", args=[appointment.id]))
        self.assertEqual(appointment.title, "Admin updated visit")

        status_response = self.client.post(
            reverse("appointment_change_status", args=[appointment.id]),
            data={"status": Appointment.Status.CANCELLED},
        )
        appointment.refresh_from_db()
        self.assertRedirects(status_response, reverse("appointment_detail", args=[appointment.id]))
        self.assertEqual(appointment.status, Appointment.Status.CANCELLED)

    def test_staff_can_create_update_and_change_status(self):
        self._login_as(self.staff_user, self.business)

        create_response = self.client.post(reverse("appointment_create"), data=self._appointment_payload(title="Staff visit"))
        appointment = Appointment.objects.get(title="Staff visit")
        self.assertRedirects(create_response, reverse("appointment_detail", args=[appointment.id]))

        update_response = self.client.post(
            reverse("appointment_update", args=[appointment.id]),
            data=self._appointment_payload(title="Staff updated visit"),
        )
        appointment.refresh_from_db()
        self.assertRedirects(update_response, reverse("appointment_detail", args=[appointment.id]))
        self.assertEqual(appointment.title, "Staff updated visit")

        status_response = self.client.post(
            reverse("appointment_change_status", args=[appointment.id]),
            data={"status": Appointment.Status.NO_SHOW},
        )
        appointment.refresh_from_db()
        self.assertRedirects(status_response, reverse("appointment_detail", args=[appointment.id]))
        self.assertEqual(appointment.status, Appointment.Status.NO_SHOW)

    def test_accountant_can_view_but_cannot_create_update_or_change_status(self):
        self._login_as(self.accountant_user, self.business)

        list_response = self.client.get(reverse("appointment_list"))
        detail_response = self.client.get(reverse("appointment_detail", args=[self.appointment.id]))
        create_response = self.client.get(reverse("appointment_create"), follow=True)
        update_response = self.client.get(reverse("appointment_update", args=[self.appointment.id]), follow=True)
        status_response = self.client.post(
            reverse("appointment_change_status", args=[self.appointment.id]),
            data={"status": Appointment.Status.CANCELLED},
            follow=True,
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertRedirects(create_response, reverse("appointment_list"))
        self.assertRedirects(update_response, reverse("appointment_list"))
        self.assertRedirects(status_response, reverse("appointment_list"))
        self.assertContains(create_response, "You do not have permission to manage appointments.")
        self.assertContains(update_response, "You do not have permission to manage appointments.")
        self.assertContains(status_response, "You do not have permission to manage appointments.")

    def test_viewer_can_view_but_cannot_create_update_or_change_status(self):
        self._login_as(self.viewer_user, self.business)

        list_response = self.client.get(reverse("appointment_list"))
        detail_response = self.client.get(reverse("appointment_detail", args=[self.appointment.id]))
        create_response = self.client.get(reverse("appointment_create"), follow=True)
        update_response = self.client.get(reverse("appointment_update", args=[self.appointment.id]), follow=True)
        status_response = self.client.post(
            reverse("appointment_change_status", args=[self.appointment.id]),
            data={"status": Appointment.Status.CANCELLED},
            follow=True,
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertRedirects(create_response, reverse("appointment_list"))
        self.assertRedirects(update_response, reverse("appointment_list"))
        self.assertRedirects(status_response, reverse("appointment_list"))
        self.assertContains(create_response, "You do not have permission to manage appointments.")
        self.assertContains(update_response, "You do not have permission to manage appointments.")
        self.assertContains(status_response, "You do not have permission to manage appointments.")

    def test_dashboard_shows_appointment_link_only_when_plan_allows_viewing(self):
        self._login_as(self.viewer_user, self.business)

        allowed_response = self.client.get(reverse("agent_dashboard"))
        self.assertContains(allowed_response, reverse("appointment_list"))

        subscription = BusinessSubscription.objects.get(business=self.business)
        subscription.plan = self.locked_plan
        subscription.save(update_fields=["plan", "updated_at"])

        blocked_response = self.client.get(reverse("agent_dashboard"))
        self.assertNotContains(blocked_response, reverse("appointment_list"))

    def test_detail_template_shows_management_actions_only_for_manage_roles(self):
        self._login_as(self.owner, self.business)
        owner_response = self.client.get(reverse("appointment_detail", args=[self.appointment.id]))
        self.assertContains(owner_response, reverse("appointment_update", args=[self.appointment.id]))
        self.assertContains(owner_response, reverse("appointment_change_status", args=[self.appointment.id]))

        self.client.logout()
        self._login_as(self.viewer_user, self.business)
        viewer_response = self.client.get(reverse("appointment_detail", args=[self.appointment.id]))
        self.assertNotContains(viewer_response, reverse("appointment_update", args=[self.appointment.id]))
        self.assertNotContains(viewer_response, reverse("appointment_change_status", args=[self.appointment.id]))

    def test_appointment_detail_uses_snapshot_after_service_name_changes(self):
        self._login_as(self.owner, self.business)
        self.service.name = "Updated Service Name"
        self.service.save()

        response = self.client.get(reverse("appointment_detail", args=[self.appointment.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Septic Pumping")
        self.assertNotContains(response, "Updated Service Name")

    def test_appointment_list_hides_create_button_for_read_only_roles(self):
        self._login_as(self.viewer_user, self.business)

        viewer_response = self.client.get(reverse("appointment_list"))

        self.assertEqual(viewer_response.status_code, 200)
        self.assertNotContains(viewer_response, reverse("appointment_create"))
        self.assertContains(viewer_response, "read-only appointment access")

    def test_sidebar_shows_create_link_only_for_manage_roles(self):
        self._login_as(self.owner, self.business)
        owner_response = self.client.get(reverse("agent_dashboard"))
        self.assertContains(owner_response, reverse("appointment_create"))

        self.client.logout()
        self._login_as(self.viewer_user, self.business)
        viewer_response = self.client.get(reverse("agent_dashboard"))
        self.assertNotContains(viewer_response, reverse("appointment_create"))
