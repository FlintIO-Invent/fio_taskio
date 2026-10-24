"""Services admission checks; independent of Logistics counters and billing state."""

from contextlib import contextmanager

from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from .usage_limits import (
    CapacityQuerySet,
    QuotaError,
    _active,
    _check,
    lock_capacity_scope,
    utc_month_bounds,
)

METRICS = {
    "crm.client": "clients",
    "billings.invoice": "invoices_per_month",
    "appointments.appointment": "appointments_per_month",
    "businesses.businessuser": "users",
    "businesses.businessinvitation": "users",
}
PROTECTED = {
    "business",
    "business_id",
    "is_active",
    "client_status",
    "start_time",
    "end_time",
    "staff_member",
    "staff_member_id",
    "role",
    "created_at",
    "status",
    "expires_at",
    "email",
    "user",
    "user_id",
}


def appointment_usage(business, instant, *, exclude_pk=None, using=DEFAULT_DB_ALIAS):
    start, end = utc_month_bounds(instant)
    return (
        business.appointments.using(using)
        .filter(start_time__gte=start, start_time__lt=end)
        .exclude(pk=exclude_pk)
        .count()
    )


def _seats(business, using, *, reservation=None):
    return (
        business.memberships.using(using).filter(is_active=True).count()
        + business.invitations.using(using)
        .filter(status="pending", expires_at__gt=timezone.now())
        .exclude(pk=reservation)
        .count()
    )


@contextmanager
def service_write_scope(instance, options):
    from .models import Business
    from .utils import get_business_usage_count

    metric = METRICS.get(instance._meta.label_lower)
    using = options.get("using") or instance._state.db or DEFAULT_DB_ALIAS
    fields = options.get("update_fields")
    if metric is None or (fields is not None and not fields):
        yield
        return
    original = (
        type(instance).objects.using(using).filter(pk=instance.pk).values().first()
        if instance.pk
        else None
    )
    business_id = instance.business_id
    if original and fields is not None and not {"business", "business_id"}.intersection(fields):
        business_id = original["business_id"]
    if (
        original
        and original["business_id"] != business_id
        and Business.objects.using(using)
        .filter(pk=original["business_id"], vertical="SERVICE")
        .exists()
    ):
        raise QuotaError("Workspace ownership cannot be changed for Services capacity records.")
    if (
        business_id is None
        or not Business.objects.using(using).filter(pk=business_id, vertical="SERVICE").exists()
    ):
        yield
        return
    with transaction.atomic(using=using):
        business, subscription = lock_capacity_scope(business_id, using=using)
        previous = (
            type(instance).objects.using(using).filter(pk=instance.pk).values().first()
            if instance.pk
            else None
        )
        projected = dict(previous or {})
        for field in instance._meta.concrete_fields:
            if (
                previous is None
                or fields is None
                or field.name in fields
                or field.attname in fields
            ):
                projected[field.attname] = getattr(instance, field.attname)
        if previous and projected["business_id"] != previous["business_id"]:
            raise QuotaError("Workspace ownership cannot be changed for Services capacity records.")
        new = previous is None
        label = instance._meta.label_lower
        if metric == "appointments_per_month":
            consumes = (
                new
                or utc_month_bounds(previous["start_time"])[0]
                != utc_month_bounds(projected["start_time"])[0]
            )
            usage = (
                appointment_usage(
                    business, projected["start_time"], exclude_pk=instance.pk, using=using
                )
                if consumes
                else 0
            )
        elif metric == "invoices_per_month":
            consumes = new
            usage = get_business_usage_count(business, metric) if consumes else 0
        elif metric == "clients":
            consumes = _active(metric, projected) and not _active(metric, previous or {})
            usage = get_business_usage_count(business, metric) if consumes else 0
        elif label == "businesses.businessinvitation":
            consumes = (
                projected["status"] == "pending"
                and projected["expires_at"] > timezone.now()
                and not (
                    previous
                    and previous["status"] == "pending"
                    and previous["expires_at"] > timezone.now()
                )
            )
            usage = _seats(business, using, reservation=instance.pk) if consumes else 0
        else:
            consumes = projected["is_active"] and not (previous or {}).get("is_active", False)
            usage = (
                _seats(
                    business, using, reservation=getattr(instance, "_service_reservation_id", None)
                )
                if consumes
                else 0
            )
            # Registration creates its first owner before provisioning the subscription.
            bootstrap = (
                subscription is None
                and new
                and projected["role"] == "owner"
                and not business.memberships.using(using).exists()
                and business.is_active
            )
            if bootstrap:
                consumes = False
        if consumes:
            label = None
            if metric == "appointments_per_month":
                month, _ = utc_month_bounds(projected["start_time"])
                label = f"appointments for {month:%B %Y} (UTC)"
            _check(business, metric, usage, label=label)
        original_state = (instance.pk, instance._state.adding, instance._state.db)
        try:
            yield
            if new and metric == "invoices_per_month":
                start, end = utc_month_bounds(instance.created_at)
                count = (
                    business.invoices.using(using)
                    .filter(created_at__gte=start, created_at__lt=end)
                    .exclude(pk=instance.pk)
                    .count()
                )
                _check(business, metric, count)
        except Exception:
            if new:
                instance.pk, instance._state.adding, instance._state.db = original_state
            raise


