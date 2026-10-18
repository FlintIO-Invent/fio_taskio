from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.logistics.location_access import assignments_for, require_work_location
from apps.logistics.models import LogisticsLocation, LogisticsLocationAssignment, LogisticsProfile

from .forms import BusinessInvitationForm
from .models import Business, BusinessInvitation, BusinessSubscription, BusinessUser, ClarivoPlan
from .utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    accept_business_invitation_for_user,
    create_or_refresh_business_invitation,
)


class InvitationLocationTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Logistics", slug="invitation-logistics", vertical=Business.Vertical.LOGISTICS
        )
        self.services = Business.objects.create(name="Services", slug="invitation-services")
        self.other = Business.objects.create(
            name="Other Logistics",
            slug="other-invitation-logistics",
            vertical=Business.Vertical.LOGISTICS,
        )
        ClarivoPlan.objects.filter(slug="logistics").update(is_active=True)
        for business, plan_slug in ((self.business, "logistics"), (self.services, "business")):
            BusinessSubscription.objects.create(
                business=business,
                plan=ClarivoPlan.objects.get(slug=plan_slug),
                status=BusinessSubscription.Status.ACTIVE,
                billing_interval=BusinessSubscription.BillingInterval.YEARLY,
            )
        self.owner = TaskIOUser.objects.create_user(email="owner@invite.test")
        self.employee = TaskIOUser.objects.create_user(email="employee@invite.test")
        self.member = BusinessUser.objects.create(
            business=self.business, user=self.owner, role=BusinessUser.Role.OWNER
        )
        self.location = self.site(self.business, "LOCAL")
        self.foreign = self.site(self.other, "FOREIGN")
        self.client.force_login(self.owner)
        self.switch(self.business)

    def site(self, business, code):
        return LogisticsLocation.objects.create(
            business=business, name=code, code=code, location_type="HUB", country_code="US"
        )

    def switch(self, business):
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = business.pk
        session.save()

    def invite(self, **kwargs):
        return create_or_refresh_business_invitation(
            business=kwargs.pop("business", self.business),
            email=self.employee.email,
            role=kwargs.pop("role", BusinessUser.Role.STAFF),
            invited_by=self.owner,
            **kwargs,
        )[0]

    @patch("apps.businesses.views.send_business_invitation_email", return_value=False)
    def test_invitation_post_and_acceptance_persist_read_only_location(self, _send):
        response = self.client.get(reverse("business_team_members"))
        self.assertContains(response, 'name="location"')
        self.assertNotContains(response, str(self.foreign))
        response = self.client.post(
            reverse("business_team_members"),
            {
                "email": self.employee.email,
                "role": "staff",
                "location": self.location.pk,
            },
        )
        self.assertRedirects(response, reverse("business_team_members"))
        invitation = BusinessInvitation.objects.get(email=self.employee.email)
        self.assertEqual(invitation.location, self.location)
        self.client.force_login(self.employee)
        response = self.client.post(reverse("accept_business_invitation", args=[invitation.token]))
        self.assertRedirects(response, reverse("agent_dashboard"), fetch_redirect_response=False)
        membership = BusinessUser.objects.get(business=self.business, user=self.employee)
        assignment = LogisticsLocationAssignment.objects.get(membership=membership)
        self.assertEqual(assignment.location, self.location)
        self.assertTrue(assignment.is_current)
        self.assertFalse(assignment.can_operate)
        self.assertFalse(assignment.is_work_context)
        self.assertFalse(assignments_for(self.business, self.employee).exists())
        LogisticsProfile.objects.update_or_create(
            business=self.business, defaults={"location_access_reviewed_at": timezone.now()}
        )
        self.assertEqual(assignments_for(self.business, self.employee).get(), assignment)
        with self.assertRaises(PermissionDenied):
            require_work_location(self.business, self.employee)

    def test_foreign_and_inactive_locations_rejected_without_invitation(self):
        inactive = self.site(self.business, "INACTIVE")
        inactive.is_active = False
        inactive.save()
        for location in (self.foreign, inactive):
            with self.subTest(location=location):
                response = self.client.post(
                    reverse("business_team_members"),
                    {
                        "email": self.employee.email,
                        "role": "staff",
                        "location": location.pk,
                    },
                )
                self.assertFormError(
                    response.context["invite_form"],
                    "location",
                    "Select a valid choice. That choice is not one of the available choices.",
                )
                with self.assertRaises(ValueError):
                    self.invite(location=location)
        self.assertFalse(BusinessInvitation.objects.exists())

    def test_acceptance_rechecks_location_and_rolls_back(self):
        invitation = self.invite(location=self.location)
        for changes in ({"business": self.other}, {"business": self.business, "is_active": False}):
            with self.subTest(changes=changes):
                LogisticsLocation.objects.filter(pk=self.location.pk).update(**changes)
                with self.assertRaises(ValueError):
                    accept_business_invitation_for_user(invitation, self.employee)
                self.assertFalse(BusinessUser.objects.filter(user=self.employee).exists())
                invitation.refresh_from_db()
                self.assertEqual(invitation.status, BusinessInvitation.Status.PENDING)

    def test_model_validation_rejects_a_foreign_invitation_location(self):
        invitation = self.invite(location=self.location)
        invitation.location = self.foreign
        with self.assertRaisesMessage(
            ValidationError, "Select a Logistics location in this workspace"
        ):
            invitation.full_clean()

    def test_admin_assignment_is_context_only_even_after_demotion(self):
        invitation = self.invite(location=self.location, role=BusinessUser.Role.ADMIN)
        membership, _, _ = accept_business_invitation_for_user(invitation, self.employee)
        assignment = LogisticsLocationAssignment.objects.get(membership=membership)
        self.assertTrue(assignment.is_work_context)
        self.assertFalse(assignment.can_operate)
        membership.role = BusinessUser.Role.STAFF
        membership.save()
        LogisticsProfile.objects.update_or_create(
            business=self.business, defaults={"location_access_reviewed_at": timezone.now()}
        )
        self.assertFalse(assignments_for(self.business, self.employee).exists())

    def test_refresh_replaces_location_and_keeps_business_and_token(self):
        invitation = self.invite(location=self.location)
        replacement = self.site(self.business, "SECOND")
        refreshed = self.invite(location=replacement)
        self.assertEqual(
            (refreshed.pk, refreshed.token, refreshed.business),
            (invitation.pk, invitation.token, self.business),
        )
        self.assertEqual(refreshed.location, replacement)

    def test_existing_active_membership_receives_no_new_access(self):
        membership = BusinessUser.objects.create(
            business=self.business, user=self.employee, role=BusinessUser.Role.VIEWER
        )
        invitation = self.invite(location=self.location)
        _, created, already_member = accept_business_invitation_for_user(invitation, self.employee)
        membership.refresh_from_db()
        self.assertFalse(created)
        self.assertTrue(already_member)
        self.assertEqual(membership.role, BusinessUser.Role.VIEWER)
        self.assertFalse(membership.logistics_location_assignments.exists())

    def test_reactivation_preserves_existing_grants(self):
        membership = BusinessUser.objects.create(
            business=self.business,
            user=self.employee,
            role=BusinessUser.Role.STAFF,
            is_active=False,
        )
        assignment = LogisticsLocationAssignment.objects.create(
            business=self.business,
            membership=membership,
            location=self.location,
            can_operate=True,
            is_current=True,
        )
        invitation = self.invite(location=self.location)
        accept_business_invitation_for_user(invitation, self.employee)
        assignment.refresh_from_db()
        self.assertTrue(assignment.can_operate)
        self.assertTrue(assignment.is_current)

    def test_legacy_and_services_invitations_need_no_location(self):
        for business in (self.business, self.services):
            with self.subTest(business=business):
                invitation = self.invite(business=business)
                membership, created, _ = accept_business_invitation_for_user(
                    invitation, self.employee
                )
                self.assertTrue(created)
                self.assertFalse(membership.logistics_location_assignments.exists())
                membership.delete()
        form = BusinessInvitationForm(business=self.services, membership=self.member)
        self.assertNotIn("location", form.fields)
        with self.assertRaises(ValueError):
            self.invite(business=self.services, location=self.location)

    def test_settings_hub_permissions_and_vertical_links(self):
        for business in (self.business, self.services):
            self.switch(business)
            for role in BusinessUser.Role.values:
                with self.subTest(business=business, role=role):
                    BusinessUser.objects.update_or_create(
                        business=business, user=self.owner, defaults={"role": role}
                    )
                    response = self.client.get(reverse("business_settings"))
                    if role in ("owner", "admin"):
                        self.assertEqual(response.status_code, 200)
                        self.assertContains(response, "Upload categories and services")
                        hub = (
                            response.content.decode()
                            .split('id="configuration-title"')[1]
                            .split("</section>")[0]
                        )
                        self.assertEqual(
                            "Subscription and Motionmate payment settings" in hub, role == "owner"
                        )
                        self.assertEqual(
                            reverse("logistics_location_access") in hub, business == self.business
                        )
                    else:
                        self.assertContains(response, "My account")
                        self.assertNotContains(response, 'name="currency"')
                        response = self.client.post(
                            reverse("business_settings"), {"name": "Forbidden"}
                        )
                        self.assertEqual(response.status_code, 403)
                        business.refresh_from_db()
                        self.assertNotEqual(business.name, "Forbidden")
