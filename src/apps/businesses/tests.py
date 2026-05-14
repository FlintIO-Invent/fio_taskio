from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import TaskIOUser

from .models import Business, BusinessUser
from .utils import CURRENT_BUSINESS_SESSION_KEY, business_required, get_current_business


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
