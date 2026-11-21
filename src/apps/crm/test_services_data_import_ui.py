"""Import UI contracts and domain preservation on owned synthetic PostgreSQL only."""

import os
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.businesses.models import BusinessUser, ClarivoPlan
from apps.businesses.test_service_allowances import ServicesFixture
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import BusinessService, ImportJob, Lead, ServiceCategory
from apps.crm.models import Client as CRMClient
from apps.crm.test_services_dashboard_ui import assert_disposable


class DataImportPresentationTests(ServicesFixture, TestCase):
    def setUp(self):
        assert_disposable()
        super().setUp()
        self.login()

    def upload(self, kind, body):
        route = {
            "clients": "client_import_upload",
            "leads": "lead_import_upload",
            "services": "business_service_import",
        }[kind]
        return self.client.post(
            reverse(route),
            {
                "csv_file": SimpleUploadedFile(
                    kind + "-fixture.csv", body.encode(), content_type="text/csv"
                )
            },
        )

    def job(self, response):
        self.assertEqual(response.status_code, 302)
        return ImportJob.objects.get(pk=response.url.rstrip("/").split("/")[-2])

    def test_uploads_have_truthful_domain_guidance_and_preserve_client_import(self):
        before = ImportJob.objects.count()
        for name in ["lead_import_upload", "business_service_import"]:
            response = self.client.get(reverse(name))
            self.assertContains(response, "mm-services-data-import")
            self.assertContains(response, "No records are created or updated before you confirm")
            self.assertContains(response, 'name="csv_file"')
            self.assertContains(response, "All fields are optional")
            self.assertContains(response, "500 data rows")
        client = self.client.get(reverse("client_import_upload"))
        self.assertContains(client, "mm-services-clients")
        self.assertNotContains(client, "services-data-import.css")
        self.assertEqual(ImportJob.objects.count(), before)

    def test_lead_native_contract_preview_confirm_replay_without_other_side_effects(self):
        baseline = (
            CRMClient.objects.count(),
            Appointment.objects.count(),
            Invoice.objects.count(),
            Lead.objects.count(),
        )
        job = self.job(
            self.upload(
                "leads", "first_name,email,lead_type\nHistorical,historical@fixture.test,REQUEST\n"
            )
        )
        self.assertEqual(Lead.objects.count(), baseline[3])
        response = self.client.get(reverse("lead_import_preview", args=[job.pk]))
        self.assertContains(response, "Confirm Lead Import")
        self.assertTrue(response.context["preview"]["ready"])
        target = reverse("lead_import_execute", args=[job.pk])
        self.assertEqual(self.client.get(target).status_code, 405)
        self.client.post(target)
        self.client.post(target)
        self.assertEqual(Lead.objects.count(), baseline[3] + 1)
        self.assertEqual(
            (CRMClient.objects.count(), Appointment.objects.count(), Invoice.objects.count()),
            baseline[:3],
        )
        result = self.client.get(reverse("lead_import_result", args=[job.pk]))
        self.assertContains(result, "Import already completed")

    def test_service_update_and_new_category_are_atomic_after_confirm(self):
        self.service.external_code = "MATCH-SVC"
        self.service.save(update_fields=["external_code"])
        count = ServiceCategory.objects.count()
        job = self.job(
            self.upload(
                "services", "external_code,unit_price,category\nMATCH-SVC,77.50,Imported category\n"
            )
        )
        self.service.refresh_from_db()
        self.assertEqual(self.service.unit_price, Decimal("50.00"))
        self.assertEqual(ServiceCategory.objects.count(), count)
        preview = self.client.get(reverse("business_service_import_preview", args=[job.pk]))
        self.assertEqual(preview.context["summary"]["update_count"], 1)
        self.assertContains(preview, "Confirm Service Import")
        self.client.post(reverse("business_service_import_execute", args=[job.pk]))
        self.client.post(reverse("business_service_import_execute", args=[job.pk]))
        self.service.refresh_from_db()
        self.assertEqual(self.service.unit_price, Decimal("77.50"))
        self.assertEqual(self.service.name, "Consultation")
        self.assertTrue(self.service.is_bookable_online)
        self.assertEqual(self.service.category.name, "Imported category")
        self.assertEqual(ServiceCategory.objects.count(), count + 1)

    def test_invalid_and_expired_previews_keep_confirmation_unavailable(self):
        before = BusinessService.objects.count()
        blocked = self.job(self.upload("services", "name,unit_price\nBad,-10\n"))
        response = self.client.get(reverse("business_service_import_preview", args=[blocked.pk]))
        self.assertContains(response, "Confirmation is unavailable")
        self.assertNotContains(response, 'type="submit">Confirm Service Import')
        self.client.post(reverse("business_service_import_execute", args=[blocked.pk]))
        self.assertEqual(BusinessService.objects.count(), before)
        ready = self.job(self.upload("leads", "first_name,email\nExpired,expired@fixture.test\n"))
        ready.transition_to(ImportJob.Status.EXPIRED)
        response = self.client.get(reverse("lead_import_preview", args=[ready.pk]))
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, "Create a New Preview", status_code=410)

    def test_owner_actor_binding_and_csrf_are_retained(self):
        job = self.job(self.upload("leads", "first_name,email\nPrivate,private@fixture.test\n"))
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        session = guarded.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.assertEqual(
            guarded.post(reverse("lead_import_execute", args=[job.pk])).status_code, 403
        )
        other = self.user()
        BusinessUser.objects.create(business=self.business, user=other, role="staff")
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(reverse("lead_import_preview", args=[job.pk])).status_code, 403
        )
        self.assertEqual(
            self.client.post(reverse("lead_import_execute", args=[job.pk])).status_code, 403
        )

    def test_history_has_only_sanitized_terminal_metadata(self):
        job = self.job(
            self.upload(
                "leads",
                "first_name,email,notes\nPrivate,secret-row@fixture.test,DO-NOT-EXPOSE-PAYLOAD\n",
            )
        )
        self.assertEqual(
            self.client.get(reverse("import_history_detail", args=[job.pk])).status_code, 404
        )
        self.client.post(reverse("lead_import_execute", args=[job.pk]))
        for url in [reverse("import_history"), reverse("import_history_detail", args=[job.pk])]:
            response = self.client.get(url)
            self.assertContains(response, "leads-fixture.csv")
            self.assertNotContains(response, "secret-row@fixture.test")
            self.assertNotContains(response, "DO-NOT-EXPOSE-PAYLOAD")
            self.assertNotContains(response, job.file_digest)

    def test_hub_preserves_role_capability_flags(self):
        for role in ["owner", "admin", "staff", "accountant", "viewer"]:
            self.member.role = role
            self.member.save(update_fields=["role"])
            response = self.client.get(reverse("data_import"))
            if role == "viewer":
                self.assertEqual(response.status_code, 302)
                continue
            self.assertContains(response, "mm-services-data-import")
            self.assertTrue(response.context["can_import_clients"])
            self.assertEqual(response.context["can_import_services"], role in ["owner", "admin"])
            self.assertEqual(
                response.context["can_import_leads"], role in ["owner", "admin", "staff"]
            )
            self.assertEqual(
                response.context["can_view_import_history"], role in ["owner", "admin"]
            )

    def test_logistics_entry_templates_match_original_rendering(self):
        job = self.job(self.upload("services", "name,unit_price\nPreview service,12.00\n"))
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        self.business.vertical = "LOGISTICS"
        self.business.save(update_fields=["vertical"])
        self.subscription.plan = plan
        self.subscription.billing_interval = "yearly"
        self.subscription.save()
        original = Path(os.environ["SERVICES_DATA_IMPORT_BEFORE"]) / "src/templates"
        templates = [
            {**settings.TEMPLATES[0], "DIRS": [str(original), *settings.TEMPLATES[0]["DIRS"]]}
        ]

        def clean(value):
            tokens = re.sub(
                r'name="csrfmiddlewaretoken" value="[^"]+"',
                'name="csrfmiddlewaretoken" value="NORMALIZED"',
                value.decode(),
            )
            return re.sub(r">\s+<", "><", tokens).strip()

        for route, args in [
            ("data_import", []),
            ("business_service_import", []),
            ("business_service_import_preview", [job.pk]),
            ("import_history", []),
        ]:
            current = self.client.get(reverse(route, args=args))
            with override_settings(TEMPLATES=templates):
                before = self.client.get(reverse(route, args=args))
            self.assertEqual(current.status_code, 200)
            self.assertNotContains(current, "services-data-import.css")
            self.assertEqual(clean(current.content), clean(before.content))
