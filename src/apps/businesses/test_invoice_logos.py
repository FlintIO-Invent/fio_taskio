"""Company logo validation, workspace settings, and tenant data lifecycle."""

import os
from io import BytesIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from PIL import Image, PngImagePlugin

from . import test_configuration_update
from .business_data_inventory import build_business_data_inventory
from .business_data_purge import BusinessPurgeError, purge_business
from .invoice_logos import MAX_UPLOAD_BYTES, load_invoice_logo, normalize_invoice_logo
from .models import Business, BusinessInvoiceLogo, BusinessSubscription, BusinessUser


def logo_upload(*, size=(300, 100), color=(30, 90, 180, 128), format="PNG", metadata=False):
    image = Image.new("RGBA" if format == "PNG" else "RGB", size, color)
    output = BytesIO()
    options = {}
    if metadata and format == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", "Private uploaded metadata")
        options["pnginfo"] = info
    image.save(output, format=format, **options)
    return SimpleUploadedFile(
        "company-logo." + format.lower(), output.getvalue(), content_type="image/" + format.lower()
    )


class InvoiceLogoValidationTests(SimpleTestCase):
    def test_normalization_preserves_alpha_and_aspect_ratio_and_strips_metadata(self):
        data = normalize_invoice_logo(logo_upload(size=(2000, 400), metadata=True))
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.size, (1000, 200))
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((50, 50))[3], 128)
            self.assertNotIn("Comment", image.info)
            self.assertNotIn("exif", image.info)
        self.assertLessEqual(len(data), 512 * 1024)

    def test_jpeg_and_portrait_logos_are_supported(self):
        for upload, expected in (
            (logo_upload(format="JPEG", color=(90, 10, 50)), (300, 100)),
            (logo_upload(size=(200, 2000)), (50, 500)),
        ):
            with self.subTest(expected=expected):
                with Image.open(BytesIO(normalize_invoice_logo(upload))) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, expected)

    def test_jpeg_orientation_is_applied_and_exif_is_not_retained(self):
        source = Image.new("RGB", (100, 300), "red")
        exif = Image.Exif()
        exif[274] = 6
        output = BytesIO()
        source.save(output, format="JPEG", exif=exif)
        data = normalize_invoice_logo(SimpleUploadedFile("rotated.jpg", output.getvalue()))
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.size, (300, 100))
            self.assertFalse(image.getexif())

    def test_invalid_forged_oversized_and_excessive_pixel_uploads_are_rejected(self):
        uploads = [
            SimpleUploadedFile("logo.png", b"<svg onload='alert(1)'/>", content_type="image/png"),
            SimpleUploadedFile("logo.png", b"not an image", content_type="image/png"),
            SimpleUploadedFile("logo.png", b"x" * (MAX_UPLOAD_BYTES + 1)),
            logo_upload(size=(4097, 1)),
            logo_upload(size=(4001, 4001)),
        ]
        for upload in uploads:
            with self.subTest(size=upload.size):
                with self.assertRaises(ValidationError):
                    normalize_invoice_logo(upload)

    def test_animation_and_overly_detailed_normalized_images_are_rejected(self):
        animated = BytesIO()
        Image.new("RGBA", (10, 10), "red").save(
            animated,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGBA", (10, 10), "blue")],
            duration=100,
        )
        noisy = BytesIO()
        Image.frombytes("RGB", (1000, 500), os.urandom(1000 * 500 * 3)).save(noisy, format="PNG")
        for data in (animated.getvalue(), noisy.getvalue()):
            with self.assertRaises(ValidationError):
                normalize_invoice_logo(SimpleUploadedFile("logo.png", data))


