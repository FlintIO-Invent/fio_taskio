"""Varied, attributable Logistics demo data created through operational services."""

from collections import Counter
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
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
from .location_access import assignments_for, has_wide_access
from .location_access_services import select_work_location
from .location_operations import operation_location, operations_enabled
from .location_reference import country_choices
from .models import (
    LogisticsCharge,
    LogisticsLocation,
    LogisticsProfile,
    Parcel,
    ParcelEvent,
    Shipment,
)
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
from .shipment_transport import configured_shipment_modes

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
    "clients": 6,
    "parcels": 20,
    "parcel_events": 83,
    "shipments": 6,
    "services": 0,
    "logistics_charges": 16,
    "invoices": 4,
    "invoice_lines": 13,
    "activity_logs": 4,
}
PARCEL_STATUS_COUNTS = {
    "REGISTERED": 3,
    "RECEIVED": 4,
    "HOLD": 2,
    "IN_TRANSIT": 3,
    "ARRIVED": 2,
    "READY": 1,
    "DELIVERED": 3,
    "CANCELLED": 2,
}
SHIPMENT_STATUS_COUNTS = {status: 1 for status in Shipment.Status.values}

CLIENT_TEMPLATES = (
    ("Avery", "Morgan", "Coral Bay Books"),
    ("Jordan", "Ellis", "Harbor Cafe"),
    ("Casey", "Bennett", "Island Supplies"),
    ("Riley", "Foster", "Sunrise Guest House"),
    ("Morgan", "Reed", "Blue Horizon Design"),
    ("Taylor", "Hayes", "Seabreeze Market"),
)
# Completed supplies (C), active books (A), arrived displays (E), upcoming cafe
# supplies (F), packaging holds (B), and local guest-house delivery (D).
PARCEL_CLIENT_INDEXES = (2, 2, 2, 0, 0, 0, 4, 4, 5, 5, 4, 4, 0, 5, 3, 1, 1, 5, 5, 3)
CLIENT_CONTENTS = (
    ("Books and stationery", "490199"),
    ("Cafe supplies and reusable cups", "392410"),
    ("Cotton clothing and shop supplies", "610910"),
    ("Ceramic tableware", "691200"),
    ("Printed display materials", "491110"),
    ("Compostable food containers", "482369"),
)

# A shipment's route also supplies the route and transport metadata of its members.
ROUTES = (
    ("Miami consolidation depot", "Philipsburg collection depot", "Sea", "USMIA", "SXPHI"),
    (
        "Philipsburg consolidation depot",
        "Blowing Point, Anguilla collection depot",
        "Sea",
        "SXPHI",
        "AIBLP",
    ),
    ("Philipsburg warehouse", "Cole Bay delivery hub", "Road", "", ""),
    (
        "Roseau, Dominica consolidation depot",
        "Pointe-a-Pitre, Guadeloupe collection depot",
        "Sea",
        "DMRSU",
        "GPPTP",
    ),
    (
        "Philipsburg consolidation depot",
        "Willemstad, Curacao collection depot",
        "Sea",
        "SXPHI",
        "CWWIL",
    ),
)
SHIPMENT_ROUTE_INDEXES = (0, 1, 3, 4, 2, 2)
PARCEL_ROUTE_INDEXES = (0, 0, 0, 1, 1, 1, 3, 3, 4, 4, 2, 2, 1, 2, 2, 0, 0, 4, 4, 2)
ASSIGNED_PARCEL_SHIPMENT_INDEXES = (0, 0, 0, 1, 1, 1, 2, 2, 3, 3, 4, 4)


