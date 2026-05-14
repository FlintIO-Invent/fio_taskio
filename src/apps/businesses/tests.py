from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import TaskIOUser

from .models import Business, BusinessUser
from .utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    business_required,
    business_role_required,
    get_current_business,
    get_current_business_membership,
)


class BusinessModelTests(TestCase):
    def test_business_slug_is_unique(self):
        Business.objects.create(name="Clarivo HQ", slug="clarivo-hq")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Business.objects.create(name="Clarivo HQ 2", slug="clarivo-hq")


class BusinessUserModelTests(TestCase):
    def test_membership_is_unique_per_user_and_business(self):
        user = TaskIOUser.objects.create_user(
            email="owner@example.com",
            password="testpass123",
        )
        business = Business.objects.create(name="Clarivo HQ", slug="clarivo-hq")
        BusinessUser.objects.create(user=user, business=business, role=BusinessUser.Role.OWNER)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BusinessUser.objects.create(user=user, business=business, role=BusinessUser.Role.ADMIN)


class CurrentBusinessTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = TaskIOUser.objects.create_user(
            email="workspace-user@example.com",
            password="testpass123",
        )

    def _build_request(self, session: dict | None = None):
        request = self.factory.get("/")
        request.user = self.user
        request.session = session if session is not None else {}
        return request

    def test_get_current_business_prefers_valid_session_business(self):
        first_business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        second_business = Business.objects.create(name="Beta Workspace", slug="beta-workspace")
        BusinessUser.objects.create(user=self.user, business=first_business, role=BusinessUser.Role.STAFF)
        BusinessUser.objects.create(user=self.user, business=second_business, role=BusinessUser.Role.OWNER)

        request = self._build_request({CURRENT_BUSINESS_SESSION_KEY: second_business.id})

        current_business = get_current_business(request)

        self.assertEqual(current_business, second_business)
        self.assertEqual(request.current_business, second_business)

    def test_get_current_business_falls_back_to_first_active_membership(self):
        first_business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        second_business = Business.objects.create(name="Beta Workspace", slug="beta-workspace")
        BusinessUser.objects.create(user=self.user, business=first_business, role=BusinessUser.Role.STAFF)
        BusinessUser.objects.create(user=self.user, business=second_business, role=BusinessUser.Role.OWNER)

        request = self._build_request({CURRENT_BUSINESS_SESSION_KEY: 999999})

        current_business = get_current_business(request)

        self.assertEqual(current_business, first_business)
        self.assertEqual(request.session[CURRENT_BUSINESS_SESSION_KEY], first_business.id)

    def test_get_current_business_returns_none_without_membership(self):
        request = self._build_request({CURRENT_BUSINESS_SESSION_KEY: 999999})

        current_business = get_current_business(request)

        self.assertIsNone(current_business)
        self.assertNotIn(CURRENT_BUSINESS_SESSION_KEY, request.session)

    def test_business_required_redirects_to_setup_when_user_has_no_membership(self):
        @business_required()
        def sample_view(request):
            return HttpResponse("ok")

        request = self._build_request()

        response = sample_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("business_setup"))

    def test_business_required_allows_access_and_sets_request_current_business(self):
        business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        BusinessUser.objects.create(user=self.user, business=business, role=BusinessUser.Role.OWNER)

        @business_required()
        def sample_view(request):
            self.assertEqual(request.current_business, business)
            return HttpResponse("ok")

        request = self._build_request()

        response = sample_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_get_current_business_membership_returns_current_workspace_membership(self):
        business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        membership = BusinessUser.objects.create(
            user=self.user,
            business=business,
            role=BusinessUser.Role.ADMIN,
        )

        request = self._build_request()

        resolved_membership = get_current_business_membership(request)

        self.assertEqual(resolved_membership, membership)
        self.assertEqual(request.current_business_membership, membership)

    def test_business_role_required_blocks_non_allowed_roles(self):
        business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        BusinessUser.objects.create(
            user=self.user,
            business=business,
            role=BusinessUser.Role.STAFF,
        )

        @business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
        def sample_view(request):
            return HttpResponse("ok")

        request = self._build_request()

        with self.assertRaises(PermissionDenied):
            sample_view(request)


class BusinessSettingsViewTests(TestCase):
    def setUp(self):
        self.user = TaskIOUser.objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Jane",
            last_name="Doe",
        )
        self.business = Business.objects.create(
            name="Clarivo HQ",
            slug="clarivo-hq",
            email="hello@clarivo.test",
            country="Sint Maarten",
        )

    def _login_with_role(self, role: str):
        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=role,
        )
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()
        self.client.force_login(self.user)

    def test_owner_can_view_business_settings(self):
        self._login_with_role(BusinessUser.Role.OWNER)

        response = self.client.get(reverse("business_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Business Details")
        self.assertContains(response, "Clarivo HQ")

    def test_admin_can_update_business_settings(self):
        self._login_with_role(BusinessUser.Role.ADMIN)

        response = self.client.post(
            reverse("business_settings"),
            {
                "name": "Clarivo Caribbean",
                "email": "billing@clarivo.test",
                "phone": "+1 721 555 0100",
                "address": "Front Street, Philipsburg",
                "country": "Sint Maarten",
                "currency": "XCD",
                "timezone": "America/Lower_Princes",
                "tax_rate": "6.50",
                "invoice_prefix": "CLR",
                "invoice_start_number": "250",
            },
            follow=True,
        )

        self.business.refresh_from_db()

        self.assertRedirects(response, reverse("business_settings"))
        self.assertEqual(self.business.name, "Clarivo Caribbean")
        self.assertEqual(self.business.currency, "XCD")
        self.assertEqual(self.business.timezone, "America/Lower_Princes")
        self.assertEqual(self.business.tax_rate, Decimal("6.50"))
        self.assertEqual(self.business.invoice_prefix, "CLR")
        self.assertEqual(self.business.invoice_start_number, 250)
        self.assertContains(response, "Business settings updated.")

    def test_staff_viewer_and_accountant_cannot_edit_business_settings(self):
        restricted_roles = [
            BusinessUser.Role.STAFF,
            BusinessUser.Role.VIEWER,
            BusinessUser.Role.ACCOUNTANT,
        ]

        for role in restricted_roles:
            with self.subTest(role=role):
                BusinessUser.objects.all().delete()
                self.client.logout()
                self._login_with_role(role)

                response = self.client.get(reverse("business_settings"))

                self.assertEqual(response.status_code, 403)
