from __future__ import annotations

import argparse
from datetime import time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.billings.models import Invoice, InvoiceLine
from apps.billings.services import calculate_tax_amount
from apps.businesses.models import (
    Business,
    BusinessBookingSettings,
    DemoSeedRecord,
    DemoSeedRun,
    WeeklyAvailability,
)
from apps.crm.models import BusinessService, Client, Lead, ServiceCategory

from ...demo_seed_reset import (
    RESET_MODEL_ORDER,
    DemoSeedResetError,
    build_demo_seed_reset_plan,
    execute_demo_seed_reset,
)

PLANNED_COUNT_DEFAULTS = {
    "services": 5,
    "clients": 10,
    "requests": 10,
    "appointments": 6,
    "invoices": 5,
}

SERVICE_TEMPLATES = (
    ("Property Assessment", "Property Care", "95.00", 60),
    ("Routine Maintenance Visit", "Property Care", "145.00", 90),
    ("Equipment Care Session", "Equipment Care", "180.00", 120),
    ("On-site Consultation", "Consulting", "110.00", 60),
    ("Follow-up Service Visit", "Consulting", "75.00", 45),
)

CLIENT_TEMPLATES = (
    ("Avery", "Morgan", "Coral Bay Studio", "12 Front Street", "PHILIPSBURG"),
    ("Jordan", "Ellis", "Harbor Light Cafe", "8 Marina Lane", "SIMPSON_BAY"),
    ("Casey", "Bennett", "Island Bloom Shop", "27 Palm Road", "COLE_BAY"),
    ("Riley", "Foster", "Sunrise Guest House", "4 Beacon Hill", "MAHO"),
    ("Morgan", "Reed", "Blue Horizon Design", "19 Garden Way", "BELAIR"),
    ("Taylor", "Hayes", "Seabreeze Market", "33 Bay View Drive", "GUANA_BAY"),
)


def non_negative_count(value: str) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if count < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return count