def shipment_demo_references(index, mode):
    if mode == TransportationMode.SEA:
        return {
            "carrier_name": "[DEMO] Coral Channel Cargo",
            "vessel_name": "[DEMO] MV Harbor Fiction",
            "voyage_reference": f"DEMO-VOY-{index + 1:03d}",
            "container_reference": f"DEMO-CONT-{index + 1:03d}",
            "bill_of_lading_reference": f"DEMO-BOL-{index + 1:03d}",
        }
    if mode == TransportationMode.ROAD:
        return {
            "carrier_name": "[DEMO] Island Dispatch",
            "vehicle_reference": f"DEMO-TRUCK-{index + 1:03d}",
            "driver_name": "[DEMO] Alex Example",
            "dispatch_reference": f"DEMO-DISPATCH-{index + 1:03d}",
        }
    return {"carrier_name": "[DEMO] Example Cargo Carrier"}


def parcel_demo_fields(*, index, client, route, today):
    """Predictable metadata, including one minimal parcel and optional-field gaps."""
    origin, destination, mode, loading_port, discharge_port = route
    description, hs_code = CLIENT_CONTENTS[PARCEL_CLIENT_INDEXES[index]]
    voyage = (
        ASSIGNED_PARCEL_SHIPMENT_INDEXES[index] + 1
        if index < len(ASSIGNED_PARCEL_SHIPMENT_INDEXES)
        else index + 1
    )
    fields = {
        "origin": origin,
        "destination": destination,
        "package_description": description,
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
        hs_code=hs_code,
        marks_numbers=f"DEMO-BOX-{index + 1:03d}" if index % 3 != 2 else "",
        sender_name=f"Demo {'Mainland Supply' if origin.startswith('Miami') else 'Island Distribution'}",
        sender_contact="dispatch@example.test" if index % 4 != 1 else "",
        sender_address=f"{100 + index} Demo Cargo Road, {origin.split()[0]}",
        sender_country_code=(
            "US" if origin.startswith("Miami") else "DM" if origin.startswith("Roseau") else "SX"
        ),
        sender_tax_id=f"DEMO-TAX-{index + 1:03d}" if mode == "Sea" else "",
        recipient_name=f"{client.first_name} {client.last_name}",
        recipient_contact=client.email if index % 2 == 0 else client.phone,
        recipient_address=f"{client.company_name}, {destination}" if index % 4 != 1 else "",
        mode_of_transport=mode,
        vessel_name="Demo Coral Voyager" if mode == "Sea" else "",
        voyage_no=f"DEMO-VOY-{voyage:02d}" if mode == "Sea" else "",
        imo_no="9074729" if mode == "Sea" else "",
        port_load_unlocode=loading_port,
        port_discharge_unlocode=discharge_port,
        master_bl_no=f"DEMO-MBL-{voyage:03d}" if mode == "Sea" else "",
        house_bl_no=f"DEMO-HBL-{index + 1:03d}" if mode == "Sea" else "",
        issue_date=today - timedelta(days=2 + index % 8) if mode == "Sea" else None,
        incoterms=("DAP", "CIF", "EXW")[index % 3],
        fragile_goods=PARCEL_CLIENT_INDEXES[index] == 3,
        biodegradable_goods=PARCEL_CLIENT_INDEXES[index] == 5,
        expiry_date=(
            today + timedelta(days=30 + index) if PARCEL_CLIENT_INDEXES[index] == 5 else None
        ),
        internal_notes="[DEMO] Keep dry; check packaging before release." if index % 3 == 0 else "",
    )
    return fields


def require_logistics_business(business):
    if business.vertical != Business.Vertical.LOGISTICS:
        raise ValidationError("Logistics demo tooling requires an existing LOGISTICS Business.")


