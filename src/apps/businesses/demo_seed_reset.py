from __future__ import annotations

from dataclasses import dataclass

from django.db import models

from apps.appointments.models import Appointment
from apps.billings.models import Invoice, InvoiceLine
from apps.crm.models import ActivityLog, BusinessService, Client, Lead, ServiceCategory
from apps.logistics.models import Parcel, ParcelEvent, Shipment

from .models import (
    Business,
    BusinessBookingSettings,
    DemoSeedRecord,
    DemoSeedRun,
    WeeklyAvailability,
)


class DemoSeedResetError(RuntimeError):
    pass


RESET_MODEL_ORDER: tuple[type[models.Model], ...] = (
    InvoiceLine,
    Invoice,
    Appointment,
    Lead,
    Client,
    BusinessService,
    ServiceCategory,
    WeeklyAvailability,
    BusinessBookingSettings,
)
RESET_MODELS_BY_LABEL = {model._meta.label: model for model in RESET_MODEL_ORDER}


@dataclass(frozen=True, slots=True)
class DemoSeedResetPlan:
    business_id: int
    business_slug: str
    seed_run_id: str | None
    object_pks: dict[str, tuple[int, ...]]
    stale_tracking_record_count: int
    tracking_record_count: int

    @property
    def has_seed_run(self) -> bool:
        return self.seed_run_id is not None

    @property
    def counts(self) -> dict[str, int]:
        return {label: len(pks) for label, pks in self.object_pks.items()}


@dataclass(frozen=True, slots=True)
class DemoSeedResetResult:
    deleted_counts: dict[str, int]
    deleted_tracking_records: int
    deleted_seed_run: bool


def build_demo_seed_reset_plan(
    *,
    business: Business,
    seed_run: DemoSeedRun | None,
    lock: bool = False,
    model_order: tuple[type[models.Model], ...] = RESET_MODEL_ORDER,
) -> DemoSeedResetPlan:
    models_by_label = {model._meta.label: model for model in model_order}
    empty_pks = {label: () for label in models_by_label}
    if seed_run is None:
        return DemoSeedResetPlan(
            business_id=business.pk,
            business_slug=business.slug,
            seed_run_id=None,
            object_pks=empty_pks,
            stale_tracking_record_count=0,
            tracking_record_count=0,
        )
    if seed_run.business_id != business.pk:
        raise DemoSeedResetError("Demo seed metadata does not belong to the selected business.")

    tracking_records = list(
        seed_run.owned_records.order_by("model_label", "object_pk").values(
            "model_label",
            "object_pk",
        )
    )
    unknown_labels = sorted(
        {record["model_label"] for record in tracking_records} - set(models_by_label)
    )
    if unknown_labels:
        raise DemoSeedResetError(
            "Reset aborted because demo tracking contains unsupported model labels: "
            + ", ".join(unknown_labels)
        )

    tracked_pks: dict[str, list[int]] = {label: [] for label in models_by_label}
    for record in tracking_records:
        try:
            object_pk = int(record["object_pk"])
        except (TypeError, ValueError) as exc:
            raise DemoSeedResetError(
                "Reset aborted because demo tracking contains an invalid object primary key."
            ) from exc
        if object_pk <= 0:
            raise DemoSeedResetError(
                "Reset aborted because demo tracking contains an invalid object primary key."
            )
        tracked_pks[record["model_label"]].append(object_pk)

    object_pks: dict[str, tuple[int, ...]] = {}
    stale_count = 0
    objects_by_label: dict[str, tuple[models.Model, ...]] = {}
    for model in model_order:
        label = model._meta.label
        requested_pks = tuple(sorted(set(tracked_pks[label])))
        queryset = model._default_manager.filter(pk__in=requested_pks).order_by("pk")
        if lock:
            queryset = queryset.select_for_update()
        objects = tuple(queryset)
        found_pks = tuple(obj.pk for obj in objects)
        stale_count += len(requested_pks) - len(found_pks)
        object_pks[label] = found_pks
        objects_by_label[label] = objects

    _validate_tenant_ownership(business=business, objects_by_label=objects_by_label)
    _validate_no_genuine_dependents(object_pks=object_pks)
    _validate_no_other_seed_claims(seed_run=seed_run, object_pks=object_pks)

    return DemoSeedResetPlan(
        business_id=business.pk,
        business_slug=business.slug,
        seed_run_id=str(seed_run.run_id),
        object_pks=object_pks,
        stale_tracking_record_count=stale_count,
        tracking_record_count=len(tracking_records),
    )


