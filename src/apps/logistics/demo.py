"""Small, attributable Logistics demo data created through operational services."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.businesses.demo_seed_reset import (
    build_demo_seed_reset_plan,
    execute_demo_seed_reset,
)
from apps.businesses.models import Business, BusinessUser, DemoSeedRecord, DemoSeedRun
from apps.crm.models import Client

from .models import Parcel, ParcelEvent, Shipment
from .parcel_policy import PARCEL_MANAGE_ROLES
from .parcel_services import (
    change_parcel_status,
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

LOGISTICS_RESET_ORDER = (ParcelEvent, Parcel, Shipment, Client)
LOGISTICS_DEMO_COUNTS = {"clients": 3, "parcels": 8, "parcel_events": 26, "shipments": 3}


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
    seed = DemoSeedRun.objects.create(business=business, planned_counts=LOGISTICS_DEMO_COUNTS)

    def own(obj):
        DemoSeedRecord.objects.create(
            seed_run=seed, model_label=obj._meta.label, object_pk=str(obj.pk)
        )
        return obj

    clients = [
        own(
            Client.objects.create(
                business=business,
                first_name=first,
                last_name=last,
                company_name=company,
                client_type=Client.ClientType.BUSINESS,
                email=f"logistics.demo.{business.pk}.{index}@example.test",
                phone="+1 721 555 0100",
                country="Sint Maarten",
            )
        )
        for index, (first, last, company) in enumerate(
            (
                ("Avery", "Morgan", "Demo Coral Bay Books"),
                ("Jordan", "Ellis", "Demo Harbor Cafe"),
                ("Casey", "Bennett", "Demo Island Supplies"),
            ),
            1,
        )
    ]
    parcels = [
        own(
            register_parcel(
                business=business,
                client=clients[index % len(clients)],
                actor=actor,
                origin="Miami consolidation depot",
                destination="Sint Maarten collection depot",
                package_description=("Books", "Cafe supplies", "Clothing")[index % 3],
                internal_reference=f"DEMO-{index + 1:03d}",
                quantity=1,
                weight_kg="2.500",
            )
        )
        for index in range(8)
    ]
    shipments = [
        own(
            create_shipment(
                business=business,
                actor=actor,
                origin="Miami consolidation depot",
                destination="Sint Maarten collection depot",
                notes=f"Demo shipment {index + 1}",
            )
        )
        for index in range(3)
    ]

    def status(parcel, value):
        change_parcel_status(
            business=business,
            parcel=parcel,
            actor=actor,
            status=value,
            public_message=f"Parcel {Parcel.Status(value).label.lower()}.",
        )

    # A complete shipment, one in transit and one draft demonstrate the normal lifecycle.
    for shipment, members, complete in (
        (shipments[0], parcels[:2], True),
        (shipments[1], parcels[2:4], False),
    ):
        for parcel in members:
            status(parcel, Parcel.Status.RECEIVED)
            assign_parcel(business=business, shipment=shipment, parcel=parcel, actor=actor)
        for value in (Shipment.Status.READY, Shipment.Status.IN_TRANSIT):
            change_shipment_status(business=business, shipment=shipment, actor=actor, status=value)
        if complete:
            change_shipment_status(
                business=business, shipment=shipment, actor=actor, status=Shipment.Status.ARRIVED
            )
            for parcel in members:
                status(parcel, Parcel.Status.READY)
                status(parcel, Parcel.Status.DELIVERED)
            change_shipment_status(
                business=business, shipment=shipment, actor=actor, status=Shipment.Status.COMPLETED
            )
    status(parcels[4], Parcel.Status.RECEIVED)
    assign_parcel(business=business, shipment=shipments[2], parcel=parcels[4], actor=actor)
    status(parcels[6], Parcel.Status.HOLD)
    status(parcels[7], Parcel.Status.CANCELLED)
    record_parcel_event(
        business=business,
        parcel=parcels[4],
        actor=actor,
        internal_note="Demo: package checked and awaiting consolidation.",
    )
    events = ParcelEvent.objects.filter(business=business, parcel__in=parcels).order_by("pk")
    for event in events:
        own(event)
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