def logistics_demo_profile_plan(business):
    """Plan compatible examples without creating or changing operational settings."""
    profile = LogisticsProfile.objects.filter(business=business).first()
    if profile and OperatingArea.TRANSPORTATION not in profile.operating_areas:
        raise ValidationError(
            "The current demo requires Transportation. The existing explicit "
            "LogisticsProfile was preserved; no operating areas or modes were changed."
        )
    modes = configured_shipment_modes(business)
    # Unknown modes retain the existing mixed examples. Shipment services allow
    # these legacy writes when no recognized mode is configured; the profile stays
    # unknown rather than treating demo content as operational configuration.
    if not modes or set(modes) == {TransportationMode.SEA, TransportationMode.ROAD}:
        shipment_modes = [ROUTES[index][2].upper() for index in SHIPMENT_ROUTE_INDEXES]
    else:
        shipment_modes = [
            modes[index % len(modes)] for index in range(LOGISTICS_DEMO_COUNTS["shipments"])
        ]
    return {
        "create_count": 0,
        "action": "keep" if profile else "leave_missing",
        "operating_areas": profile.operating_areas if profile else [],
        "transportation_modes": profile.transportation_modes if profile else [],
        "strategy": "configured_modes" if modes else "legacy_mixed_unknown_modes",
        "shipment_modes": shipment_modes,
        "shipment_mode_counts": dict(Counter(shipment_modes)),
    }


def logistics_demo_routes(profile_plan):
    shipment_modes = profile_plan["shipment_modes"]
    if shipment_modes == [ROUTES[index][2].upper() for index in SHIPMENT_ROUTE_INDEXES]:
        return (
            [ROUTES[index] for index in SHIPMENT_ROUTE_INDEXES],
            [ROUTES[index] for index in PARCEL_ROUTE_INDEXES],
        )
    sea_routes = [route for route in ROUTES if route[2] == "Sea"]
    generic_routes = {
        TransportationMode.AIR: (ROUTES[0][0], ROUTES[0][1], "Air", "", ""),
        TransportationMode.RAIL: (
            "Miami consolidation depot",
            "Orlando collection depot",
            "Rail",
            "",
            "",
        ),
        TransportationMode.ROAD: ROUTES[2],
    }
    shipment_routes = [
        (
            sea_routes[index % len(sea_routes)]
            if mode == TransportationMode.SEA
            else generic_routes[mode]
        )
        for index, mode in enumerate(shipment_modes)
    ]
    # Assigned parcel metadata follows its shipment, including mode and Sea fields.
    parcel_routes = [
        (
            shipment_routes[ASSIGNED_PARCEL_SHIPMENT_INDEXES[index]]
            if index < len(ASSIGNED_PARCEL_SHIPMENT_INDEXES)
            else shipment_routes[index % len(shipment_routes)]
        )
        for index in range(LOGISTICS_DEMO_COUNTS["parcels"])
    ]
    return shipment_routes, parcel_routes


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


def logistics_demo_location_plan(
    *, business, actor, origin_location_id=None, destination_location_id=None
):
    """Read-only, explicit facility selection; never infer or create company sites."""
    if (
        not operations_enabled(business)
        and origin_location_id is None
        and destination_location_id is None
    ):
        return None
    if not origin_location_id or not destination_location_id:
        raise ValidationError(
            "Verified demo seeding requires explicit --origin-location-id and "
            "--destination-location-id for registered operating facilities."
        )
    sites = []
    for value in (origin_location_id, destination_location_id):
        site = LogisticsLocation.objects.filter(business=business, pk=value, is_active=True).first()
        if site is None:
            raise ValidationError("Select active demo facilities owned by this workspace.")
        if (
            not has_wide_access(business, actor)
            and not assignments_for(business, actor)
            .filter(location=site, can_operate=True)
            .exists()
        ):
            raise PermissionDenied("Demo operations require permission to operate at both sites.")
        sites.append(site)
    if operations_enabled(business) and operation_location(business, actor).pk != sites[0].pk:
        raise ValidationError("Select the demo origin as your current work location first.")
    return {
        side: {
            "id": site.pk,
            "code": site.code,
            "name": site.name,
            "country_code": site.country_code,
        }
        for side, site in zip(("origin", "destination"), sites, strict=True)
    }


