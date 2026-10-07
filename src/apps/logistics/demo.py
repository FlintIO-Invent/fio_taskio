"""Varied, attributable Logistics demo data created through operational services."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.billings.models import Invoice, InvoiceLine
from apps.businesses.demo_seed_reset import (
    build_demo_seed_reset_plan,
    execute_demo_seed_reset,
)
from apps.businesses.models import Business, BusinessUser, DemoSeedRecord, DemoSeedRun
from apps.crm.models import ActivityLog, BusinessService, Client

from .billing_services import add_charge, invoice_charges
from .classification import OperatingArea, TransportationMode
from .models import LogisticsCharge, LogisticsProfile, Parcel, ParcelEvent, Shipment
from .parcel_policy import PARCEL_MANAGE_ROLES
from .parcel_services import (
    change_parcel_status,
    edit_parcel,
    record_parcel_event,
    register_parcel,
    require_parcel_access,
)
from .shipment_services import (
    assign_parcel,
    change_shipment_status,
    create_shipment,
    require_shipment_access,
)

LOGISTICS_RESET_ORDER = (
    LogisticsCharge,
    InvoiceLine,
    Invoice,
    ActivityLog,
    ParcelEvent,
    Parcel,
    Shipment,
    Client,
    BusinessService,
)
LOGISTICS_DEMO_COUNTS = {
    "clients": 10,
    "parcels": 20,
    "parcel_events": 83,
    "shipments": 6,
    "services": 8,
    "logistics_charges": 9,
    "invoices": 3,
    "invoice_lines": 5,
    "activity_logs": 3,
}

CLIENT_TEMPLATES = (
    ("Avery", "Morgan", "Coral Bay Books"),
    ("Jordan", "Ellis", "Harbor Cafe"),
    ("Casey", "Bennett", "Island Supplies"),
    ("Riley", "Foster", "Sunrise Guest House"),
    ("Morgan", "Reed", "Blue Horizon Design"),
    ("Taylor", "Hayes", "Seabreeze Market"),
    ("Alex", "Rivera", "Palm Garden Nursery"),
    ("Sam", "Brooks", "Marina Outfitters"),
    ("Jamie", "Clarke", "Beachside Ceramics"),
    ("Drew", "Parker", "Island Cycle Shop"),
)

# A shipment's route also supplies the route and transport metadata of its members.
ROUTES = (
    ("Miami consolidation depot", "Philipsburg collection depot", "Sea", "USMIA", "SXPHI"),
    ("San Juan air cargo terminal", "Simpson Bay airport depot", "Air", "PRSJU", "SXSXM"),
    ("Philipsburg warehouse", "Cole Bay delivery hub", "Road", "", ""),
)
SHIPMENT_ROUTE_INDEXES = (0, 1, 0, 1, 2, 0)
ASSIGNED_PARCEL_ROUTE_INDEXES = (0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 2, 2)


def parcel_demo_fields(*, index, client, route, today):
    """Predictable metadata, including one minimal parcel and optional-field gaps."""
    origin, destination, mode, loading_port, discharge_port = route
    fields = {
        "origin": origin,
        "destination": destination,
        "package_description": (
            "Books and stationery",
            "Cafe supplies and reusable cups",
            "Cotton clothing",
            "Ceramic tableware",
            "Compostable food containers",
        )[index % 5],
        "internal_reference": f"DEMO-{index + 1:03d}",
    }
    if index == 19:
        return fields  # New registration before weighing, addressing and routing.
    length = Decimal(20 + index * 2)
    width = Decimal(15 + index)
    height = Decimal(10 + index)
    fields.update(
        quantity=1 + index % 4,
        weight_kg=Decimal("0.750") + Decimal(index) * Decimal("0.625"),
        length_cm=length if index % 4 != 2 else None,
        width_cm=width if index % 4 != 2 else None,
        height_cm=height if index % 4 != 2 else None,
        volume_m3=(
            (length * width * height / Decimal("1000000")).quantize(Decimal("0.001"))
            if index % 4 != 2
            else None
        ),
        dimensions=f"{length} x {width} x {height} cm" if index % 4 == 2 else "",
        declared_value=Decimal("35.00") + Decimal(index * 18) if index % 4 != 3 else None,
        hs_code=("490199", "392410", "610910", "691200", "482369")[index % 5],
        marks_numbers=f"DEMO-BOX-{index + 1:03d}" if index % 3 != 2 else "",
        sender_name=f"Demo {'Mainland Supply' if mode != 'Road' else 'Island Distribution'}",
        sender_contact="dispatch@example.test" if index % 4 != 1 else "",
        sender_address=f"{100 + index} Demo Cargo Road, {origin.split()[0]}",
        sender_country_code="SX" if mode == "Road" else "US",
        sender_tax_id=f"DEMO-TAX-{index + 1:03d}" if mode == "Sea" else "",
        recipient_name=f"{client.first_name} {client.last_name}",
        recipient_contact=client.email if index % 2 == 0 else client.phone,
        recipient_address=f"{client.street_address}, Sint Maarten" if index % 4 != 1 else "",
        mode_of_transport=mode,
        vessel_name="Demo Coral Voyager" if mode == "Sea" else "Demo Island Cargo",
        voyage_no=f"DEMO-VOY-{index // 3 + 1:02d}" if mode == "Sea" else "",
        imo_no="9074729" if mode == "Sea" else "",
        port_load_unlocode=loading_port,
        port_discharge_unlocode=discharge_port,
        master_bl_no=f"DEMO-MBL-{index // 3 + 1:03d}" if mode == "Sea" else "",
        house_bl_no=f"DEMO-HBL-{index + 1:03d}" if mode == "Sea" else "",
        issue_date=today - timedelta(days=2 + index % 8) if mode == "Sea" else None,
        incoterms=("DAP", "CIF", "EXW")[index % 3],
        fragile_goods=index % 5 == 3,
        biodegradable_goods=index % 5 == 4,
        expiry_date=today + timedelta(days=30 + index) if index % 5 == 4 else None,
        internal_notes="[DEMO] Keep dry; check packaging before release." if index % 3 == 0 else "",
    )
    return fields


def require_logistics_business(business):
    if business.vertical != Business.Vertical.LOGISTICS:
        raise ValidationError("Logistics demo tooling requires an existing LOGISTICS Business.")


def demo_actor(*, business, actor_id=None):
    require_logistics_business(business)
    members = (
        BusinessUser.objects.filter(
            business=business, is_active=True, user__is_active=True, role__in=PARCEL_MANAGE_ROLES
        )
        .select_related("user")
        .order_by("user_id")
    )
    if actor_id is not None:
        members = members.filter(user_id=actor_id)
    member = members.first()
    if member is None:
        raise ValidationError("Seeding requires an existing active Logistics operator membership.")
    require_parcel_access(business=business, actor=member.user, write=True)
    require_shipment_access(business=business, actor=member.user, write=True)
    return member.user


@transaction.atomic
def seed_logistics_demo(*, business_id, actor_id=None):
    business = Business.objects.select_for_update().get(pk=business_id)
    require_logistics_business(business)
    if DemoSeedRun.objects.filter(business=business).exists():
        raise ValidationError(
            "Demo ownership metadata already exists; preview/reset it before seeding again."
        )
    actor = demo_actor(business=business, actor_id=actor_id)
    profile, created = LogisticsProfile.objects.get_or_create(business=business)
    # Fill only the legacy/default unknown-mode profile, preserving explicit settings.
    if created or (
        profile.operating_areas == [OperatingArea.TRANSPORTATION]
        and not profile.transportation_modes
    ):
        profile.transportation_modes = [
            TransportationMode.SEA,
            TransportationMode.AIR,
            TransportationMode.ROAD,
        ]
        profile.save(update_fields=["transportation_modes", "updated_at"])
    seed = DemoSeedRun.objects.create(business=business, planned_counts=LOGISTICS_DEMO_COUNTS)
    now = timezone.now()
    today = timezone.localdate(now)

    def own(obj):
        DemoSeedRecord.objects.create(
            seed_run=seed, model_label=obj._meta.label, object_pk=str(obj.pk)
        )
        return obj

    clients = []
    for index, (first, last, company) in enumerate(CLIENT_TEMPLATES, 1):
        client = Client(
            business=business,
            first_name=first,
            last_name=last,
            # The existing Client model requires a company_name, including individuals.
            company_name=f"[DEMO] {company}" if index <= 8 else f"[DEMO] {first} {last}",
            client_type=Client.ClientType.BUSINESS if index <= 8 else Client.ClientType.INDIVIDUAL,
            email=f"logistics.demo.{business.pk}.{index}@example.test",
            phone=f"+1 721 555 {100 + index:04d}",
            street_address=f"{10 + index} Demo Front Street",
            district=Client.DistrictChoices.PHILIPSBURG,
            country="Sint Maarten",
            notes="[DEMO] Fictional Logistics client for manual testing.",
        )
        client.full_clean()
        client.save()
        clients.append(own(client))
    parcels = [
        own(
            register_parcel(
                business=business,
                client=clients[0 if index == 11 else index % len(clients)],
                actor=actor,
                **parcel_demo_fields(
                    index=index,
                    client=clients[0 if index == 11 else index % len(clients)],
                    route=ROUTES[
                        (
                            ASSIGNED_PARCEL_ROUTE_INDEXES[index]
                            if index < len(ASSIGNED_PARCEL_ROUTE_INDEXES)
                            else index % len(ROUTES)
                        )
                    ],
                    today=today,
                ),
            )
        )
        for index in range(LOGISTICS_DEMO_COUNTS["parcels"])
    ]
    shipments = [
        own(
            create_shipment(
                business=business,
                actor=actor,
                origin=ROUTES[SHIPMENT_ROUTE_INDEXES[index]][0],
                destination=ROUTES[SHIPMENT_ROUTE_INDEXES[index]][1],
                departure_at=now + timedelta(days=(-8, -1, -4, 2, 4, 7)[index]),
                estimated_arrival_at=now + timedelta(days=(-3, 3, -1, 5, 4, 12)[index]),
                notes=f"[DEMO] Shipment {index + 1:02d}; fictional cargo for UI testing.",
            )
        )
        for index in range(LOGISTICS_DEMO_COUNTS["shipments"])
    ]

    def status(parcel, value):
        change_parcel_status(
            business=business,
            parcel=parcel,
            actor=actor,
            status=value,
            public_message=f"Parcel {Parcel.Status(value).label.lower()}.",
            location=parcel.origin if value == Parcel.Status.RECEIVED else parcel.destination,
        )

    # Services generate bulk parcel history as shipments depart and arrive.
    for shipment, members, target in (
        (shipments[0], parcels[:3], Shipment.Status.COMPLETED),
        (shipments[1], parcels[3:6], Shipment.Status.IN_TRANSIT),
        (shipments[2], parcels[6:8], Shipment.Status.ARRIVED),
        (shipments[3], parcels[8:10], Shipment.Status.READY),
    ):
        for parcel in members:
            status(parcel, Parcel.Status.RECEIVED)
            assign_parcel(business=business, shipment=shipment, parcel=parcel, actor=actor)
        for value in (Shipment.Status.READY, Shipment.Status.IN_TRANSIT, Shipment.Status.ARRIVED):
            change_shipment_status(business=business, shipment=shipment, actor=actor, status=value)
            if value == target:
                break
        if target == Shipment.Status.COMPLETED:
            for parcel in members:
                status(parcel, Parcel.Status.READY)
                status(parcel, Parcel.Status.DELIVERED)
            change_shipment_status(
                business=business, shipment=shipment, actor=actor, status=Shipment.Status.COMPLETED
            )
    status(parcels[10], Parcel.Status.RECEIVED)
    for parcel in parcels[10:12]:
        assign_parcel(business=business, shipment=shipments[4], parcel=parcel, actor=actor)
    change_shipment_status(
        business=business, shipment=shipments[5], actor=actor, status=Shipment.Status.CANCELLED
    )
    status(parcels[13], Parcel.Status.RECEIVED)
    for value in (
        Parcel.Status.RECEIVED,
        Parcel.Status.IN_TRANSIT,
        Parcel.Status.ARRIVED,
        Parcel.Status.READY,
    ):
        status(parcels[14], value)
    status(parcels[15], Parcel.Status.HOLD)
    status(parcels[16], Parcel.Status.RECEIVED)
    status(parcels[16], Parcel.Status.HOLD)
    status(parcels[17], Parcel.Status.CANCELLED)
    status(parcels[18], Parcel.Status.RECEIVED)
    status(parcels[18], Parcel.Status.CANCELLED)

    for parcel in parcels:
        parcel.refresh_from_db()
        location = parcel.origin
        if parcel.current_status == Parcel.Status.IN_TRANSIT:
            location = "En route to " + parcel.destination
        elif parcel.current_status in {
            Parcel.Status.ARRIVED,
            Parcel.Status.READY,
            Parcel.Status.DELIVERED,
        }:
            location = parcel.destination
        record_parcel_event(
            business=business,
            parcel=parcel,
            actor=actor,
            location="" if parcel == parcels[19] else location,
            public_message=(
                ""
                if parcel.current_status in {Parcel.Status.HOLD, Parcel.Status.CANCELLED}
                else "Demo location checkpoint recorded."
            ),
            internal_note=(
                "[DEMO] Awaiting label details."
                if parcel == parcels[19]
                else "[DEMO] Packaging and routing checkpoint."
            ),
        )
    for index, note in (
        (0, "[DEMO] Delivery receipt checked."),
        (16, "[DEMO] Hold for packaging inspection; contact the client."),
    ):
        edit_parcel(business=business, parcel=parcels[index], actor=actor, internal_notes=note)
    events = ParcelEvent.objects.filter(business=business, parcel__in=parcels).order_by("pk")
    for event in events:
        own(event)
    # Shared Services and Invoice models; no booking setup or payment side effects.
    import uuid

    services = [
        own(
            BusinessService.objects.create(
                business=business,
                name=f"[DEMO] {name}",
                unit_price=Decimal(price),
                description=f"[DEMO] {name}",
                tax_rate=business.tax_rate,
            )
        )
        for name, price in (
            ("Small Parcel Delivery", "15"),
            ("Medium Parcel Delivery", "25"),
            ("Large Parcel Delivery", "40"),
            ("Standard Handling", "5"),
            ("Fragile Handling", "12"),
            ("Storage", "8"),
            ("Freight", "150"),
            ("Customs Processing", "35"),
        )
    ]
    charges = []
    for parcel, service, price, description in (
        (parcels[0], services[1], None, ""),
        (parcels[0], services[4], None, ""),
        (parcels[10], services[0], None, ""),  # Same client, another parcel.
        (parcels[1], services[2], Decimal("35"), "Negotiated delivery"),
        (parcels[2], None, Decimal("37.50"), "Special oversized handling"),
        (parcels[3], services[1], None, ""),
        (parcels[3], services[4], None, ""),
        (parcels[3], services[5], None, ""),
    ):
        charges.append(
            own(
                add_charge(
                    business=business,
                    actor=actor,
                    parcel=parcel,
                    service=service,
                    unit_price=price,
                    description=description,
                    idempotency_key=uuid.uuid4(),
                )
            )
        )
    # A dedicated, single-client shipment shows shipment-level billing safely.
    billing_shipment = shipments[4]
    shipment_charge = own(
        add_charge(
            business=business,
            actor=actor,
            shipment=billing_shipment,
            service=services[6],
            idempotency_key=uuid.uuid4(),
        )
    )
    for group in (charges[:3], [charges[3]], [shipment_charge]):
        invoice = own(
            invoice_charges(
                business=business, actor=actor, charge_ids=[charge.pk for charge in group]
            )
        )
        for line in invoice.lines.all():
            own(line)
        for activity in ActivityLog.objects.filter(
            business=business, payload__invoice_number=invoice.invoice_number
        ):
            own(activity)
    return seed


def plan_logistics_demo_reset(*, business, seed_run, lock=False):
    require_logistics_business(business)
    return build_demo_seed_reset_plan(
        business=business, seed_run=seed_run, lock=lock, model_order=LOGISTICS_RESET_ORDER
    )


@transaction.atomic
def reset_logistics_demo(*, business_id):
    business = Business.objects.select_for_update().get(pk=business_id)
    seed = DemoSeedRun.objects.select_for_update().filter(business=business).first()
    plan = plan_logistics_demo_reset(business=business, seed_run=seed, lock=True)
    if seed is None:
        return None
    return execute_demo_seed_reset(seed_run=seed, plan=plan, model_order=LOGISTICS_RESET_ORDER)
