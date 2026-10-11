"""Connected lab cargo through domain services, with conservative owned-only reset."""

import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from django.apps import apps
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.billings.models import Invoice, InvoiceLine
from apps.businesses.demo_seed_reset import _validate_tenant_ownership
from apps.businesses.models import DemoSeedRecord
from apps.crm.models import ActivityLog, Client

from .billing_services import add_charge, invoice_charges, require_billing_access
from .demo import shipment_demo_references
from .location_access_services import select_work_location, set_handling_site
from .models import (
    LogisticsCharge,
    LogisticsHandlingSite,
    LogisticsLocationAssignment,
    Parcel,
    ParcelEvent,
    Shipment,
)
from .parcel_services import change_parcel_status, record_parcel_event, register_parcel
from .shipment_services import (
    assign_parcel,
    change_shipment_status,
    create_shipment,
    generate_manifest,
)
from .shipment_transport import configured_shipment_modes
from .test_lab import (
    ACCOUNTS,
    DOMAIN,
    LOCATIONS,
    OWNED_MODELS,
    audit_operation,
    authorize,
    lab_for,
    own,
    owned_objects,
    require_entitlement,
)
from .test_lab_scenarios import (
    CANCELLATIONS,
    CLIENTS,
    CONTENTS,
    EXPECTED_COUNTS,
    MULTILEG,
    SHIPMENTS,
    SITE_WORKERS,
    VERSION,
)

RESET_ORDER = (
    LogisticsCharge,
    InvoiceLine,
    Invoice,
    ActivityLog,
    LogisticsHandlingSite,
    ParcelEvent,
    Parcel,
    Shipment,
    Client,
)
MODELS = {model._meta.label: model for model in RESET_ORDER}
COUNT_NAMES = dict(
    zip(
        RESET_ORDER,
        (
            "logistics_charges",
            "invoice_lines",
            "invoices",
            "activity_logs",
            "handling_sites",
            "parcel_events",
            "parcels",
            "shipments",
            "clients",
        ),
        strict=True,
    )
)