def execute_demo_seed_reset(
    *,
    seed_run: DemoSeedRun,
    plan: DemoSeedResetPlan,
    model_order: tuple[type[models.Model], ...] = RESET_MODEL_ORDER,
) -> DemoSeedResetResult:
    if str(seed_run.run_id) != plan.seed_run_id or seed_run.business_id != plan.business_id:
        raise DemoSeedResetError("Demo seed metadata changed before reset execution.")

    deleted_counts: dict[str, int] = {}
    for model in model_order:
        label = model._meta.label
        pks = plan.object_pks[label]
        deleted_counts[label] = model._default_manager.filter(pk__in=pks).count()
        queryset = model._default_manager.filter(pk__in=pks)
        if model in (ParcelEvent, Parcel, Shipment):
            queryset._purge_delete()
        else:
            queryset.delete()

    deleted_tracking_records = DemoSeedRecord.objects.filter(seed_run=seed_run).count()
    DemoSeedRecord.objects.filter(seed_run=seed_run).delete()
    seed_run.delete()
    return DemoSeedResetResult(
        deleted_counts=deleted_counts,
        deleted_tracking_records=deleted_tracking_records,
        deleted_seed_run=True,
    )


def _validate_tenant_ownership(
    *,
    business: Business,
    objects_by_label: dict[str, tuple[models.Model, ...]],
) -> None:
    for label, objects in objects_by_label.items():
        for obj in objects:
            owner_business_id = _object_business_id(obj)
            if owner_business_id != business.pk:
                raise DemoSeedResetError(
                    f"Reset aborted: tracked {label} object #{obj.pk} does not belong "
                    "to the selected business."
                )
            _validate_related_tenant_ids(obj=obj, business_id=business.pk)


def _object_business_id(obj: models.Model) -> int | None:
    if isinstance(obj, InvoiceLine):
        return obj.invoice.business_id
    return getattr(obj, "business_id", None)


def _validate_related_tenant_ids(*, obj: models.Model, business_id: int) -> None:
    related_business_ids: list[int | None] = []
    if isinstance(obj, Parcel):
        related_business_ids.append(obj.client.business_id)
        if obj.shipment_id is not None:
            related_business_ids.append(obj.shipment.business_id)
    elif isinstance(obj, ParcelEvent):
        related_business_ids.append(obj.parcel.business_id)
    elif isinstance(obj, InvoiceLine):
        if obj.service_id is not None:
            related_business_ids.append(obj.service.business_id)
    elif isinstance(obj, Invoice):
        related_business_ids.append(obj.client.business_id)
        if obj.appointment_id is not None:
            related_business_ids.append(obj.appointment.business_id)
    elif isinstance(obj, Appointment):
        related_business_ids.append(obj.client.business_id)
        if obj.service_id is not None:
            related_business_ids.append(obj.service.business_id)
        if obj.source_lead_id is not None:
            related_business_ids.append(obj.source_lead.business_id)
    elif isinstance(obj, Lead):
        if obj.category_id is not None:
            related_business_ids.append(obj.category.business_id)
        if obj.requested_service_id is not None:
            related_business_ids.append(obj.requested_service.business_id)
    elif isinstance(obj, BusinessService) and obj.category_id is not None:
        related_business_ids.append(obj.category.business_id)

    if any(related_business_id != business_id for related_business_id in related_business_ids):
        raise DemoSeedResetError(
            f"Reset aborted: tracked {obj._meta.label} object #{obj.pk} has a "
            "cross-business relationship."
        )


