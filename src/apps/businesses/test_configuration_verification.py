"""PostgreSQL verification of the additive invitation/location change."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.forms import InvitationAcceptanceSignupForm
from apps.accounts.models import TaskIOUser
from apps.logistics.location_access import has_wide_access, locations_for, require_work_location
from apps.logistics.models import LogisticsLocation, LogisticsLocationAssignment, LogisticsProfile

from . import test_configuration_update
from .models import Business, BusinessInvitation, BusinessUser
from .utils import accept_business_invitation_for_user


class ExistingRoleAccessTests(TestCase):
    setUp = test_configuration_update.InvitationLocationTests.setUp
    site = test_configuration_update.InvitationLocationTests.site
    switch = test_configuration_update.InvitationLocationTests.switch
    invite = test_configuration_update.InvitationLocationTests.invite

    def test_admin_keeps_business_wide_access_after_location_invitation(self):
        second = self.site(self.business, "SECOND")
        invitation = self.invite(location=self.location, role=BusinessUser.Role.ADMIN)
        accept_business_invitation_for_user(invitation, self.employee)
        self.assertTrue(has_wide_access(self.business, self.employee))
        self.assertCountEqual(locations_for(self.business, self.employee), [self.location, second])
        self.assertIsNone(require_work_location(self.business, self.employee))

    def test_reactivation_with_new_location_keeps_existing_operational_site(self):
        second = self.site(self.business, "SECOND")
        membership = BusinessUser.objects.create(
            business=self.business, user=self.employee, role="staff", is_active=False
        )
        prior = LogisticsLocationAssignment.objects.create(
            business=self.business,
            membership=membership,
            location=second,
            can_operate=True,
            is_current=True,
        )
        LogisticsProfile.objects.update_or_create(
            business=self.business,
            defaults={"location_access_reviewed_at": self.business.created_at},
        )
        accept_business_invitation_for_user(self.invite(location=self.location), self.employee)
        prior.refresh_from_db()
        self.assertTrue(prior.can_operate)
        self.assertTrue(prior.is_current)
        self.assertEqual(require_work_location(self.business, self.employee), second)
        added = membership.logistics_location_assignments.get(location=self.location)
        self.assertFalse(added.can_operate)
        self.assertFalse(added.is_current)


@skipUnless(connection.vendor == "postgresql", "Invitation concurrency requires PostgreSQL")
class InvitationAcceptanceConcurrencyTests(TransactionTestCase):
    serialized_rollback = True
    setUp = test_configuration_update.InvitationLocationTests.setUp
    site = test_configuration_update.InvitationLocationTests.site
    switch = test_configuration_update.InvitationLocationTests.switch
    invite = test_configuration_update.InvitationLocationTests.invite

    def accept(self, invitation_id, barrier=None, entered=None):
        close_old_connections()
        try:
            invitation = BusinessInvitation.objects.select_related("business").get(pk=invitation_id)
            user = TaskIOUser.objects.get(pk=self.employee.pk)
            if barrier:
                barrier.wait(timeout=10)
            if entered:
                entered.set()
            try:
                membership, created, already_member = accept_business_invitation_for_user(
                    invitation, user
                )
                return "accepted", membership.pk, created, already_member
            except ValueError:
                return "rejected", None, False, False
        finally:
            connections.close_all()

    def test_same_invitation_race_creates_one_membership_and_assignment(self):
        invitation = self.invite(location=self.location)
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.accept, invitation.pk, barrier) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
        self.assertCountEqual([result[0] for result in results], ["accepted", "rejected"])
        self.assertEqual(BusinessUser.objects.filter(user=self.employee).count(), 1)
        assignment = LogisticsLocationAssignment.objects.get(membership__user=self.employee)
        self.assertEqual(assignment.location, self.location)
        self.assertTrue(assignment.is_current)
        self.assertFalse(assignment.can_operate)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, BusinessInvitation.Status.ACCEPTED)

    def test_concurrent_signup_acceptance_does_not_return_a_server_error(self):
        for business in (self.business, self.services):
            with self.subTest(business=business):
                self.check_signup_race(business)

    def check_signup_race(self, business):
        invitation = BusinessInvitation.objects.create(
            business=business,
            email=f"concurrent-{business.pk}@verification.test",
            role="staff",
            location=self.location if business == self.business else None,
        )
        barrier = Barrier(2)
        original_save = InvitationAcceptanceSignupForm.save

        def simultaneous_signup(form, invitation):
            barrier.wait(timeout=10)
            return original_save(form, invitation)

        def post_signup():
            close_old_connections()
            try:
                client = Client(raise_request_exception=False)
                response = client.post(
                    reverse("accept_business_invitation", args=[invitation.token]),
                    {
                        "first_name": "Concurrent",
                        "last_name": "Signup",
                        "password1": "Concurrent-local-42!",
                        "password2": "Concurrent-local-42!",
                    },
                )
                return response.status_code, client.session.get("_auth_user_id")
            finally:
                connections.close_all()

        with patch.object(InvitationAcceptanceSignupForm, "save", simultaneous_signup):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(post_signup) for _ in range(2)]
                results = [future.result(timeout=30) for future in futures]
        self.assertEqual([status for status, _user in results], [302, 302])
        # Only the winning request may authenticate; the loser must sign in.
        self.assertEqual(sum(user is not None for _status, user in results), 1)
        self.assertEqual(TaskIOUser.objects.filter(email=invitation.email).count(), 1)
        self.assertEqual(BusinessUser.objects.filter(user__email=invitation.email).count(), 1)
        self.assertEqual(
            LogisticsLocationAssignment.objects.filter(
                membership__user__email=invitation.email
            ).count(),
            int(business == self.business),
        )

    def test_duplicate_legacy_invitations_do_not_add_access_to_active_member(self):
        first = self.invite(location=self.location)
        second = BusinessInvitation.objects.create(
            business=self.business,
            email=self.employee.email,
            role="admin",
            location=self.site(self.business, "SECOND"),
        )
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.accept, item.pk, barrier) for item in (first, second)]
            results = [future.result(timeout=30) for future in futures]
        self.assertTrue(all(result[0] == "accepted" for result in results))
        self.assertEqual(sum(result[2] for result in results), 1)
        self.assertEqual(sum(result[3] for result in results), 1)
        self.assertEqual(BusinessUser.objects.filter(user=self.employee).count(), 1)
        self.assertEqual(
            LogisticsLocationAssignment.objects.filter(membership__user=self.employee).count(), 1
        )

    def test_location_deactivation_serializes_before_acceptance(self):
        invitation = self.invite(location=self.location)
        entered = Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Business.objects.select_for_update().get(pk=self.business.pk)
                future = pool.submit(self.accept, invitation.pk, entered=entered)
                self.assertTrue(entered.wait(timeout=10))
                self.assertFalse(future.done())
                LogisticsLocation.objects.filter(pk=self.location.pk).update(is_active=False)
            self.assertEqual(future.result(timeout=30)[0], "rejected")
        self.assertFalse(BusinessUser.objects.filter(user=self.employee).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, BusinessInvitation.Status.PENDING)


@skipUnless(connection.vendor == "postgresql", "Migration verification requires PostgreSQL")
class InvitationLocationMigrationTests(TransactionTestCase):
    serialized_rollback = True
    before = [
        ("businesses", "0031_logistics_usage_monitoring"),
        ("logistics", "0025_application_tier_selection"),
    ]
    after = [
        ("businesses", "0032_businessinvitation_location"),
        ("logistics", "0025_application_tier_selection"),
    ]

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.after)
        super().tearDown()

    def test_nullable_migration_preserves_preexisting_invitation_and_membership(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old_apps = executor.loader.project_state(self.before).apps
        business = old_apps.get_model("businesses", "Business").objects.create(
            name="Migration", slug="migration-verification"
        )
        user = old_apps.get_model("accounts", "TaskIOUser").objects.create(
            email="migration@verification.test", password="unusable"
        )
        membership = old_apps.get_model("businesses", "BusinessUser").objects.create(
            business=business, user=user, role="owner"
        )
        invitation = old_apps.get_model("businesses", "BusinessInvitation").objects.create(
            business=business,
            email="legacy@verification.test",
            token="legacy-migration-token",
            role="staff",
        )
        executor = MigrationExecutor(connection)
        executor.migrate(self.after)
        preserved = BusinessInvitation.objects.get(pk=invitation.pk)
        self.assertIsNone(preserved.location_id)
        self.assertEqual(
            (preserved.token, preserved.role, preserved.business_id),
            (invitation.token, "staff", business.pk),
        )
        self.assertEqual(BusinessUser.objects.get(pk=membership.pk).role, "owner")
        with connection.cursor() as cursor:
            fields = connection.introspection.get_table_description(
                cursor, BusinessInvitation._meta.db_table
            )
            self.assertTrue(next(field for field in fields if field.name == "location_id").null_ok)
            constraints = connection.introspection.get_constraints(
                cursor, BusinessInvitation._meta.db_table
            )
        self.assertTrue(
            any(
                item.get("foreign_key") == ("logistics_logisticslocation", "id")
                for item in constraints.values()
            )
        )