def digest(obj):
    """Refuse to erase fixture records subsequently edited by an operator."""
    data = {field.attname: getattr(obj, field.attname) for field in obj._meta.concrete_fields}
    return hashlib.sha256(
        json.dumps(data, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def dataset_objects(business, seed, *, lock=False, verify=False):
    metadata = seed.planned_counts.get("dataset")
    if not isinstance(metadata, dict) or metadata.get("version") != VERSION:
        raise CommandError("Dataset ownership/version is missing or unsupported.")
    entries = metadata.get("records")
    if not isinstance(entries, dict) or not entries:
        raise CommandError("Dataset record manifest is missing.")
    objects = {model: [] for model in RESET_ORDER}
    seen = set()
    targets = {model: {} for model in RESET_ORDER}
    for key, entry in entries.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise CommandError("Invalid stable fixture identifier.")
        model = MODELS.get(entry.get("model"))
        pk = entry.get("pk")
        if model is None or not isinstance(pk, int) or pk <= 0 or (model, pk) in seen:
            raise CommandError("Invalid or duplicate dataset ownership target.")
        seen.add((model, pk))
        targets[model][pk] = (key, entry)
    for model, requested in targets.items():
        qs = model.objects.filter(pk__in=requested).order_by("pk")
        if lock:
            qs = qs.select_for_update()
        items = list(qs)
        if len(items) != len(requested):
            raise CommandError("Missing owned fixture; manual review required.")
        for obj in items:
            key, entry = requested[obj.pk]
            if verify and digest(obj) != entry.get("digest"):
                raise CommandError(f"Fixture changed: {key}; refusing destructive reset.")
        objects[model] = items
    tracked = {
        (MODELS[record.model_label], int(record.object_pk))
        for record in seed.owned_records.filter(model_label__in=MODELS)
        if record.object_pk.isdecimal()
    }
    if tracked != seen:
        raise CommandError("Dataset manifest and seed ownership records do not match.")
    # Populate the related-object cache from this locked ownership graph, avoiding
    # hundreds of per-event reads while retaining the existing tenant validator.
    by_model = {model: {obj.pk: obj for obj in items} for model, items in objects.items()}
    for items in objects.values():
        for obj in items:
            for field in obj._meta.fields:
                if field.is_relation and field.related_model in by_model:
                    related = by_model[field.related_model].get(getattr(obj, field.attname))
                    if related is not None:
                        field.set_cached_value(obj, related)
    _validate_tenant_ownership(
        business=business,
        objects_by_label={model._meta.label: tuple(items) for model, items in objects.items()},
    )
    foundation = {
        model: set(
            map(
                int,
                seed.owned_records.filter(model_label=model._meta.label).values_list(
                    "object_pk", flat=True
                ),
            )
        )
        for model in OWNED_MODELS
    }
    allowed = {
        **foundation,
        **{model: {obj.pk for obj in items} for model, items in objects.items()},
    }
    for items in objects.values():
        for obj in items:
            for field in obj._meta.fields:
                if field.is_relation and field.related_model:
                    value = getattr(obj, field.attname)
                    if value is not None and value not in allowed.get(field.related_model, set()):
                        raise CommandError("Owned dataset references an unowned related record.")
    return objects


def reset_plan(business, seed, *, lock=False):
    objects = dataset_objects(business, seed, lock=lock, verify=True)
    owned = {model: {obj.pk for obj in items} for model, items in objects.items()}
    # Include every incoming FK, even SET_NULL and unfamiliar future app models.
    for model in apps.get_models():
        conditions = Q()
        for field in model._meta.fields:
            if field.is_relation and field.related_model in owned:
                conditions |= Q(**{field.attname + "__in": owned[field.related_model]})
        if (
            conditions
            and model.objects.filter(conditions).exclude(pk__in=owned.get(model, set())).exists()
        ):
            raise CommandError(f"Unowned {model._meta.label} depends on dataset; reset refused.")
    for model, pks in owned.items():
        if (
            DemoSeedRecord.objects.exclude(seed_run=seed)
            .filter(model_label=model._meta.label, object_pk__in=list(map(str, pks)))
            .exists()
        ):
            raise CommandError("Another seed claims dataset records.")
    for invoice in objects[Invoice]:
        if (
            invoice.status != Invoice.Status.DRAFT
            or invoice.emailed_at
            or invoice.emailed_to
            or invoice.email_send_count
        ):
            raise CommandError(
                "Financial retention: only unchanged, undispatched fixture drafts can reset."
            )
    return objects


def context(business, seed, *, environment, lock=False):
    if business is None or business.pk == 133:
        raise CommandError("Only the owned lab is permitted; business 133 is always excluded.")
    if seed.planned_counts.get("phase") != "ready" or not business.is_active:
        raise CommandError("Complete Block 06A lab provisioning first.")
    # Cargo setup/reset preserves the foundation. Normal login/billing metadata
    # and unrelated lab records need not be fixture-owned; reset_plan separately
    # rejects every unowned dependency of the cargo it would actually delete.
    owned_objects(business, seed, lock=lock, check_dependents=False)
    require_entitlement(business.subscription, environment)
    members = {m.user.email.split("@")[0]: m for m in business.memberships.select_related("user")}
    if set(members) != {name for name, _, _ in ACCOUNTS}:
        raise CommandError("Exactly the nine standardized existing memberships are required.")
    for name, role, codes in ACCOUNTS:
        member = members[name]
        if (
            member.role != role
            or not member.is_active
            or not member.user.is_active
            or member.user.email != f"{name}@{DOMAIN}"
        ):
            raise CommandError(
                "Lab account role/identity changed; no permissions will be modified."
            )
        grants = member.logistics_location_assignments.filter(
            can_operate=True, is_work_context=False
        )
        if set(grants.values_list("location__code", flat=True)) != set(codes):
            raise CommandError("Lab worker grants changed; no permissions will be modified.")
    sites = {site.code: site for site in business.logistics_locations.all()}
    if set(sites) != {site["code"] for site in LOCATIONS}:
        raise CommandError("The four standardized operating sites are required.")
    for template in LOCATIONS:
        site = sites[template["code"]]
        if not site.is_active or any(
            getattr(site, key) != value for key, value in template.items()
        ):
            raise CommandError(
                "Standardized site configuration changed; no sites will be overwritten."
            )
    profile = business.logistics_profile
    if not profile.location_operations_enabled_at or not profile.location_access_reviewed_at:
        raise CommandError("Reviewed, enabled location operations are required.")
    modes = configured_shipment_modes(business)
    if not {"SEA", "ROAD"}.issubset(modes):
        raise CommandError(
            "These scenarios require configured SEA and ROAD; the profile will not be changed."
        )
    users = {name: member.user for name, member in members.items()}
    require_billing_access(business=business, actor=users["owner"], write=True)
    return users, sites, modes


def plan_dataset(*, environment, business_id, reset=False):
    authorize(environment)
    business, seed = lab_for(environment, business_id)
    _, _, modes = context(business, seed, environment=environment)
    if reset:
        counts = {
            COUNT_NAMES[model]: len(items) for model, items in reset_plan(business, seed).items()
        }
    else:
        if seed.planned_counts.get("dataset"):
            raise CommandError(
                "Dataset already exists. Inspect it or preview guarded reset before reseeding."
            )
        counts = EXPECTED_COUNTS
    return {
        "version": VERSION,
        "business_id": business.pk,
        "counts": counts,
        "air_supported": "AIR" in modes,
        "air_fallback": None if "AIR" in modes else "SEA (same Miami to SXM routes)",
        "scenarios": [story[0] for story in SHIPMENTS]
        + [key for key, _ in MULTILEG]
        + list(CANCELLATIONS),
        "financial_confirmation_required": reset,
    }


def inspect_dataset(*, environment, business_id):
    authorize(environment)
    business, seed = lab_for(environment, business_id)
    if business is None or business.pk == 133:
        raise CommandError("Only the owned lab may be inspected.")
    if not seed.planned_counts.get("dataset"):
        return {"version": VERSION, "business_id": business_id, "dataset": None}
    objects = dataset_objects(business, seed)
    return {
        "version": VERSION,
        "business_id": business_id,
        "counts": {COUNT_NAMES[model]: len(items) for model, items in objects.items()},
        "parcel_states": dict(Counter(obj.current_status for obj in objects[Parcel])),
        "shipment_states": dict(Counter(obj.status for obj in objects[Shipment])),
        "transport_modes": dict(Counter(obj.transport_mode for obj in objects[Shipment])),
        "event_actors": dict(
            Counter(getattr(obj.actor, "email", "[unavailable]") for obj in objects[ParcelEvent])
        ),
        "event_locations": dict(
            Counter(
                getattr(obj.operational_location, "code", "[unavailable]")
                for obj in objects[ParcelEvent]
            )
        ),
        "records": seed.planned_counts["dataset"]["records"],
    }


@contextmanager
def work_at(business, actor, site):
    """Use normal context selection, then restore every existing assignment exactly."""
    member = business.memberships.get(user=actor)
    assignments = LogisticsLocationAssignment.objects.filter(membership=member)
    original = list(assignments.values("pk", "is_current", "can_operate", "is_work_context"))
    select_work_location(business=business, actor=actor, location=site)
    try:
        yield
    finally:
        assignments.exclude(pk__in=[row["pk"] for row in original]).delete()
        assignments.update(is_current=False)
        for row in original:
            pk = row.pop("pk")
            assignments.filter(pk=pk).update(**row)


def _seed(business, seed, users, sites, modes):
    records = {}

    def remember(key, obj):
        own(seed, obj)
        records[key] = {"model": obj._meta.label, "pk": obj.pk}
        return obj

    clients = []
    for index, (key, first, last, company) in enumerate(CLIENTS):
        client = Client(
            business=business,
            first_name=first,
            last_name=last,
            company_name=f"[LAB] {company}",
            client_type=Client.ClientType.BUSINESS,
            email=f"{key}@customers.globalcargo.motionmate.test",
            phone=f"+1 721 555 {100 + index:04d}",
            street_address=f"{20 + index} Fictional Front Street",
            district=Client.DistrictChoices.PHILIPSBURG,
            country="Sint Maarten",
            notes=f"[LAB] Fictional bill-to customer; fixture {key}.",
        )
        client.full_clean()
        client.save()
        clients.append(remember(f"client/{key}", client))
    owner = users["owner"]
    now = timezone.now()
    all_parcels = []
    billed = []

    def route(source, destination):
        return dict(
            origin=source.name,
            destination=destination.name,
            origin_location=source,
            destination_location=destination,
            origin_country_code=source.country_code,
            destination_country_code=destination.country_code,
        )

    def parcel(key, source, destination, mode, client_index, item_index):
        recipient = clients[(client_index + 4) % len(clients)]
        description, hs = CONTENTS[client_index % len(CONTENTS)]
        fields = dict(
            **route(source, destination),
            internal_reference=f"LAB/{key}",
            package_description=description,
            quantity=1 + item_index % 3,
            weight_kg=Decimal("1.250") + Decimal(item_index) * Decimal("0.625"),
            length_cm=Decimal("30"),
            width_cm=Decimal("20"),
            height_cm=Decimal("15"),
            volume_m3=Decimal("0.009"),
            declared_value=Decimal("60") + client_index * 15,
            hs_code=hs,
            marks_numbers=f"LAB-BOX-{len(all_parcels) + 1:03d}",
            mode_of_transport={"SEA": "Sea", "AIR": "Air", "ROAD": "Road"}[mode],
            sender_name=(
                "[LAB] Mainland Supply"
                if source.country_code == "US"
                else "[LAB] Island Distribution"
            ),
            sender_contact="dispatch@suppliers.globalcargo.motionmate.test",
            sender_address_line_1="100 Fictional Cargo Road",
            sender_city=source.city,
            sender_country_code=source.country_code,
            recipient_name=recipient.company_name,
            recipient_contact=recipient.email,
            recipient_address_line_1=recipient.street_address,
            recipient_city=destination.city,
            recipient_country_code=destination.country_code,
            fragile_goods=client_index % 6 == 3,
            internal_notes=f"[LAB] Stable scenario: {key}; fictional cargo, no dispatch notification.",
        )
        with work_at(business, owner, source):
            obj = register_parcel(
                business=business, client=clients[client_index], actor=owner, **fields
            )
        all_parcels.append((key, obj))
        return remember(f"parcel/{key}", obj)

    def event(obj, state, site, worker=None, message=None):
        actor = users[worker or SITE_WORKERS[site.code]]
        with work_at(business, actor, site):
            return change_parcel_status(
                business=business,
                parcel=obj,
                actor=actor,
                status=state,
                location=site.name,
                public_message=message or f"{state.replace('_', ' ').title()} at {site.name}.",
            )

    def checkpoint(obj, site, worker=None):
        actor = users[worker or SITE_WORKERS[site.code]]
        with work_at(business, actor, site):
            record_parcel_event(
                business=business,
                parcel=obj,
                actor=actor,
                location=site.name,
                internal_note="[LAB] Packaging and routing checkpoint verified.",
            )

    for index, (
        key,
        source_code,
        destination_code,
        preferred,
        target,
        count,
        client_index,
    ) in enumerate(SHIPMENTS):
        source, destination = sites[source_code], sites[destination_code]
        mode = preferred if preferred in modes else "SEA"
        departed = target in ("IN_TRANSIT", "ARRIVED", "COMPLETED")
        departure = now + timedelta(days=-3 if departed else 2 + index % 3)
        arrival = now + timedelta(days=-1 if target in ("ARRIVED", "COMPLETED") else 5 + index % 3)
        with work_at(business, owner, source):
            shipment = remember(
                f"shipment/{key}",
                create_shipment(
                    business=business,
                    actor=owner,
                    **route(source, destination),
                    transport_mode=mode,
                    departure_at=departure,
                    estimated_arrival_at=arrival,
                    notes=f"[LAB] {key}; fictional operational scenario.",
                    **shipment_demo_references(index, mode),
                ),
            )
        members = [
            parcel(f"{key}/{j + 1:02d}", source, destination, mode, client_index, j)
            for j in range(count)
        ]
        for obj in members:
            if target != "DRAFT":
                event(obj, "RECEIVED", source)
            with work_at(business, owner, source):
                assign_parcel(business=business, shipment=shipment, parcel=obj, actor=owner)
        if target == "CANCELLED":
            with work_at(business, users["miami"], source):
                change_shipment_status(
                    business=business, shipment=shipment, actor=users["miami"], status=target
                )
        elif target != "DRAFT":
            for state in ("READY", "IN_TRANSIT", "ARRIVED"):
                site = destination if state == "ARRIVED" else source
                worker = "regional" if key == "miami-sea-moving" else SITE_WORKERS[site.code]
                with work_at(business, users[worker], site):
                    change_shipment_status(
                        business=business, shipment=shipment, actor=users[worker], status=state
                    )
                if state == target:
                    break
            if target == "COMPLETED":
                for obj in members:
                    event(obj, "READY", destination)
                    event(obj, "DELIVERED", destination)
                with work_at(business, users[SITE_WORKERS[destination.code]], destination):
                    change_shipment_status(
                        business=business,
                        shipment=shipment,
                        actor=users[SITE_WORKERS[destination.code]],
                        status="COMPLETED",
                    )
        for obj in members:
            checkpoint(obj, destination if target in ("ARRIVED", "COMPLETED") else source)
        generate_manifest(business=business, shipment=shipment, actor=owner)
        billed.append((key, shipment if target != "CANCELLED" else members[0], members[0], mode))

    for index, (key, target) in enumerate(MULTILEG):
        source, stop, destination = sites["MIA-HUB"], sites["SXM-PORT"], sites["DM-HUB"]
        obj = parcel(key, source, destination, "SEA", 10 + index, index)
        remember(
            f"handling/{key}/expected-sxm",
            set_handling_site(
                business=business, actor=owner, location=stop, parcel=obj, kind="EXPECTED"
            ),
        )
        event(obj, "RECEIVED", source)
        event(obj, "IN_TRANSIT", source)
        event(obj, "ARRIVED", stop, "regional")
        event(obj, "HOLD", stop, message="Transshipment inspection at Sint Maarten Port.")
        event(
            obj,
            "IN_TRANSIT",
            stop,
            "sxm-port",
            "Inspection released; dispatched onward to Dominica.",
        )
        event(obj, "ARRIVED", destination)
        event(obj, "READY", destination)
        if target == "DELIVERED":
            event(obj, "DELIVERED", destination)
        checkpoint(obj, destination)
        billed.append((key, obj, obj, "SEA"))

    for index, key in enumerate(CANCELLATIONS):
        site = sites["MIA-HUB" if index == 0 else "SXM-DC"]
        obj = parcel(key, site, site, "ROAD", index, index)
        event(obj, "CANCELLED", site)
        checkpoint(obj, site)

    for key, target, handling_parcel, mode in billed:
        charges = []
        for kind, item, price, quantity in (
            (
                "freight",
                target,
                Decimal({"SEA": "120", "AIR": "180", "ROAD": "25"}[mode]),
                Decimal("1"),
            ),
            ("handling", handling_parcel, Decimal("5"), Decimal(handling_parcel.quantity)),
        ):
            charges.append(
                remember(
                    f"charge/{key}/{kind}",
                    add_charge(
                        business=business,
                        actor=owner,
                        **({"parcel": item} if isinstance(item, Parcel) else {"shipment": item}),
                        description=f"[LAB] {mode.title()} {kind}",
                        unit_price=price,
                        quantity=quantity,
                        idempotency_key=uuid5(NAMESPACE_URL, f"{VERSION}/{key}/{kind}"),
                    ),
                )
            )
        invoice = remember(
            f"invoice/{key}",
            invoice_charges(
                business=business, actor=owner, charge_ids=[charge.pk for charge in charges]
            ),
        )
        invoice.notes = f"[LAB] {key}. Draft only; no email, payment or invoice dispatch."
        invoice.save(update_fields=["notes", "updated_at"])
        for j, line in enumerate(invoice.lines.order_by("pk"), 1):
            remember(f"invoice-line/{key}/{j}", line)
        activity = ActivityLog.objects.get(
            business=business, payload__invoice_number=invoice.invoice_number
        )
        remember(f"activity/{key}/invoice-created", activity)

    for key, obj in all_parcels:
        for j, evt in enumerate(obj.events.order_by("timestamp", "pk"), 1):
            remember(f"event/{key}/{j:02d}", evt)
    for model in RESET_ORDER:
        entries = {
            entry["pk"]: entry for entry in records.values() if entry["model"] == model._meta.label
        }
        for obj in model.objects.filter(pk__in=entries):
            entries[obj.pk]["digest"] = digest(obj)
    seed.planned_counts["dataset"] = {
        "version": VERSION,
        "records": records,
        "air_supported": "AIR" in modes,
        "expected_counts": EXPECTED_COUNTS,
    }
    seed.save(update_fields=["planned_counts", "updated_at"])
    objects = dataset_objects(business, seed, verify=True)
    actual = {COUNT_NAMES[model]: len(items) for model, items in objects.items()}
    if actual != EXPECTED_COUNTS:
        raise CommandError(f"Domain counts changed; execution rolled back: {actual}")


@transaction.atomic
def execute_dataset(
    *,
    environment,
    business_id,
    confirm_business_id,
    confirm_database,
    confirm_app=None,
    reason_reference=None,
    reset=False,
    confirm_test_financial_data=False,
):
    authorize(environment, execute=True, confirm_database=confirm_database, confirm_app=confirm_app)
    if business_id != confirm_business_id or business_id <= 0 or business_id == 133:
        raise CommandError(
            "Execute requires an exact owned business ID confirmation; 133 is excluded."
        )
    if not reason_reference or not reason_reference.strip() or len(reason_reference) > 120:
        raise CommandError("Execute requires a reason reference of at most 120 characters.")
    business, seed = lab_for(environment, business_id, lock=True)
    users, sites, modes = context(business, seed, environment=environment, lock=True)
    if reset:
        objects = reset_plan(business, seed, lock=True)
        if not confirm_test_financial_data:
            raise CommandError(
                "Dataset draft invoices require --confirm-test-financial-data for reset."
            )
        for model in RESET_ORDER:
            pks = [obj.pk for obj in objects[model]]
            qs = model.objects.filter(pk__in=pks)
            if model in (LogisticsCharge, ParcelEvent, Parcel, Shipment):
                qs._purge_delete()
            else:
                qs.delete()
            seed.owned_records.filter(
                model_label=model._meta.label, object_pk__in=list(map(str, pks))
            ).delete()
        del seed.planned_counts["dataset"]
        seed.save(update_fields=["planned_counts", "updated_at"])
    else:
        if seed.planned_counts.get("dataset"):
            raise CommandError("Dataset already exists; refusing duplicate execution.")
        _seed(business, seed, users, sites, modes)
    audit_operation(
        business.pk, environment, "dataset-reset" if reset else "dataset-seed", reason_reference
    )
    return inspect_dataset(environment=environment, business_id=business.pk)
