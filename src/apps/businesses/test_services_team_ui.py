"""Team form, access and preserved-consumer contracts on owned PostgreSQL only."""

import os
import re
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.crm.test_services_dashboard_ui import assert_disposable

from .models import Business, BusinessInvitation, BusinessSubscription, BusinessUser, ClarivoPlan
from .test_service_allowances import ServicesFixture
from .utils import CURRENT_BUSINESS_SESSION_KEY


class TeamPresentationTests(ServicesFixture, TestCase):
    def setUp(self):
        assert_disposable()
        super().setUp()
        self.login()

    def test_invite_invalid_values_keep_draft_and_complete_form(self):
        response = self.client.post(
            reverse("business_team_members"), {"email": "bad-email", "role": "staff"}
        )
        self.assertContains(response, 'value="bad-email"')
        self.assertContains(response, "Enter a valid email address.")
        self.assertContains(response, 'name="role"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertFalse(BusinessInvitation.objects.exists())

    def test_pending_refresh_preserves_single_invitation_and_failure_feedback(self):
        with patch("apps.businesses.views.send_business_invitation_email", return_value=False):
            for _ in range(2):
                response = self.client.post(
                    reverse("business_team_members"),
                    {"email": "colleague@native.test", "role": "staff"},
                    follow=True,
                )
        self.assertEqual(BusinessInvitation.objects.count(), 1)
        self.assertContains(response, "email could not be sent")
        self.assertContains(response, "colleague@native.test")
        invite = BusinessInvitation.objects.get()
        self.assertContains(response, reverse("accept_business_invitation", args=[invite.token]))

    def test_roles_remain_server_authoritative(self):
        for role in BusinessUser.Role.values:
            self.member.role = role
            self.member.save(update_fields=["role"])
            response = self.client.get(reverse("business_team_members"))
            self.assertEqual(response.status_code, 200 if role in ["owner", "admin"] else 403)
            if role not in ["owner", "admin"]:
                self.assertEqual(
                    self.client.post(
                        reverse("business_team_members"),
                        {"email": "denied@native.test", "role": "staff"},
                    ).status_code,
                    403,
                )
        self.assertFalse(BusinessInvitation.objects.exists())

    def test_deactivate_scoped_post_preserves_user_and_inactive_record(self):
        user = self.user()
        member = BusinessUser.objects.create(business=self.business, user=user, role="staff")
        url = reverse("business_team_member_deactivate", args=[member.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        member.refresh_from_db()
        user.refresh_from_db()
        self.assertFalse(member.is_active)
        self.assertTrue(user.is_active)
        self.assertContains(self.client.get(reverse("business_team_members")), user.email)
        other = Business.objects.create(name="Other tenant", slug="other-team")
        BusinessSubscription.objects.create(business=other, plan=self.plan, status="active")
        foreign = BusinessUser.objects.create(business=other, user=self.user(), role="staff")
        self.assertEqual(
            self.client.post(
                reverse("business_team_member_deactivate", args=[foreign.pk])
            ).status_code,
            404,
        )
        self.client.post(reverse("business_team_member_deactivate", args=[self.member.pk]))
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    def test_csrf_required_on_invitation_and_removal(self):
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        session = guarded.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.assertEqual(
            guarded.post(
                reverse("business_team_members"), {"email": "csrf@native.test", "role": "staff"}
            ).status_code,
            403,
        )
        self.assertEqual(
            guarded.post(
                reverse("business_team_member_deactivate", args=[self.member.pk])
            ).status_code,
            403,
        )

    def test_logistics_rendering_matches_frozen_before(self):
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        self.business.vertical = "LOGISTICS"
        self.business.save(update_fields=["vertical"])
        self.subscription.plan = plan
        self.subscription.billing_interval = "yearly"
        self.subscription.save()
        before = Path(os.environ["SERVICES_TEAM_BEFORE"]) / "src/templates"
        templates = [
            {**settings.TEMPLATES[0], "DIRS": [str(before), *settings.TEMPLATES[0]["DIRS"]]}
        ]
        current = self.client.get(reverse("business_team_members"))
        with override_settings(TEMPLATES=templates):
            original = self.client.get(reverse("business_team_members"))

        def clean(raw):
            return re.sub(
                rb">\s+<", b"><", re.sub(rb'name="csrfmiddlewaretoken" value="[^"]+"', b"csrf", raw)
            ).strip()

        self.assertEqual(clean(current.content), clean(original.content))
        self.assertNotContains(current, "services-team.css")
