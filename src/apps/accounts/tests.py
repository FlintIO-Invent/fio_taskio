from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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
