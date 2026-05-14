from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.businesses.models import Business, BusinessUser
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .models import SaaSUserProfile


class CustomerRegistrationViewTests(TestCase):
    def test_get_renders_registration_page(self):
        response = self.client.get(reverse("customer_registration"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create your customer account")

    def test_post_creates_customer_account_with_hashed_password(self):
        response = self.client.post(
            reverse("customer_registration"),
            {
                "email": "owner@example.com",
                "first_name": "Jane",
                "last_name": "Doe",
                "company_name": "Acme Freight",
                "phone": "+1 721 555 0100",
                "address": "Philipsburg, Sint Maarten",
                "date_of_birth": "1990-06-15",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            follow=True,
        )

        user = get_user_model().objects.get(email="owner@example.com")

        self.assertRedirects(response, reverse("customer_registration"))
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertEqual(user.incorporation_status, "UNINCORPORATED")
        self.assertTrue(SaaSUserProfile.objects.filter(user=user).exists())
        self.assertContains(response, "Your account has been created.")

    def test_post_rejects_duplicate_email_case_insensitive(self):
        get_user_model().objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Existing",
            last_name="User",
        )

        response = self.client.post(
            reverse("customer_registration"),
            {
                "email": "OWNER@example.com",
                "first_name": "Jane",
                "last_name": "Doe",
                "company_name": "Acme Freight",
                "phone": "+1 721 555 0100",
                "address": "Philipsburg, Sint Maarten",
                "date_of_birth": "1990-06-15",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]

        self.assertTrue(form.is_bound)
        self.assertEqual(
            form.errors["email"],
            ["An account with this email already exists."],
        )


class BusinessRegistrationViewTests(TestCase):
    def test_get_renders_business_registration_page(self):
        response = self.client.get(reverse("register_business"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Register your business")

    def test_post_creates_user_business_membership_and_logs_in(self):
        response = self.client.post(
            reverse("register_business"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "owner@example.com",
                "business_name": "Acme Freight",
                "business_email": "hello@acmefreight.com",
                "country": "Sint Maarten",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            follow=True,
        )

        user = get_user_model().objects.get(email="owner@example.com")
        business = Business.objects.get(name="Acme Freight")
        membership = BusinessUser.objects.get(user=user, business=business)
        profile = SaaSUserProfile.objects.get(user=user)

        self.assertRedirects(response, reverse("saas_profile"))
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertEqual(user.company_name, "Acme Freight")
        self.assertEqual(business.email, "hello@acmefreight.com")
        self.assertEqual(business.country, "Sint Maarten")
        self.assertEqual(membership.role, BusinessUser.Role.OWNER)
        self.assertEqual(profile.workspace_name, "Acme Freight")
        self.assertEqual(profile.billing_email, "hello@acmefreight.com")
        self.assertEqual(int(self.client.session[CURRENT_BUSINESS_SESSION_KEY]), business.id)
        self.assertContains(response, "Your Clarivo workspace has been created.")

    def test_post_generates_unique_slug_for_duplicate_business_names(self):
        existing_owner = get_user_model().objects.create_user(
            email="existing@example.com",
            password="StrongPass123!",
            first_name="Existing",
            last_name="Owner",
        )
        existing_business = Business.objects.create(
            name="Acme Freight",
            slug="acme-freight",
            email="existing@acmefreight.com",
            country="Sint Maarten",
        )
        BusinessUser.objects.create(
            user=existing_owner,
            business=existing_business,
            role=BusinessUser.Role.OWNER,
        )

        response = self.client.post(
            reverse("register_business"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "new-owner@example.com",
                "business_name": "Acme Freight",
                "business_email": "hello@acmefreight.com",
                "country": "Sint Maarten",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Business.objects.filter(slug="acme-freight-2").exists())


class SaaSProfileViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Jane",
            last_name="Doe",
            company_name="Acme Freight",
            incorporation_status="CORPORATED",
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse("saas_profile"))

        self.assertRedirects(
            response,
            f"{reverse('agent_login')}?next={reverse('saas_profile')}",
        )

    def test_get_creates_profile_and_renders_page(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("saas_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workspace Settings")
        self.assertTrue(SaaSUserProfile.objects.filter(user=self.user).exists())

    def test_post_basic_info_updates_user(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("saas_profile"),
            {
                "section": "basic",
                "first_name": "Janet",
                "last_name": "Rivera",
                "email": "janet@example.com",
                "company_name": "FlintIO Caribbean",
                "phone": "+1 721 555 0111",
                "assigned_location": "ST_MAARTEN",
                "date_of_birth": "1992-08-04",
                "address": "Front Street, Philipsburg",
            },
            follow=True,
        )

        self.user.refresh_from_db()

        self.assertRedirects(response, f"{reverse('saas_profile')}?section=basic")
        self.assertEqual(self.user.first_name, "Janet")
        self.assertEqual(self.user.email, "janet@example.com")
        self.assertEqual(self.user.company_name, "FlintIO Caribbean")
        self.assertContains(response, "Basic profile details updated.")

    def test_post_invoice_settings_updates_profile(self):
        self.client.force_login(self.user)
        profile = SaaSUserProfile.get_or_create_for_user(self.user)

        response = self.client.post(
            reverse("saas_profile"),
            {
                "section": "invoice",
                "currency_code": "XCD",
                "invoice_prefix": "CAS",
                "invoice_default_due_days": "21",
                "invoice_accent_color": "#0B6E4F",
                "show_company_address_on_invoice": "on",
                "payment_instructions": "Bank transfer only.",
                "invoice_footer_note": "Thanks for trusting TaskIO.",
            },
            follow=True,
        )

        profile.refresh_from_db()

        self.assertRedirects(response, f"{reverse('saas_profile')}?section=invoice")
        self.assertEqual(profile.currency_code, "XCD")
        self.assertEqual(profile.invoice_prefix, "CAS")
        self.assertEqual(profile.invoice_default_due_days, 21)
        self.assertEqual(profile.invoice_accent_color, "#0B6E4F")
        self.assertTrue(profile.show_company_address_on_invoice)
        self.assertFalse(profile.show_tax_id_on_invoice)
        self.assertContains(response, "Invoice defaults updated.")