class Command(BaseCommand):
    help = "Plan or initialize demo-data seeding for one existing Business."

    def add_arguments(self, parser):
        selector = parser.add_mutually_exclusive_group(required=True)
        selector.add_argument("--business-id", type=int)
        selector.add_argument("--business-slug")

        for name, default in PLANNED_COUNT_DEFAULTS.items():
            parser.add_argument(
                f"--{name}",
                type=non_negative_count,
                default=None,
                help=f"Number to create (default: {default}).",
            )

        parser.add_argument(
            "--execute",
            action="store_true",
            help="Create tenant-scoped demo records and ownership metadata.",
        )
        parser.add_argument(
            "--booking-setup",
            action="store_true",
            help="Create missing demo booking settings and business-wide availability.",
        )
        parser.add_argument(
            "--enable-public-booking",
            action="store_true",
            help="Enable newly created booking settings when the business plan permits it.",
        )
        parser.add_argument(
            "--reset-demo",
            action="store_true",
            help="Preview removal of tracked demo records; add --execute to delete them.",
        )

    def handle(self, *args, **options):
        business_id = options.get("business_id")
        business_slug = options.get("business_slug")
        booking_setup = bool(options["booking_setup"])
        enable_public_booking = bool(options["enable_public_booking"])
        reset_demo = bool(options["reset_demo"])
        explicit_count_options = {name: options.get(name) for name in PLANNED_COUNT_DEFAULTS}
        if reset_demo and (
            any(value is not None for value in explicit_count_options.values())
            or booking_setup
            or enable_public_booking
        ):
            raise CommandError(
                "--reset-demo cannot be combined with generation counts, --booking-setup, "
                "or --enable-public-booking."
            )
        supplied_selectors = sum(
            value is not None and value != "" for value in (business_id, business_slug)
        )
        if supplied_selectors != 1:
            raise CommandError("Provide exactly one of --business-id or --business-slug.")
        if business_id is not None and business_id <= 0:
            raise CommandError("--business-id must be a positive integer.")
        if business_slug is not None:
            business_slug = business_slug.strip()
            if not business_slug:
                raise CommandError("--business-slug must not be empty.")

        lookup = {"pk": business_id} if business_id is not None else {"slug": business_slug}
        try:
            business = Business.objects.get(**lookup)
        except Business.DoesNotExist as exc:
            selector_description = (
                f"ID {business_id}" if business_id is not None else f"slug '{business_slug}'"
            )
            raise CommandError(f"Business with {selector_description} was not found.") from exc

        if reset_demo:
            self._handle_reset(business=business, execute=bool(options["execute"]))
            return

        if enable_public_booking and not booking_setup:
            raise CommandError("--enable-public-booking requires --booking-setup.")
        planned_counts = {}
        for name, default in PLANNED_COUNT_DEFAULTS.items():
            value = explicit_count_options[name]
            if value is None:
                value = default
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise CommandError(f"--{name} must be a non-negative integer.")
            planned_counts[name] = value
        if planned_counts["appointments"]:
            missing_dependencies = [
                name for name in ("services", "clients", "requests") if not planned_counts[name]
            ]
            if missing_dependencies:
                required_options = ", ".join(f"--{name}" for name in missing_dependencies)
                raise CommandError(
                    "--appointments requires at least one demo service, client, and request; "
                    f"increase {required_options} or set --appointments 0."
                )
        if planned_counts["invoices"] and not planned_counts["clients"]:
            raise CommandError("--invoices requires at least one demo client.")
        if enable_public_booking and not business.can_use_module("public_booking"):
            raise CommandError(
                "--enable-public-booking requires an active business plan that allows "
                "public booking."
            )

        self._render_plan(
            business=business,
            planned_counts=planned_counts,
            booking_setup=booking_setup,
            enable_public_booking=enable_public_booking,
        )
        if not options["execute"]:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN ONLY: no database writes were made and no demo records were created."
                )
            )
            return

        with transaction.atomic():
            try:
                locked_business = Business.objects.select_for_update().get(pk=business.pk)
            except Business.DoesNotExist as exc:
                raise CommandError("The selected business no longer exists.") from exc
            if enable_public_booking and not locked_business.can_use_module("public_booking"):
                raise CommandError("The selected business plan no longer allows public booking.")

            seed_run, created = DemoSeedRun.objects.update_or_create(
                business=locked_business,
                defaults={"planned_counts": planned_counts},
            )
            created_counts = self._create_demo_records(
                business=locked_business,
                seed_run=seed_run,
                planned_counts=planned_counts,
                booking_setup=booking_setup,
                enable_public_booking=enable_public_booking,
            )

        action = "Created" if created else "Reused"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} demo seed metadata {seed_run.run_id} for Business ID {business.pk}."
            )
        )
        self.stdout.write("Created operational demo records:")
        for name in (
            "service_categories",
            "services",
            "clients",
            "requests",
            "appointments",
            "invoices",
            "invoice_lines",
            "booking_settings",
            "availability",
        ):
            self.stdout.write(f"- {name}: {created_counts[name]}")
        self.stdout.write(f"- public_booking_enabled: {created_counts['public_booking_enabled']}")

    def _render_plan(
        self,
        *,
        business: Business,
        planned_counts: dict[str, int],
        booking_setup: bool,
        enable_public_booking: bool,
    ) -> None:
        self.stdout.write("Demo data seed plan")
        self.stdout.write(f"- Business ID: {business.pk}")
        self.stdout.write(f"- Business slug: {business.slug}")
        self.stdout.write("- Planned counts:")
        for name in PLANNED_COUNT_DEFAULTS:
            self.stdout.write(f"  - {name}: {planned_counts[name]}")
        self.stdout.write(f"- Booking setup: {booking_setup}")
        self.stdout.write(f"- Enable public booking: {enable_public_booking}")

    def _handle_reset(self, *, business: Business, execute: bool) -> None:
        if not execute:
            seed_run = DemoSeedRun.objects.filter(business=business).first()
            try:
                plan = build_demo_seed_reset_plan(
                    business=business,
                    seed_run=seed_run,
                )
            except DemoSeedResetError as exc:
                raise CommandError(str(exc)) from exc
            self._render_reset_plan(plan)
            self.stdout.write(
                self.style.WARNING(
                    "RESET PREVIEW ONLY: no demo tracking or operational records were deleted."
                )
            )
            return

        with transaction.atomic():
            try:
                locked_business = Business.objects.select_for_update().get(pk=business.pk)
            except Business.DoesNotExist as exc:
                raise CommandError("The selected business no longer exists.") from exc
            seed_run = (
                DemoSeedRun.objects.select_for_update().filter(business=locked_business).first()
            )
            try:
                plan = build_demo_seed_reset_plan(
                    business=locked_business,
                    seed_run=seed_run,
                    lock=True,
                )
            except DemoSeedResetError as exc:
                raise CommandError(str(exc)) from exc
            self._render_reset_plan(plan)
            if seed_run is None:
                result = None
            else:
                result = execute_demo_seed_reset(seed_run=seed_run, plan=plan)

        if result is None:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Business ID {business.pk} has no demo seed metadata; no changes were made."
                )
            )
            return

        self.stdout.write(self.style.SUCCESS(f"Reset demo data for Business ID {business.pk}."))
        for model in RESET_MODEL_ORDER:
            label = model._meta.label
            self.stdout.write(f"- Deleted {label}: {result.deleted_counts[label]}")
        self.stdout.write(f"- Deleted demo tracking records: {result.deleted_tracking_records}")
        self.stdout.write(f"- Deleted demo seed run: {result.deleted_seed_run}")

    def _render_reset_plan(self, plan) -> None:
        self.stdout.write("Demo data reset plan")
        self.stdout.write(f"- Business ID: {plan.business_id}")
        self.stdout.write(f"- Business slug: {plan.business_slug}")
        self.stdout.write(f"- Seed run ID: {plan.seed_run_id or 'none'}")
        self.stdout.write("- Tracked records by dependency-safe deletion order:")
        for model in RESET_MODEL_ORDER:
            label = model._meta.label
            self.stdout.write(f"  - {label}: {plan.counts[label]}")
        self.stdout.write(f"- Tracking records: {plan.tracking_record_count}")
        self.stdout.write(f"- Stale tracking records: {plan.stale_tracking_record_count}")

    def _create_demo_records(
        self,
        *,
        business: Business,
        seed_run: DemoSeedRun,
        planned_counts: dict[str, int],
        booking_setup: bool,
        enable_public_booking: bool,
    ) -> dict[str, int | bool]:
        categories: dict[str, ServiceCategory] = {}
        services: list[BusinessService] = []
        clients: list[Client] = []
        requests: list[Lead] = []
        appointments: list[Appointment] = []

        for index in range(planned_counts["services"]):
            service_name, category_name, price, duration = SERVICE_TEMPLATES[
                index % len(SERVICE_TEMPLATES)
            ]
            if category_name not in categories:
                category = ServiceCategory.objects.create(
                    business=business,
                    name=f"[DEMO] {category_name}",
                )
                self._register_created(seed_run, category)
                categories[category_name] = category

            service = BusinessService.objects.create(
                business=business,
                category=categories[category_name],
                name=f"[DEMO] {service_name} {index + 1:02d}",
                external_code=f"DEMO-SVC-{index + 1:03d}",
                description="[DEMO] Fictional service generated for workspace exploration.",
                unit_price=Decimal(price),
                tax_rate=business.tax_rate,
                is_active=True,
                is_bookable_online=booking_setup,
                default_duration_minutes=duration,
                booking_buffer_minutes=15,
                public_description="[DEMO] Sample service; not a real customer offering.",
                requires_manual_confirmation=True,
            )
            self._register_created(seed_run, service)
            services.append(service)

        for index in range(planned_counts["clients"]):
            first_name, last_name, company_name, street_address, district = CLIENT_TEMPLATES[
                index % len(CLIENT_TEMPLATES)
            ]
            cycle = index // len(CLIENT_TEMPLATES)
            display_suffix = f" {cycle + 1}" if cycle else ""
            client = Client.objects.create(
                business=business,
                first_name=first_name,
                last_name=f"{last_name}{display_suffix}",
                email=f"demo.client.{business.pk}.{index + 1:03d}@example.test",
                phone=f"+1 721 555 {1000 + index:04d}",
                client_type=Client.ClientType.BUSINESS,
                company_name=f"[DEMO] {company_name}{display_suffix}",
                industry="Sample services",
                job_title="Operations contact",
                preferred_contact_method=Client.PreferredContactMethod.EMAIL,
                client_status=Client.ClientStatus.ACTIVE,
                lead_source=Client.LeadSource.REFERRAL,
                priority=(Client.Priority.HIGH if index % 4 == 0 else Client.Priority.MEDIUM),
                interested_services=(services[index % len(services)].name if services else ""),
                street_address=street_address,
                district=district,
                country=business.country or "Sint Maarten",
                postal_code="N/A",
                notes="[DEMO] Fictional client generated for workspace exploration.",
            )
            self._register_created(seed_run, client)
            clients.append(client)

        base_start = seed_run.created_at.replace(hour=9, minute=0, second=0, microsecond=0)
        for index in range(planned_counts["requests"]):
            service = services[index % len(services)] if services else None
            client = clients[index % len(clients)] if clients else None
            start_time = base_start + timedelta(days=index + 1, hours=index % 4)
            duration_minutes = service.default_duration_minutes if service else 60
            request = Lead.objects.create(
                business=business,
                lead_type=Lead.LeadType.REQUEST,
                status=Lead.Status.NEW if index % 3 else Lead.Status.CONTACTED,
                category=service.category if service else None,
                requested_service=service,
                preferred_start_time=start_time,
                preferred_end_time=start_time + timedelta(minutes=duration_minutes),
                request_source=Lead.RequestSource.STAFF,
                first_name=client.first_name if client else "Demo",
                last_name=client.last_name if client else f"Requester {index + 1:02d}",
                email=(
                    client.email
                    if client
                    else f"demo.request.{business.pk}.{index + 1:03d}@example.test"
                ),
                phone=client.phone if client else f"+1 721 555 {3000 + index:04d}",
                company_name=(
                    client.company_name if client else f"[DEMO] Requester {index + 1:02d}"
                ),
                message="[DEMO] Fictional service request for workspace exploration.",
                street_address=client.street_address if client else "1 Demo Way",
                district=client.district if client else Lead.DistrictChoices.PHILIPSBURG,
                country=business.country or "Sint Maarten",
                postal_code="N/A",
                notes="[DEMO] Generated request; no real customer is associated with it.",
                consent_to_contact=True,
                is_active=True,
            )
            self._register_created(seed_run, request)
            requests.append(request)

        for index in range(planned_counts["appointments"]):
            client = clients[index % len(clients)]
            source_request = requests[index % len(requests)] if requests else None
            service = (
                source_request.requested_service
                if source_request and source_request.requested_service_id
                else (services[index % len(services)] if services else None)
            )
            start_time = base_start + timedelta(days=index + 1, hours=5 + (index % 3))
            duration_minutes = service.default_duration_minutes if service else 60
            appointment = Appointment.objects.create(
                business=business,
                client=client,
                service=service,
                source_lead=source_request,
                title=(
                    f"[DEMO] {service.name.removeprefix('[DEMO] ')}"
                    if service
                    else "[DEMO] Client appointment"
                ),
                start_time=start_time,
                end_time=start_time + timedelta(minutes=duration_minutes),
                status=Appointment.Status.SCHEDULED,
                location=client.street_address,
                notes="[DEMO] Fictional appointment generated for workspace exploration.",
            )
            self._register_created(seed_run, appointment)
            appointments.append(appointment)

        invoices: list[Invoice] = []
        invoice_lines: list[InvoiceLine] = []
        invoice_sequence = seed_run.owned_records.filter(model_label=Invoice._meta.label).count()
        for index in range(planned_counts["invoices"]):
            appointment = appointments[index % len(appointments)] if appointments else None
            client = appointment.client if appointment else clients[index % len(clients)]
            invoice_sequence += 1
            invoice_number = self._next_demo_invoice_number(
                business=business,
                seed_run=seed_run,
                starting_sequence=invoice_sequence,
            )
            invoice = Invoice.objects.create(
                invoice_number=invoice_number,
                business=business,
                client=client,
                appointment=appointment,
                status=Invoice.Status.DRAFT,
                notes="[DEMO] Fictional invoice generated for workspace exploration.",
            )
            self._register_created(seed_run, invoice)
            invoices.append(invoice)

            selected_services: list[BusinessService | None]
            if services:
                selected_services = [services[index % len(services)]]
                if len(services) > 1:
                    selected_services.append(services[(index + 1) % len(services)])
            else:
                selected_services = [None]

            for line_index, service in enumerate(selected_services):
                quantity = Decimal("1.00") if line_index == 0 else Decimal("2.00")
                unit_price = (
                    service.unit_price
                    if service is not None
                    else Decimal("85.00") + Decimal(index * 10)
                )
                line = InvoiceLine.objects.create(
                    invoice=invoice,
                    service=service,
                    description=(
                        f"[DEMO] {service.name.removeprefix('[DEMO] ')}"
                        if service is not None
                        else "[DEMO] General service visit"
                    ),
                    quantity=quantity,
                    unit_price=unit_price,
                )
                self._register_created(seed_run, line)
                invoice_lines.append(line)

            invoice.subtotal = sum(
                (
                    line.line_total
                    for line in InvoiceLine.objects.filter(invoice=invoice).only("line_total")
                ),
                start=Decimal("0.00"),
            )
            invoice.tax = calculate_tax_amount(
                subtotal=invoice.subtotal,
                tax_rate=business.tax_rate,
            )
            invoice.total = invoice.subtotal + invoice.tax
            invoice.save(update_fields=["subtotal", "tax", "total"])

        booking_settings_created = 0
        availability_created = 0
        public_booking_enabled = False
        if booking_setup:
            owned_service_pks = [
                int(object_pk)
                for object_pk in seed_run.owned_records.filter(
                    model_label=BusinessService._meta.label,
                ).values_list("object_pk", flat=True)
                if object_pk.isdigit()
            ]
            BusinessService.objects.filter(
                business=business,
                pk__in=owned_service_pks,
                is_bookable_online=False,
            ).update(
                is_bookable_online=True,
                updated_at=timezone.now(),
            )
            try:
                booking_settings = BusinessBookingSettings.objects.select_for_update().get(
                    business=business
                )
            except BusinessBookingSettings.DoesNotExist:
                booking_settings = BusinessBookingSettings.objects.create(
                    business=business,
                    booking_enabled=enable_public_booking,
                    default_duration_minutes=60,
                    minimum_notice_hours=24,
                    maximum_days_ahead=60,
                    buffer_minutes=15,
                    confirmation_mode=BusinessBookingSettings.ConfirmationMode.REQUEST_ONLY,
                    public_booking_instructions=(
                        "[DEMO] Choose a sample service and preferred appointment time."
                    ),
                    cancellation_policy_text="[DEMO] Sample cancellation policy.",
                    reschedule_policy_text="[DEMO] Sample rescheduling policy.",
                )
                self._register_created(seed_run, booking_settings)
                booking_settings_created = 1
            else:
                settings_is_demo_owned = seed_run.owned_records.filter(
                    model_label=BusinessBookingSettings._meta.label,
                    object_pk=str(booking_settings.pk),
                ).exists()
                if (
                    enable_public_booking
                    and settings_is_demo_owned
                    and not booking_settings.booking_enabled
                ):
                    booking_settings.booking_enabled = True
                    booking_settings.save(update_fields=["booking_enabled", "updated_at"])

            public_booking_enabled = booking_settings.booking_enabled
            if not WeeklyAvailability.objects.filter(
                business=business,
                is_active=True,
            ).exists():
                for day_of_week in (
                    WeeklyAvailability.DayOfWeek.MONDAY,
                    WeeklyAvailability.DayOfWeek.TUESDAY,
                    WeeklyAvailability.DayOfWeek.WEDNESDAY,
                    WeeklyAvailability.DayOfWeek.THURSDAY,
                    WeeklyAvailability.DayOfWeek.FRIDAY,
                ):
                    availability = WeeklyAvailability.objects.create(
                        business=business,
                        day_of_week=day_of_week,
                        start_time=time(9, 0),
                        end_time=time(17, 0),
                        is_active=True,
                    )
                    self._register_created(seed_run, availability)
                    availability_created += 1

        return {
            "service_categories": len(categories),
            "services": len(services),
            "clients": len(clients),
            "requests": len(requests),
            "appointments": len(appointments),
            "invoices": len(invoices),
            "invoice_lines": len(invoice_lines),
            "booking_settings": booking_settings_created,
            "availability": availability_created,
            "public_booking_enabled": public_booking_enabled,
        }

    @staticmethod
    def _next_demo_invoice_number(
        *,
        business: Business,
        seed_run: DemoSeedRun,
        starting_sequence: int,
    ) -> str:
        sequence = starting_sequence
        run_prefix = str(seed_run.run_id).split("-", maxsplit=1)[0].upper()
        while True:
            candidate = f"DEMO-{run_prefix}-{sequence:04d}"
            if not Invoice.objects.filter(
                business=business,
                invoice_number=candidate,
            ).exists():
                return candidate
            sequence += 1

    @staticmethod
    def _register_created(seed_run: DemoSeedRun, instance) -> None:
        DemoSeedRecord.objects.create(
            seed_run=seed_run,
            model_label=instance._meta.label,
            object_pk=str(instance.pk),
        )
