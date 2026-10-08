"""Classification is tenant metadata, independent of product eligibility and access."""

import json
from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.businesses.business_data_inventory import (
    build_business_data_inventory,
    find_unregistered_direct_business_relations,
)
from apps.businesses.business_data_operations import deactivate_business
from apps.businesses.business_data_purge import purge_business
from apps.businesses.models import Business

from . import test_parcels
from .classification import OperatingArea, TransportationMode
from .enrollment import enroll_application, issue_enrollment_link
from .forms import LogisticsApplicationForm
from .models import LogisticsApplication, LogisticsProfile
from .test_enrollment import PASSWORD, reviewer
from .tests import PILOT_POLICY, application_data


class ClassificationValidationTests(TestCase):
    def test_application_requires_areas_and_transportation_modes(self):
        for changes, field in (
            ({"operating_areas": []}, "operating_areas"),
            ({"transportation_modes": []}, "transportation_modes"),
            ({"operating_areas": ["WAREHOUSING"]}, "transportation_modes"),
            ({"operating_areas": ["UNKNOWN"]}, "operating_areas"),
            ({"transportation_modes": ["Sea"]}, "transportation_modes"),
        ):
            with self.subTest(changes=changes):
                form = LogisticsApplicationForm(data=application_data(**changes))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)
                with self.assertRaises(ValidationError):
                    LogisticsApplication.objects.create(**application_data(**changes))

    def test_multiple_selections_and_no_transportation_are_supported(self):
        for changes in (
            {
                "operating_areas": OperatingArea.values,
                "transportation_modes": TransportationMode.values,
            },
            {
                "operating_areas": ["WAREHOUSING", "INVENTORY_MANAGEMENT", "ORDER_PROCESSING"],
                "transportation_modes": [],
            },
        ):
            form = LogisticsApplicationForm(data=application_data(**changes))
            self.assertTrue(form.is_valid(), form.errors)
            application = form.save()
            self.assertEqual(application.operating_areas, changes["operating_areas"])
            self.assertEqual(application.transportation_modes, changes["transportation_modes"])

    def test_profiles_validate_values_and_service_and_one_per_business(self):
        service = Business.objects.create(name="Service", slug="service")
        self.assertFalse(LogisticsProfile.objects.filter(business=service).exists())
        with self.assertRaises(ValidationError):
            LogisticsProfile.objects.create(business=service)
        business = Business.objects.create(name="Logistics", slug="logistics", vertical="LOGISTICS")
        profile = LogisticsProfile.objects.create(business=business)
        self.assertTrue(profile.has_operating_area(OperatingArea.TRANSPORTATION))
        self.assertFalse(profile.has_transport_mode(TransportationMode.SEA))
        self.assertFalse(profile.has_operating_area("UNKNOWN"))
        with self.assertRaises(ValidationError):
            LogisticsProfile.objects.create(business=business)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LogisticsProfile.objects.bulk_create([LogisticsProfile(business=business)])
        for areas, modes in (
            ([], []),
            (["UNKNOWN"], []),
            (["WAREHOUSING"], ["SEA"]),
            (["TRANSPORTATION"], ["UNKNOWN"]),
            (["TRANSPORTATION"] * 2, []),
            ("TRANSPORTATION", []),
            ([{}], []),
        ):
            profile.operating_areas, profile.transportation_modes = areas, modes
            with self.subTest(areas=areas, modes=modes), self.assertRaises(ValidationError):
                profile.save()

    def test_admin_uses_validated_multiselect_forms(self):
        from django.test import RequestFactory

        actor = reviewer()
        actor.is_superuser = True
        request = RequestFactory().get("/admin/")
        request.user = actor
        for model, values in (
            (LogisticsApplication, application_data(operating_areas=["WAREHOUSING"])),
            (
                LogisticsProfile,
                {
                    "business": Business.objects.create(name="Service", slug="admin-service").pk,
                    "operating_areas": ["WAREHOUSING"],
                    "transportation_modes": [],
                },
            ),
        ):
            form_class = admin.site._registry[model].get_form(request)
            form = form_class(data=values)
            self.assertFalse(form.is_valid())
            self.assertIn("operating_areas", form.fields)
            self.assertIn("transportation_modes", form.fields)

    def test_admin_preserves_checkbox_initial_values_and_withdrawn_readonly_fields(self):
        from django.test import RequestFactory

        from .services import review_application

        actor = reviewer()
        actor.is_superuser = True
        request = RequestFactory().get("/admin/")
        request.user = actor
        application = LogisticsApplication.objects.create(**application_data())
        model_admin = admin.site._registry[LogisticsApplication]
        form_class = model_admin.get_form(request, application)
        form = form_class(instance=application)
        self.assertEqual(form.initial["transportation_modes"], ["ROAD"])
        self.assertIn("checked", str(form["transportation_modes"]))
        valid = form_class(
            data=application_data(operating_areas=["WAREHOUSING"], transportation_modes=[]),
            instance=application,
        )
        self.assertTrue(valid.is_valid(), valid.errors)
        review_application(
            application.pk,
            result="WITHDRAWN",
            actor=actor,
            reason="Withdrawal recorded",
            expected_revision=1,
        )
        application.refresh_from_db()
        withdrawn = model_admin.get_form(request, application)(instance=application)
        self.assertNotIn("operating_areas", withdrawn.fields)


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY)
class ClassificationProvisioningTests(TestCase):
    def setUp(self):
        self.actor = reviewer()
        self.application = LogisticsApplication.objects.create(
            **application_data(
                operating_areas=["TRANSPORTATION", "WAREHOUSING"],
                transportation_modes=["SEA", "ROAD"],
            )
        )
        self.token = issue_enrollment_link(
            self.application.pk, actor=self.actor, expected_revision=1
        )

    def test_conversion_copies_values_and_retry_preserves_later_profile_edits(self):
        result = enroll_application(self.token, password=PASSWORD)
        profile = result.business.logistics_profile
        self.assertEqual(profile.operating_areas, self.application.operating_areas)
        self.assertEqual(profile.transportation_modes, self.application.transportation_modes)
        profile.operating_areas, profile.transportation_modes = ["WAREHOUSING"], []
        profile.save()
        retry = enroll_application(self.token, authenticated_user=result.user)
        self.assertTrue(retry.reused)
        self.assertEqual(LogisticsProfile.objects.count(), 1)
        profile.refresh_from_db()
        self.assertEqual(profile.operating_areas, ["WAREHOUSING"])
        self.application.refresh_from_db()
        self.assertEqual(self.application.operating_areas, ["TRANSPORTATION", "WAREHOUSING"])
        self.assertEqual(
            self.application.decisions.first().evaluated_inputs["transportation_modes"],
            ["SEA", "ROAD"],
        )

    def test_profile_failure_rolls_back_conversion(self):
        with patch.object(LogisticsProfile, "save", side_effect=ValidationError("profile failure")):
            with self.assertRaises(ValidationError):
                enroll_application(self.token, password=PASSWORD)
        self.assertFalse(Business.objects.exists())
        self.application.refresh_from_db()
        self.assertIsNone(self.application.business_id)
        self.assertIsNone(self.application.enrollment_tokens.get().used_at)

    @override_settings(LOGISTICS_AUTO_APPROVE_ALL=False)
    def test_classification_changes_revise_approval_and_revoke_tokens(self):
        self.application.operating_areas, self.application.transportation_modes = [
            "WAREHOUSING"
        ], []
        self.application.save()
        self.assertEqual(self.application.revision, 2)
        self.assertEqual(self.application.approved_revision, 2)
        self.assertEqual(self.application.reason_codes, [])
        self.assertIsNotNone(self.application.enrollment_tokens.get().revoked_at)
        self.assertEqual(self.application.decisions.count(), 2)
        self.assertEqual(
            self.application.decisions.last().evaluated_inputs["operating_areas"],
            ["TRANSPORTATION", "WAREHOUSING"],
        )

    def test_selection_order_is_not_a_material_revision(self):
        self.application.operating_areas.reverse()
        self.application.transportation_modes.reverse()
        self.application.save()
        self.assertEqual(self.application.revision, 1)
        self.assertEqual(self.application.decisions.count(), 1)

    def test_inspection_and_deactivation_and_purge(self):
        result = enroll_application(self.token, password=PASSWORD)
        output = StringIO()
        call_command(
            "inspect_logistics_application", application_id=self.application.pk, stdout=output
        )
        self.assertEqual(json.loads(output.getvalue())["transportation_modes"], ["SEA", "ROAD"])
        inventory = build_business_data_inventory(result.business)
        self.assertEqual(
            inventory.logistics["operating_profile"]["operating_areas"],
            ["TRANSPORTATION", "WAREHOUSING"],
        )
        self.assertEqual(find_unregistered_direct_business_relations(), ())
        deactivate_business(
            business_id=result.business.pk, reason_reference="classification-test", operator_id=None
        )
        self.assertTrue(LogisticsProfile.objects.filter(business=result.business).exists())
        purge_business(business_id=result.business.pk, reason_reference="classification-test")
        self.assertFalse(LogisticsProfile.objects.exists())
        self.application.refresh_from_db()
        self.assertEqual(self.application.transportation_modes, ["SEA", "ROAD"])
        self.assertIsNotNone(self.application.business_id_snapshot)


