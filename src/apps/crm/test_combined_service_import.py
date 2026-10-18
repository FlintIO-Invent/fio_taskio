from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.businesses.models import Business, BusinessSubscription, ClarivoPlan

from .importing.service_execution import ServiceImportExecutionCode
from .models import BusinessService, ServiceCategory
from .test_service_execution import ServiceExecutionTestMixin


class CombinedImportTests(ServiceExecutionTestMixin, TestCase):
    def test_categories_resolve_once_with_existing_and_foreign_names(self):
        other = Business.objects.create(name="Other", slug="other-category-workspace")
        foreign = ServiceCategory.objects.create(business=other, name="New category")
        legacy = ServiceCategory.objects.create(name="New category")
        existing = ServiceCategory.objects.create(business=self.business, name="Existing")
        rows = [
            {
                **self.base_row,
                "name": str(index),
                "external_code": f"ROW-{index}",
                "category": category,
            }
            for index, category in enumerate(
                ("New category", "new CATEGORY", "Existing", "existing")
            )
        ]
        job = self.ready_job(rows)
        self.assertEqual(self.business.service_categories.count(), 1)
        result = self.execute(job)
        self.assertTrue(result.completed)
        self.assertEqual(result.categories_created, 1)
        services = list(self.business.business_services.order_by("name"))
        self.assertEqual(services[0].category_id, services[1].category_id)
        self.assertNotIn(services[0].category_id, (foreign.pk, legacy.pk))
        self.assertEqual([s.category_id for s in services[2:]], [existing.pk, existing.pk])
        self.assertEqual(services[0].tax_rate, self.business.tax_rate)

    def test_invalid_row_blocks_all_categories_and_services(self):
        job, preview = self.job_for(
            [
                self.base_row,
                {**self.base_row, "external_code": "BAD", "unit_price": "invalid"},
            ]
        )
        self.assertFalse(preview.ready)
        self.assertEqual(preview.summary.error_count, 1)
        self.assertEqual(preview.rows[1].row_number, 3)
        self.assertEqual(self.execute(job).code, ServiceImportExecutionCode.NOT_READY)
        self.assertFalse(self.business.business_services.exists())
        self.assertFalse(self.business.service_categories.exists())

    def test_later_service_failure_rolls_back_new_categories_and_prior_service(self):
        job = self.ready_job(
            [
                self.base_row,
                {**self.base_row, "external_code": "SECOND", "name": "Second"},
            ]
        )
        original_save = BusinessService.save

        def save_or_fail(service, *args, **kwargs):
            if service.external_code == "SECOND":
                raise RuntimeError("Later row failed")
            return original_save(service, *args, **kwargs)

        with patch.object(BusinessService, "save", save_or_fail):
            self.assertEqual(self.execute(job).code, ServiceImportExecutionCode.FAILED)
        self.assertFalse(self.business.business_services.exists())
        self.assertFalse(self.business.service_categories.exists())

    def test_combined_upload_and_template_are_accessible(self):
        self.login()
        response = self.client.get(reverse("business_service_import"))
        self.assertContains(response, "Upload Categories and Services")
        self.assertContains(response, reverse("business_service_sample_csv"))
        template = self.client.get(reverse("business_service_sample_csv"))
        self.assertEqual(template.status_code, 200)
        self.assertIn("category", template.content.decode().splitlines()[0].split(","))


class LogisticsCombinedImportTests(CombinedImportTests):
    def setUp(self):
        super().setUp()
        self.business.vertical = Business.Vertical.LOGISTICS
        self.business.save(update_fields=["vertical"])
        ClarivoPlan.objects.filter(slug="logistics").update(is_active=True)
        BusinessSubscription.objects.filter(business=self.business).update(
            plan=ClarivoPlan.objects.get(slug="logistics"),
            billing_interval=BusinessSubscription.BillingInterval.YEARLY,
        )
