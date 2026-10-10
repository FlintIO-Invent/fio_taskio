"""V2 entropy, collision recovery and end-to-end legacy compatibility."""

import math
import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from . import test_parcels as fixtures
from .models import Parcel, ParcelEvent, generate_tracking_code
from .parcel_services import edit_parcel
from .public_tracking import lookup_public_tracking
from .scan import normalize_scan_code, resolve_scanned_parcel
from .shipment_services import assign_parcel, create_shipment, generate_manifest
from .tracking_codes import (
    TRACKING_CODE_ALPHABET,
    TRACKING_CODE_PREFIX,
    TRACKING_CODE_SUFFIX_LENGTH,
)

V2_REGEX = r"\AMM-PCL-[A-HJKM-NP-Z2-9]{39}\Z"
LEGACY_CODE = "A10F" * 12


class TrackingCodeGenerationTests(SimpleTestCase):
    def test_entropy_preserves_192_bit_bearer_secret(self):
        self.assertEqual(len(TRACKING_CODE_ALPHABET), 31)
        self.assertEqual(len(set(TRACKING_CODE_ALPHABET)), 31)
        self.assertFalse(set("O0I1L") & set(TRACKING_CODE_ALPHABET))
        bits_per_character = math.log2(len(TRACKING_CODE_ALPHABET))
        self.assertGreaterEqual(TRACKING_CODE_SUFFIX_LENGTH * bits_per_character, 192)
        self.assertLess((TRACKING_CODE_SUFFIX_LENGTH - 1) * bits_per_character, 192)
        self.assertLessEqual(len(generate_tracking_code()), 48)

    def test_each_character_uses_cryptographic_choice(self):
        suffix = (TRACKING_CODE_ALPHABET * 2)[:TRACKING_CODE_SUFFIX_LENGTH]
        with patch("secrets.choice", side_effect=suffix) as source:
            self.assertEqual(generate_tracking_code(), TRACKING_CODE_PREFIX + suffix)
        self.assertEqual(source.call_count, TRACKING_CODE_SUFFIX_LENGTH)
        for call in source.call_args_list:
            self.assertEqual(call.args, (TRACKING_CODE_ALPHABET,))

    def test_random_codes_and_both_scan_formats(self):
        codes = [generate_tracking_code() for _ in range(100)]
        self.assertEqual(len(set(codes)), 100)
        for code in [*codes, LEGACY_CODE]:
            if code != LEGACY_CODE:
                self.assertRegex(code, V2_REGEX)
            for raw in (code, code.lower(), "\t " + code.lower() + "\r\n"):
                self.assertEqual(normalize_scan_code(raw), code)

    def test_short_ambiguous_and_malformed_v2_codes_are_rejected(self):
        valid = generate_tracking_code()
        for code in (
            "MM-PCL-A82719K4N",
            valid[:-1],
            valid + "A",
            "MM-PCL-" + "A" * 19 + " " + "A" * 19,
            "MM-PCL-" + "A" * 19 + "\n" + "A" * 19,
            valid + valid,
            "https://example.test/" + valid,
            *["MM-PCL-" + character * 39 for character in "O0I1L"],
        ):
            with self.subTest(code=code), self.assertRaises(ValidationError):
                normalize_scan_code(code)
            with self.assertRaises(ValidationError):
                Parcel._meta.get_field("tracking_code").clean(code, None)

    def test_direct_qr_and_code128_encoding(self):
        from reportlab.graphics.barcode import createBarcodeDrawing

        for code in (generate_tracking_code(), LEGACY_CODE):
            for symbology in ("QR", "Code128"):
                with self.subTest(symbology=symbology, code=code):
                    drawing = createBarcodeDrawing(symbology, value=code)
                    self.assertIn("<svg", drawing.asString("svg"))
                    if symbology == "Code128":
                        drawing._bc.validate()
                        self.assertTrue(drawing._bc.valid)
                        self.assertEqual(drawing._bc.validated, code)