@transaction.atomic
def seed_logistics_demo(
    *, business_id, actor_id=None, origin_location_id=None, destination_location_id=None
):
    business = Business.objects.select_for_update().get(pk=business_id)
    require_logistics_business(business)
    if DemoSeedRun.objects.filter(business=business).exists():
        raise ValidationError(
            "Demo ownership metadata already exists; preview/reset it before seeding again."
        )
    actor = demo_actor(business=business, actor_id=actor_id)
    location_plan = logistics_demo_location_plan(
        business=business,
        actor=actor,
        origin_location_id=origin_location_id,
        destination_location_id=destination_location_id,
    )
    route_fields = {}
    if location_plan:
        for side in ("origin", "destination"):
            site = location_plan[side]
            route_fields[f"{side}_location"] = LogisticsLocation.objects.get(pk=site["id"])
            route_fields[f"{side}_country_code"] = site["country_code"]
            route_fields[side] = dict(country_choices())[site["country_code"]]
        select_work_location(business=business, actor=actor, location=origin_location_id)
    profile_plan = logistics_demo_profile_plan(business)
    shipment_routes, parcel_routes = logistics_demo_routes(profile_plan)
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
            company_name=f"[DEMO] {company}",
            client_type=Client.ClientType.BUSINESS,
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
                client=clients[PARCEL_CLIENT_INDEXES[index]],
                actor=actor,
                **{
                    **parcel_demo_fields(
                        index=index,
                        client=clients[PARCEL_CLIENT_INDEXES[index]],
                        route=parcel_routes[index],
                        today=today,
                    ),
                    **route_fields,
                },
            )
        )
        for index in range(LOGISTICS_DEMO_COUNTS["parcels"])
    ]
    shipments = [
        own(
            create_shipment(
                business=business,
                actor=actor,
                **{
                    **{
                        "origin": shipment_routes[index][0],
                        "destination": shipment_routes[index][1],
                    },
                    **route_fields,
                },
                transport_mode=profile_plan["shipment_modes"][index],
                departure_at=now + timedelta(days=(-8, -1, -4, 2, 4, 7)[index]),
                estimated_arrival_at=now + timedelta(days=(-3, 3, -1, 5, 4, 12)[index]),
                notes=f"[DEMO] Shipment {index + 1:02d}; fictional cargo for UI testing.",
                **shipment_demo_references(index, profile_plan["shipment_modes"][index]),
            )
        )
        for index in range(LOGISTICS_DEMO_COUNTS["shipments"])
    ]

    def status(parcel, value):
        if location_plan:
            select_work_location(
                business=business,
                actor=actor,
                location=(
                    destination_location_id
                    if value in {"ARRIVED", "READY", "DELIVERED"}
                    else origin_location_id
                ),
            )
        messages = {
            Parcel.Status.RECEIVED: "Received and weighed at the origin depot.",
            Parcel.Status.IN_TRANSIT: "Dispatched from the origin depot to the destination hub.",
            Parcel.Status.ARRIVED: "Unloaded and checked at the destination hub.",
            Parcel.Status.READY: "Ready for collection or onward local delivery.",
            Parcel.Status.DELIVERED: "Delivered to the recipient; collection confirmed.",
            Parcel.Status.HOLD: "Processing paused; please contact the depot for an update.",
            Parcel.Status.CANCELLED: "Cancelled before dispatch at the client's request.",
        }
        change_parcel_status(
            business=business,
            parcel=parcel,
            actor=actor,
            status=value,
            public_message=messages[value],
            location=(
                parcel.origin
                if value in {Parcel.Status.RECEIVED, Parcel.Status.HOLD, Parcel.Status.CANCELLED}
                else (
                    "En route to " + parcel.destination
                    if value == Parcel.Status.IN_TRANSIT
                    else parcel.destination
                )
            ),
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
            if location_plan:
                select_work_location(
                    business=business,
                    actor=actor,
                    location=(
                        destination_location_id
                        if value == Shipment.Status.ARRIVED
                        else origin_location_id
                    ),
                )
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
        if location_plan:
            select_work_location(
                business=business,
                actor=actor,
                location=(
                    destination_location_id
                    if parcel.current_status in {"ARRIVED", "READY", "DELIVERED"}
                    else origin_location_id
                ),
            )
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
                else (
                    "Booking registered; awaiting receipt at the origin depot."
                    if parcel.current_status == Parcel.Status.REGISTERED
                    else f"Cargo checkpoint confirmed at {location}."
                )
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
    # Demo charge snapshots need no SERVICE catalogue or appointment objects.
    rates = (
        ("Small Parcel Delivery", "15"),
        ("Medium Parcel Delivery", "25"),
        ("Large Parcel Delivery", "40"),
        ("Standard Handling", "5"),
        ("Fragile Handling", "12"),
        ("Storage", "8"),
        ("Freight", "150"),
        ("Customs Processing", "35"),
    )

    def charge(target, rate_index, *, quantity=1, price=None, description=""):
        if rate_index is not None:
            name, standard_price = rates[rate_index]
            description = description or f"[DEMO] {name}"
            if price is None:
                price = Decimal(standard_price)
        return own(
            add_charge(
                business=business,
                actor=actor,
                **({"parcel": target} if isinstance(target, Parcel) else {"shipment": target}),
                quantity=Decimal(quantity),
                unit_price=price,
                description=description,
                idempotency_key=uuid4(),
            )
        )

    # Each shipment billed here has one client. Mixed-client shipment billing is
    # deliberately not bypassed. Paid/Sent are fictional local invoice snapshots;
    # no email, payment, Stripe or subscription action is performed.
    invoice_scenarios = (
        (
            Invoice.Status.SENT,
            f"A: Books moving from {shipments[1].origin} to {shipments[1].destination}",
            [
                charge(shipments[1], 6),
                charge(parcels[3], 3, quantity=2),
                charge(parcels[4], 7),
            ],
        ),
        (
            Invoice.Status.PAID,
            f"C: Shop supplies delivered from {shipments[0].origin} to {shipments[0].destination}",
            [
                charge(shipments[0], 6),
                charge(parcels[0], 2, price=Decimal("35.00"), description="Negotiated delivery"),
                charge(parcels[1], 3),
                charge(
                    parcels[2], None, price=Decimal("37.50"), description="Oversized cargo handling"
                ),
            ],
        ),
        (
            Invoice.Status.SENT,
            "D: Tableware ready, awaiting onward local delivery",
            [
                charge(parcels[14], 0),
                charge(parcels[14], 4),
                charge(parcels[14], 5, quantity=2),
            ],
        ),
        (
            Invoice.Status.DRAFT,
            "E: Display materials booked for "
            f"{TransportationMode(shipments[4].transport_mode).label.lower()} dispatch",
            [
                charge(shipments[4], 6),
                charge(parcels[10], 7),
                charge(parcels[11], 3),
            ],
        ),
    )
    for state, story, group in invoice_scenarios:
        invoice = own(
            invoice_charges(
                business=business, actor=actor, charge_ids=[charge.pk for charge in group]
            )
        )
        invoice.status = state
        invoice.notes = (
            f"[DEMO] {story}. Simulated {state.lower()} status; no email or payment processed."
        )
        invoice.save(update_fields=["status", "notes", "updated_at"])
        for line in invoice.lines.all():
            own(line)
        for activity in ActivityLog.objects.filter(
            business=business,
            client=invoice.client,
            payload__invoice_number=invoice.invoice_number,
        ):
            own(activity)
    # Unbilled estimates demonstrate the existing charge-to-invoice workflow too.
    charge(parcels[16], 5, quantity=3)
    charge(parcels[16], 3)
    charge(parcels[8], 1)
    if location_plan:
        select_work_location(business=business, actor=actor, location=origin_location_id)
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