def _validate_no_genuine_dependents(*, object_pks: dict[str, tuple[int, ...]]) -> None:
    owned = {
        model._meta.label: set() for model in (*RESET_MODEL_ORDER, ParcelEvent, Parcel, Shipment)
    }
    owned.update({label: set(pks) for label, pks in object_pks.items()})
    blockers: list[str] = []

    for description, queryset, label in (
        (
            "logistics.Parcel.client -> seeded client",
            Parcel.objects.filter(client_id__in=owned[Client._meta.label]),
            Parcel._meta.label,
        ),
        (
            "logistics.Parcel.shipment -> seeded shipment",
            Parcel.objects.filter(shipment_id__in=owned[Shipment._meta.label]),
            Parcel._meta.label,
        ),
        (
            "logistics.ParcelEvent.parcel -> seeded parcel",
            ParcelEvent.objects.filter(parcel_id__in=owned[Parcel._meta.label]),
            ParcelEvent._meta.label,
        ),
    ):
        _append_unowned_blocker(
            blockers, description=description, queryset=queryset, owned_pks=owned[label]
        )
    if (
        ParcelEvent.objects.filter(pk__in=owned[ParcelEvent._meta.label])
        .exclude(parcel_id__in=owned[Parcel._meta.label])
        .exists()
    ):
        blockers.append("seeded event -> genuine parcel")
    if (
        Parcel.objects.filter(pk__in=owned[Parcel._meta.label], shipment__isnull=False)
        .exclude(shipment_id__in=owned[Shipment._meta.label])
        .exists()
    ):
        blockers.append("seeded parcel -> genuine shipment")

    _append_unowned_blocker(
        blockers,
        description="billings.InvoiceLine.invoice -> seeded invoice",
        queryset=InvoiceLine.objects.filter(invoice_id__in=owned[Invoice._meta.label]),
        owned_pks=owned[InvoiceLine._meta.label],
    )
    _append_unowned_blocker(
        blockers,
        description="billings.Invoice.appointment -> seeded appointment",
        queryset=Invoice.objects.filter(appointment_id__in=owned[Appointment._meta.label]),
        owned_pks=owned[Invoice._meta.label],
    )
    _append_unowned_blocker(
        blockers,
        description="appointments.Appointment.source_lead -> seeded request",
        queryset=Appointment.objects.filter(source_lead_id__in=owned[Lead._meta.label]),
        owned_pks=owned[Appointment._meta.label],
    )
    _append_unowned_blocker(
        blockers,
        description="crm.ActivityLog.lead -> seeded request",
        queryset=ActivityLog.objects.filter(lead_id__in=owned[Lead._meta.label]),
        owned_pks=set(),
    )
    _append_unowned_blocker(
        blockers,
        description="appointments.Appointment.client -> seeded client",
        queryset=Appointment.objects.filter(client_id__in=owned[Client._meta.label]),
        owned_pks=owned[Appointment._meta.label],
    )
    _append_unowned_blocker(
        blockers,
        description="billings.Invoice.client -> seeded client",
        queryset=Invoice.objects.filter(client_id__in=owned[Client._meta.label]),
        owned_pks=owned[Invoice._meta.label],
    )
    _append_unowned_blocker(
        blockers,
        description="crm.ActivityLog.client -> seeded client",
        queryset=ActivityLog.objects.filter(client_id__in=owned[Client._meta.label]),
        owned_pks=set(),
    )
    _append_unowned_blocker(
        blockers,
        description="crm.Lead.requested_service -> seeded service",
        queryset=Lead.objects.filter(requested_service_id__in=owned[BusinessService._meta.label]),
        owned_pks=owned[Lead._meta.label],
    )
    _append_unowned_blocker(
        blockers,
        description="appointments.Appointment.service -> seeded service",
        queryset=Appointment.objects.filter(service_id__in=owned[BusinessService._meta.label]),
        owned_pks=owned[Appointment._meta.label],
    )
    _append_unowned_blocker(
        blockers,
        description="billings.InvoiceLine.service -> seeded service",
        queryset=InvoiceLine.objects.filter(service_id__in=owned[BusinessService._meta.label]),
        owned_pks=owned[InvoiceLine._meta.label],
    )
    _append_unowned_blocker(
        blockers,
        description="crm.BusinessService.category -> seeded category",
        queryset=BusinessService.objects.filter(category_id__in=owned[ServiceCategory._meta.label]),
        owned_pks=owned[BusinessService._meta.label],
    )
    _append_unowned_blocker(
        blockers,
        description="crm.Lead.category -> seeded category",
        queryset=Lead.objects.filter(category_id__in=owned[ServiceCategory._meta.label]),
        owned_pks=owned[Lead._meta.label],
    )

    owned_line_pks = owned[InvoiceLine._meta.label]
    if owned_line_pks:
        lines_on_genuine_invoices = InvoiceLine.objects.filter(pk__in=owned_line_pks).exclude(
            invoice_id__in=owned[Invoice._meta.label]
        )
        if lines_on_genuine_invoices.exists():
            blockers.append("seeded invoice line -> genuine invoice")

    if blockers:
        raise DemoSeedResetError(
            "Reset aborted because genuine or untracked records depend on seeded data: "
            + "; ".join(blockers)
        )


def _append_unowned_blocker(
    blockers: list[str],
    *,
    description: str,
    queryset: models.QuerySet,
    owned_pks: set[int],
) -> None:
    if owned_pks:
        queryset = queryset.exclude(pk__in=owned_pks)
    if queryset.exists():
        blockers.append(description)


def _validate_no_other_seed_claims(
    *,
    seed_run: DemoSeedRun,
    object_pks: dict[str, tuple[int, ...]],
) -> None:
    for label, pks in object_pks.items():
        if not pks:
            continue
        claimed_elsewhere = DemoSeedRecord.objects.exclude(seed_run=seed_run).filter(
            model_label=label,
            object_pk__in=[str(pk) for pk in pks],
        )
        if claimed_elsewhere.exists():
            raise DemoSeedResetError(
                "Reset aborted because another business's demo seed also claims a selected object."
            )