class InvoiceLogoSettingsTests(TestCase):
    setUp = test_configuration_update.InvitationLocationTests.setUp
    site = test_configuration_update.InvitationLocationTests.site
    switch = test_configuration_update.InvitationLocationTests.switch

    def role(self, business, role="owner"):
        BusinessUser.objects.update_or_create(
            business=business, user=self.owner, defaults={"role": role}
        )
        self.switch(business)

    def settings_data(self):
        form = self.client.get(reverse("business_settings")).context["form"]
        return {
            name: form[name].value() if form[name].value() is not None else ""
            for name in form.fields
        }

    def test_settings_upload_replace_preserve_and_remove_for_both_products(self):
        self.assertFalse(BusinessInvoiceLogo.objects.exists())
        for business in (self.business, self.services):
            with self.subTest(vertical=business.vertical):
                self.role(business)
                data = self.settings_data()
                response = self.client.post(
                    reverse("business_settings"),
                    {**data, "invoice_logo": logo_upload(), "business_id": self.other.pk},
                )
                self.assertRedirects(response, reverse("business_settings"))
                original = load_invoice_logo(business.pk).png_data
                preview = self.client.get(reverse("business_settings"))
                self.assertContains(preview, 'enctype="multipart/form-data"')
                self.assertContains(preview, "data:image/png;base64,")
                self.assertFalse(BusinessInvoiceLogo.objects.filter(business=self.other).exists())
                self.assertRedirects(
                    self.client.post(reverse("business_settings"), data),
                    reverse("business_settings"),
                )
                self.assertEqual(load_invoice_logo(business.pk).png_data, original)
                self.role(business, "admin")
                self.client.post(
                    reverse("business_settings"),
                    {**data, "invoice_logo": logo_upload(color=(200, 40, 10, 255))},
                )
                self.assertNotEqual(load_invoice_logo(business.pk).png_data, original)
                self.assertEqual(BusinessInvoiceLogo.objects.filter(business=business).count(), 1)
                self.client.post(
                    reverse("business_settings"), {**data, "remove_invoice_logo": "on"}
                )
                self.assertIsNone(load_invoice_logo(business.pk))

    def test_invalid_upload_and_conflicting_removal_preserve_business_and_saved_logo(self):
        data = self.settings_data()
        saved = BusinessInvoiceLogo.objects.create(
            business=self.business, png_data=normalize_invoice_logo(logo_upload())
        )
        original = bytes(saved.png_data)
        for upload, extra in (
            (SimpleUploadedFile("bad.png", b"broken"), {}),
            (logo_upload(color=(200, 40, 10, 255)), {"remove_invoice_logo": "on"}),
        ):
            response = self.client.post(
                reverse("business_settings"),
                {**data, "name": "Do not save", "invoice_logo": upload, **extra},
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors.get("invoice_logo"))
            saved.refresh_from_db()
            self.assertEqual(bytes(saved.png_data), original)
            self.business.refresh_from_db()
            self.assertEqual(self.business.name, "Logistics")
        response = self.client.post(
            reverse("business_settings"), {**data, "name": "", "invoice_logo": logo_upload()}
        )
        self.assertTrue(response.context["form"].errors.get("name"))
        self.assertEqual(BusinessInvoiceLogo.objects.get(pk=saved.pk).updated_at, saved.updated_at)

    def test_staff_accountants_viewers_and_restricted_owners_cannot_change_logo(self):
        data = self.settings_data()
        for business in (self.business, self.services):
            for role in ("staff", "accountant", "viewer"):
                self.role(business, role)
                self.assertNotContains(
                    self.client.get(reverse("business_settings")), 'name="invoice_logo"'
                )
                response = self.client.post(
                    reverse("business_settings"), {**data, "invoice_logo": logo_upload()}
                )
                self.assertEqual(response.status_code, 403)
            self.role(business)
            BusinessSubscription.objects.filter(business=business).update(
                status=BusinessSubscription.Status.CANCELLED
            )
            self.assertEqual(
                self.client.post(
                    reverse("business_settings"), {**data, "invoice_logo": logo_upload()}
                ).status_code,
                302,
            )
        self.assertFalse(BusinessInvoiceLogo.objects.exists())

    def test_failed_logo_save_rolls_back_other_business_settings(self):
        data = self.settings_data()
        with (
            patch(
                "apps.businesses.views.BusinessInvoiceLogo.objects.update_or_create",
                side_effect=RuntimeError("test database failure"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("business_settings"),
                {**data, "name": "Rolled back", "invoice_logo": logo_upload()},
            )
        self.business.refresh_from_db()
        self.assertEqual(self.business.name, "Logistics")
        self.assertFalse(BusinessInvoiceLogo.objects.exists())

    def test_corrupt_logo_falls_back_and_can_be_removed(self):
        BusinessInvoiceLogo.objects.create(business=self.business, png_data=b"broken")
        with self.assertLogs("apps.businesses.invoice_logos", level="WARNING"):
            response = self.client.get(reverse("business_settings"))
        self.assertContains(response, "The saved logo cannot be previewed")
        self.assertContains(response, 'name="remove_invoice_logo"')
        form = response.context["form"]
        data = {
            name: form[name].value() if form[name].value() is not None else ""
            for name in form.fields
        }
        self.client.post(reverse("business_settings"), {**data, "remove_invoice_logo": "on"})
        self.assertFalse(BusinessInvoiceLogo.objects.exists())

    def test_inventory_and_confirmed_test_tenant_purge_include_logo_without_touching_other_tenants(
        self,
    ):
        target = Business.objects.create(
            name="Disposable logo tenant", slug="logo-purge-test", is_active=False
        )
        data = normalize_invoice_logo(logo_upload())
        BusinessInvoiceLogo.objects.create(business=target, png_data=data)
        retained = BusinessInvoiceLogo.objects.create(business=self.business, png_data=data)
        inventory = build_business_data_inventory(target)
        self.assertEqual(
            next(
                row.total_count for row in inventory.records if row.key == "business_invoice_logo"
            ),
            1,
        )
        purge_business(business_id=target.pk, reason_reference="TEST-LOGO-PURGE")
        self.assertFalse(BusinessInvoiceLogo.objects.filter(business_id=target.pk).exists())
        self.assertTrue(BusinessInvoiceLogo.objects.filter(pk=retained.pk).exists())

    def test_financial_confirmation_gate_keeps_logo_until_confirmed_purge(self):
        from apps.billings.models import Invoice
        from apps.crm.models import Client

        self.role(self.services)
        customer = Client.objects.create(
            business=self.services, first_name="Purge", last_name="Test"
        )
        Invoice.objects.create(
            business=self.services, client=customer, invoice_number="LOGO-PURGE", total=100
        )
        logo = BusinessInvoiceLogo.objects.create(
            business=self.services, png_data=normalize_invoice_logo(logo_upload())
        )
        self.services.is_active = False
        self.services.save(update_fields=["is_active"])
        with self.assertRaises(BusinessPurgeError) as error:
            purge_business(business_id=self.services.pk, reason_reference="TEST-LOGO-GATE")
        self.assertEqual(error.exception.error_code, "test_financial_data_confirmation_required")
        self.assertTrue(BusinessInvoiceLogo.objects.filter(pk=logo.pk).exists())
        purge_business(
            business_id=self.services.pk,
            reason_reference="TEST-LOGO-GATE",
            confirm_test_financial_data=True,
        )
        self.assertFalse(BusinessInvoiceLogo.objects.filter(pk=logo.pk).exists())