class ClassificationWorkspaceTests(TestCase):
    setUp = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch

    def test_settings_are_tenant_scoped_and_do_not_gate_parcels(self):
        LogisticsProfile.objects.create(business=self.business, operating_areas=["WAREHOUSING"])
        LogisticsProfile.objects.create(business=self.other, transportation_modes=["RAIL"])
        self.client.force_login(self.user)
        session = self.client.session
        session["current_business_id"] = self.business.pk
        session.save()
        response = self.client.get(reverse("business_settings"))
        self.assertContains(response, "Warehousing")
        self.assertNotContains(response, "Rail")
        self.assertEqual(self.client.get(reverse("logistics_parcel_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("logistics_shipment_list")).status_code, 200)


class ClassificationMigrationTests(TransactionTestCase):
    def test_backfill_only_logistics_and_preserves_application_history(self):
        old = [("logistics", "0009_shipment_write_safety")]
        new = [("logistics", "0010_operating_classification")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(old)
        try:
            historical = executor.loader.project_state(old).apps
            BusinessModel = historical.get_model("businesses", "Business")
            logistics = BusinessModel.objects.create(
                name="Old Logistics", slug="old-logistics", vertical="LOGISTICS"
            )
            service = BusinessModel.objects.create(
                name="Old Service", slug="old-service", vertical="SERVICE"
            )
            Application = historical.get_model("logistics", "LogisticsApplication")
            application = Application.objects.create(
                **{
                    k: v
                    for k, v in application_data().items()
                    if k not in {"operating_areas", "transportation_modes"}
                }
            )
            MigrationExecutor(connection).migrate(new)
            profile = LogisticsProfile.objects.get(business_id=logistics.pk)
            self.assertEqual(profile.operating_areas, ["TRANSPORTATION"])
            self.assertEqual(profile.transportation_modes, [])
            self.assertFalse(LogisticsProfile.objects.filter(business_id=service.pk).exists())
            migrated = LogisticsApplication.objects.get(pk=application.pk)
            self.assertEqual(migrated.operating_areas, [])
            self.assertEqual(migrated.transportation_modes, [])
            self.assertEqual(migrated.revision, application.revision)
            self.assertEqual(migrated.updated_at, application.updated_at)
            migrated.operational_notes = "Unrelated legacy correction"
            migrated.save()
            self.assertEqual(migrated.operating_areas, [])
        finally:
            MigrationExecutor(connection).migrate(latest)
