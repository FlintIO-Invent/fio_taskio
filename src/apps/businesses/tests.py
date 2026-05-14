from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import TaskIOUser

from .models import Business, BusinessUser


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