class ServiceCapacityQuerySet(CapacityQuerySet):
    """Services bulk writers use the same admission boundary as individual saves."""

    def _service_ids(self):
        return self.filter(business__vertical="SERVICE").values_list("pk", flat=True)

    def _business_ids(self, objs):
        from .models import Business

        return set(
            Business.objects.using(self.db)
            .filter(pk__in={o.business_id for o in objs}, vertical="SERVICE")
            .values_list("pk", flat=True)
        )

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        kwargs = dict(
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )
        objs = list(objs)
        ids = self._business_ids(objs)
        if not ids:
            return super().bulk_create(objs, **kwargs)
        if kwargs.get("ignore_conflicts") or kwargs.get("update_conflicts"):
            raise QuotaError("Use a retry key for capacity-managed operations.")
        originals = [(o, o.pk, o._state.adding, o._state.db) for o in objs]
        try:
            with transaction.atomic(using=self.db):
                for pk in sorted(ids):
                    lock_capacity_scope(pk, using=self.db)
                for obj in objs:
                    if obj.business_id in ids:
                        obj.save(force_insert=True, using=self.db)
                super().bulk_create([o for o in objs if o.business_id not in ids], **kwargs)
        except Exception:
            for obj, pk, adding, db in originals:
                obj.pk, obj._state.adding, obj._state.db = pk, adding, db
            raise
        return objs

    def update(self, **kwargs):
        if not PROTECTED.intersection(kwargs):
            return super().update(**kwargs)
        target = kwargs.get("business_id", getattr(kwargs.get("business"), "pk", None))
        if target and self._business_ids([self.model(business_id=target)]):
            raise QuotaError("Workspace ownership cannot be changed with a bulk update.")
        with transaction.atomic(using=self.db):
            rows = list(self.filter(pk__in=self._service_ids()).order_by("business_id", "pk"))
            if rows and any(hasattr(v, "resolve_expression") for v in kwargs.values()):
                raise QuotaError("Use explicit values for capacity-managed bulk updates.")
            for pk in sorted({o.business_id for o in rows}):
                lock_capacity_scope(pk, using=self.db)
            for obj in rows:
                for name, value in kwargs.items():
                    setattr(obj, name, value)
                obj.save(using=self.db, update_fields=list(kwargs))
            return len(rows) + super(
                ServiceCapacityQuerySet, self.exclude(business__vertical="SERVICE")
            ).update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        objs = list(objs)
        if not PROTECTED.intersection(fields):
            return super().bulk_update(objs, fields, batch_size=batch_size)
        sources = set(
            self.model.objects.using(self.db).filter(pk__in=[o.pk for o in objs])._service_ids()
        )
        targets = self._business_ids(objs)
        if not (sources or targets):
            return super().bulk_update(objs, fields, batch_size=batch_size)
        if any(
            hasattr(getattr(obj, field), "resolve_expression") for obj in objs for field in fields
        ):
            raise QuotaError("Use explicit values for capacity-managed bulk updates.")
        with transaction.atomic(using=self.db):
            for pk in sorted(targets):
                lock_capacity_scope(pk, using=self.db)
            for obj in objs:
                if obj.pk in sources or obj.business_id in targets:
                    obj.save(using=self.db, update_fields=fields)
            super().bulk_update(
                [o for o in objs if o.pk not in sources and o.business_id not in targets],
                fields,
                batch_size=batch_size,
            )
        return len(objs)

    def update_or_create(self, defaults=None, create_defaults=None, **kwargs):
        candidate = {**kwargs, **(create_defaults or defaults or {})}
        business_id = candidate.get("business_id", getattr(candidate.get("business"), "pk", None))
        with transaction.atomic(using=self.db):
            rows = self.filter(**kwargs)
            ids = set(rows.filter(pk__in=rows._service_ids()).values_list("business_id", flat=True))
            if business_id:
                ids.update(self._business_ids([self.model(business_id=business_id)]))
            for pk in sorted(ids):
                lock_capacity_scope(pk, using=self.db)
            return super().update_or_create(
                defaults=defaults, create_defaults=create_defaults, **kwargs
            )
