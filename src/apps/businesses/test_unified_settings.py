from django.forms.models import model_to_dict
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import SaaSUserProfile

from . import test_configuration_update
from .models import Business, BusinessSubscription, BusinessUser


class UnifiedSettingsTests(TestCase):
    setUp = test_configuration_update.InvitationLocationTests.setUp
    site = test_configuration_update.InvitationLocationTests.site
    switch = test_configuration_update.InvitationLocationTests.switch

    def role(self, business, role):
        BusinessUser.objects.update_or_create(
            business=business, user=self.owner, defaults={"role": role}
        )
        self.switch(business)

    def personal_data(self):
        self.owner.refresh_from_db()
        return {
            "section": "account",
            "account-first_name": "Updated",
            "account-last_name": "Account",
            "account-email": self.owner.email,
            "account-phone": "+1 555 123 4567",
            "account-address": "Personal address",
            "account-date_of_birth": "1990-02-03",
        }

    def test_roles_see_only_permitted_fields_and_no_old_profile_ui(self):
        for business in (self.business, self.services):
            for role in BusinessUser.Role.values:
                with self.subTest(business=business, role=role):
                    self.role(business, role)
                    response = self.client.get(reverse("business_settings"))
                    self.assertContains(response, "My account")
                    self.assertContains(response, 'name="account-email"', count=1)
                    self.assertContains(response, reverse("password_change"))
                    self.assertNotContains(response, "Account Profile")
                    self.assertNotContains(response, "Legacy")
                    self.assertNotContains(response, reverse("saas_profile"))
                    self.assertEqual(
                        'name="currency"' in response.content.decode(), role in ("owner", "admin")
                    )
                    self.assertEqual(
                        "Subscription and Motionmate payment settings" in response.content.decode(),
                        role == "owner",
                    )
        self.assertFalse(SaaSUserProfile.objects.filter(user=self.owner).exists())

    def test_personal_saves_preserve_business_legacy_values_and_other_users(self):
        profile = SaaSUserProfile.objects.create(
            user=self.owner,
            workspace_name="Old name",
            currency_code="XCD",
            invoice_prefix="OLD",
            payment_instructions="Retained instructions",
            invoice_footer_note="Retained footer",
        )
        profile_before = model_to_dict(profile)
        other_user = model_to_dict(self.employee)
        self.owner.company_name = "Retained company fallback"
        self.owner.assigned_location = "DOMINICA"
        self.owner.save()
        for business in (self.business, self.services):
            for role in BusinessUser.Role.values:
                self.role(business, role)
                business_before = list(Business.objects.order_by("pk").values())
                data = self.personal_data()
                data.update(
                    {
                        "business_id": self.other.pk,
                        "user_id": self.employee.pk,
                        "name": "Do not write",
                        "currency": "EUR",
                        "company_name": "Do not write",
                        "assigned_location": "WORLD",
                    }
                )
                self.assertRedirects(
                    self.client.post(reverse("business_settings"), data),
                    f"{reverse('business_settings')}#my-account",
                )
                self.owner.refresh_from_db()
                self.assertEqual(self.owner.first_name, "Updated")
                self.assertEqual(
                    (self.owner.company_name, self.owner.assigned_location),
                    ("Retained company fallback", "DOMINICA"),
                )
                profile.refresh_from_db()
                self.employee.refresh_from_db()
                self.assertEqual(model_to_dict(profile), profile_before)
                self.assertEqual(model_to_dict(self.employee), other_user)
                self.assertEqual(list(Business.objects.order_by("pk").values()), business_before)

    def test_business_saves_are_scoped_and_restricted(self):
        profile = SaaSUserProfile.objects.create(
            user=self.owner, currency_code="XCD", invoice_prefix="OLD"
        )
        for business in (self.business, self.services):
            for role in BusinessUser.Role.values:
                self.role(business, role)
                business.refresh_from_db()
                other = model_to_dict(self.other)
                user = model_to_dict(self.owner)
                old_profile = model_to_dict(profile)
                if role in ("owner", "admin"):
                    response = self.client.get(reverse("business_settings"))
                    form = response.context["form"]
                    data = {
                        name: (form[name].value() if form[name].value() is not None else "")
                        for name in form.fields
                    }
                    data.update(
                        {
                            "section": "business",
                            "name": "Updated workspace",
                            "country": "US" if business == self.business else "Sint Maarten",
                            "currency": "EUR",
                            "business_id": self.other.pk,
                            "account-first_name": "Do not write",
                        }
                    )
                    self.assertRedirects(
                        self.client.post(reverse("business_settings"), data),
                        reverse("business_settings"),
                    )
                    business.refresh_from_db()
                    self.assertEqual(
                        (business.name, business.currency), ("Updated workspace", "EUR")
                    )
                else:
                    before = model_to_dict(business)
                    self.assertEqual(
                        self.client.post(
                            reverse("business_settings"),
                            {"name": "Forbidden", "section": "business"},
                        ).status_code,
                        403,
                    )
                    business.refresh_from_db()
                    self.assertEqual(model_to_dict(business), before)
                self.owner.refresh_from_db()
                profile.refresh_from_db()
                self.other.refresh_from_db()
                self.assertEqual(model_to_dict(self.owner), user)
                self.assertEqual(model_to_dict(profile), old_profile)
                self.assertEqual(model_to_dict(self.other), other)

    def test_invalid_personal_and_business_saves_preserve_records(self):
        personal = self.personal_data()
        personal["account-email"] = self.employee.email
        user_before = model_to_dict(self.owner)
        response = self.client.post(reverse("business_settings"), personal)
        self.assertFormError(
            response.context["account_form"],
            "email",
            "Another account is already using this email.",
        )
        self.owner.refresh_from_db()
        self.assertEqual(model_to_dict(self.owner), user_before)
        before = model_to_dict(self.business)
        response = self.client.post(
            reverse("business_settings"), {"section": "business", "name": ""}
        )
        self.assertTrue(response.context["form"].errors)
        self.business.refresh_from_db()
        self.assertEqual(model_to_dict(self.business), before)

    def test_profile_get_redirects_to_permitted_sections_without_writes(self):
        for role in BusinessUser.Role.values:
            self.role(self.business, role)
            for section, anchor in (
                ("basic", "my-account"),
                ("workspace", "business-details"),
                ("invoice", "invoice-defaults"),
            ):
                expected = anchor if role in ("owner", "admin") else "my-account"
                self.assertRedirects(
                    self.client.get(reverse("saas_profile"), {"section": section}),
                    f"{reverse('business_settings')}#{expected}",
                )
        self.assertFalse(SaaSUserProfile.objects.filter(user=self.owner).exists())

    def test_old_profile_post_keeps_compatibility_values_separate(self):
        before = model_to_dict(self.business)
        response = self.client.post(
            reverse("saas_profile"),
            {
                "section": "workspace",
                "workspace_name": "Preserved old client name",
                "billing_email": "old@example.test",
                "support_email": "help@example.test",
                "website": "https://example.test",
                "tax_id": "OLD-TAX",
            },
        )
        self.assertRedirects(response, f"{reverse('business_settings')}#business-details")
        self.assertEqual(
            SaaSUserProfile.objects.get(user=self.owner).workspace_name, "Preserved old client name"
        )
        self.business.refresh_from_db()
        self.assertEqual(model_to_dict(self.business), before)

    def test_restricted_subscription_and_no_business_still_allow_personal_settings(self):
        BusinessSubscription.objects.filter(business=self.business).update(
            status=BusinessSubscription.Status.CANCELLED
        )
        self.assertContains(self.client.get(reverse("business_settings")), "My account")
        self.assertRedirects(
            self.client.post(reverse("business_settings"), self.personal_data()),
            f"{reverse('business_settings')}#my-account",
        )
        self.assertEqual(
            self.client.post(reverse("business_settings"), {"name": "Forbidden"}).status_code, 302
        )
        BusinessUser.objects.filter(user=self.owner).delete()
        self.assertContains(self.client.get(reverse("business_settings")), "My account")
        self.assertRedirects(
            self.client.post(reverse("business_settings"), self.personal_data()),
            f"{reverse('business_settings')}#my-account",
        )

    def test_personal_post_requires_login(self):
        self.client.logout()
        self.assertEqual(
            self.client.post(reverse("business_settings"), self.personal_data()).status_code, 302
        )