@override_settings(
    LOGISTICS_LOCAL_BILLING_BYPASS=False,
    LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE=False,
    LOGISTICS_TRACKING_CLIENT_IP_MODE="direct",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class TrackingCodeCompatibilityTests(TestCase):
    setUp = fixtures.ParcelTests.setUp
    register = fixtures.ParcelTests.register
    switch = fixtures.ParcelTests.switch

    def legacy_parcel(self):
        parcel = self.register()
        # Simulate a persisted pre-V2 row using a privileged fixture write.
        QuerySet(model=Parcel).filter(pk=parcel.pk).update(tracking_code=LEGACY_CODE)
        parcel.refresh_from_db()
        return parcel

    def test_duplicate_candidate_retries_without_extra_events(self):
        with patch("secrets.choice", return_value="A"):
            existing = self.register()
        replacement = "MM-PCL-" + "B" * 39
        with (
            patch("secrets.choice", return_value="A"),
            patch(
                "apps.logistics.parcel_services.generate_tracking_code", return_value=replacement
            ) as retry,
        ):
            parcel = self.register()
        retry.assert_called_once_with()
        self.assertNotEqual(parcel.pk, existing.pk)
        self.assertEqual(parcel.tracking_code, replacement)
        self.assertEqual(Parcel.objects.count(), 2)
        self.assertEqual(ParcelEvent.objects.count(), 2)

    def test_database_unique_constraint_remains_authoritative(self):
        parcel = self.register()
        duplicate = Parcel(
            business=self.business,
            client=self.customer,
            created_by=self.user,
            tracking_code=parcel.tracking_code,
            **self.fields,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            # Bypass only validation, not the database's UNIQUE constraint.
            with patch.object(duplicate, "full_clean"):
                duplicate._domain_save(force_insert=True)
        self.assertEqual(Parcel.objects.count(), 1)

    def test_unrelated_insert_failure_is_not_retried(self):
        with (
            patch.object(Parcel, "_domain_save", side_effect=IntegrityError("other constraint")),
            patch("apps.logistics.parcel_services.generate_tracking_code") as retry,
            self.assertRaises(IntegrityError),
        ):
            self.register()
        retry.assert_not_called()
        self.assertFalse(Parcel.objects.exists())
        self.assertFalse(ParcelEvent.objects.exists())

    def test_legacy_code_survives_edit_registration_replay_and_immutability(self):
        key = uuid.uuid4()
        parcel = self.register(idempotency_key=key)
        QuerySet(model=Parcel).filter(pk=parcel.pk).update(tracking_code=LEGACY_CODE)
        replay = self.register(idempotency_key=key)
        self.assertEqual(replay.pk, parcel.pk)
        self.assertEqual(replay.tracking_code, LEGACY_CODE)
        edited = edit_parcel(
            business=self.business, actor=self.user, parcel=parcel, internal_notes="Reviewed"
        )
        self.assertEqual(edited.tracking_code, LEGACY_CODE)
        edited.full_clean()
        edited.tracking_code = generate_tracking_code()
        with self.assertRaisesMessage(ValidationError, "immutable"):
            edited._domain_save()
        parcel.refresh_from_db()
        self.assertEqual(parcel.tracking_code, LEGACY_CODE)

    def test_both_formats_search_scan_camera_public_and_manifest(self):
        shipment = create_shipment(
            business=self.business, actor=self.user, origin="Miami", destination="Curacao"
        )
        for parcel in (self.legacy_parcel(), self.register()):
            with self.subTest(code=parcel.tracking_code):
                response = self.client.get(
                    reverse("logistics_parcel_list"), {"q": parcel.tracking_code}
                )
                self.assertContains(response, parcel.tracking_code)
                for decoded in (parcel.tracking_code, "\t" + parcel.tracking_code.lower() + "\r\n"):
                    self.assertEqual(
                        resolve_scanned_parcel(
                            business=self.business, actor=self.user, code=decoded
                        ),
                        parcel,
                    )
                    response = self.client.post(
                        reverse("logistics_parcel_scan"),
                        {"tracking_code": decoded},
                        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                    )
                    self.assertContains(response, parcel.tracking_code)
                cache.clear()
                public = self.client.post(
                    reverse("logistics_public_tracking"), {"tracking_code": parcel.tracking_code}
                )
                self.assertContains(public, parcel.tracking_code)
                self.assertIn("no-store", public["Cache-Control"])
                self.assertIsNotNone(lookup_public_tracking(parcel.tracking_code))
                for bad in (
                    parcel.tracking_code.lower(),
                    " " + parcel.tracking_code,
                    parcel.tracking_code + "\n",
                ):
                    self.assertIsNone(lookup_public_tracking(bad))
                detail = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
                self.assertContains(detail, f'data-copy-tracking="{parcel.tracking_code}"')
                assign_parcel(
                    business=self.business, actor=self.user, shipment=shipment, parcel=parcel
                )
        expected = set(Parcel.objects.values_list("tracking_code", flat=True))
        manifest = generate_manifest(business=self.business, actor=self.user, shipment=shipment)
        self.assertEqual({row["tracking_code"] for row in manifest["parcels"]}, expected)
        for route, params in (
            ("logistics_shipment_detail", {}),
            ("logistics_shipment_manifest", {}),
            ("logistics_shipment_manifest", {"download": "csv"}),
        ):
            response = self.client.get(reverse(route, args=[shipment.pk]), params)
            for code in expected:
                self.assertContains(response, code)
        self.client.force_login(self.other_user)
        self.switch(self.other)
        for code in expected:
            response = self.client.post(reverse("logistics_parcel_scan"), {"tracking_code": code})
            self.assertEqual(response.status_code, 404)
            response = self.client.get(reverse("logistics_parcel_list"), {"q": code})
            self.assertEqual(list(response.context["page_obj"]), [])
            self.assertNotContains(response, 'data-copy-tracking="' + code + '"')
