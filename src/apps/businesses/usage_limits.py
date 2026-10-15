"""Shared Logistics quota boundary. Entitlements still come from businesses.utils."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import DEFAULT_DB_ALIAS, models, transaction
from django.utils import timezone

from .plan_catalog import LOGISTICS_TIER_SLUGS

MODEL_METRICS = {
    "crm.client": "clients",
    "crm.businessservice": "services",
    "businesses.businessuser": "users",
    "businesses.businessinvitation": "users",
    "logistics.logisticslocation": "locations",
    "logistics.parcel": "parcels_per_month",
    "logistics.shipment": "shipments_per_month",
    "billings.invoice": "invoices_per_month",
}
MONTHLY_MODELS = {
    "parcels_per_month": "logistics.Parcel",
    "shipments_per_month": "logistics.Shipment",
    "invoices_per_month": "billings.Invoice",
}
PROTECTED_FIELDS = {
    "business",
    "business_id",
    "is_active",
    "client_status",
    "created_at",
    "status",
    "expires_at",
    "email",
    "user",
    "user_id",
}


class QuotaError(ValidationError):
    """Safe for forms, APIs and import execution to report to the workspace user."""


def utc_month_bounds(instant=None):
    instant = instant or timezone.now()
    if timezone.is_naive(instant):
        raise ValueError("Usage timestamps must be timezone-aware.")
    start = instant.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def lock_capacity_scope(business_id, *, using=DEFAULT_DB_ALIAS):
    from .models import Business, BusinessSubscription

    if not transaction.get_connection(using).in_atomic_block:
        raise RuntimeError("Capacity locks require transaction.atomic().")
    business = Business.objects.using(using).select_for_update().get(pk=business_id)
    subscription = (
        BusinessSubscription.objects.using(using)
        .select_for_update(of=("self",))
        .select_related("plan")
        .filter(business_id=business_id)
        .first()
    )
    business._state.fields_cache["subscription"] = subscription
    return business, subscription


def is_capacity_tier(business, subscription):
    return bool(
        business.vertical == "LOGISTICS"
        and subscription
        and subscription.plan.slug in LOGISTICS_TIER_SLUGS
    )


def seat_usage(
    business,
    *,
    exclude_email=None,
    exclude_invitation_pk=None,
    using=DEFAULT_DB_ALIAS,
    include_details=False,
):
    from .models import BusinessInvitation, BusinessUser

    members = BusinessUser.objects.using(using).filter(business_id=business.pk, is_active=True)
    active_emails = {email.casefold() for email in members.values_list("user__email", flat=True)}
    if exclude_email:
        active_emails.add(exclude_email.casefold())
    pending = (
        BusinessInvitation.objects.using(using)
        .filter(business_id=business.pk, status="pending", expires_at__gt=timezone.now())
        .exclude(pk=exclude_invitation_pk)
        .values_list("email", flat=True)
    )
    active_count = members.count()
    reserved_count = len({email.casefold() for email in pending} - active_emails)
    return (active_count, reserved_count) if include_details else active_count + reserved_count


def monthly_usage(
    business,
    subscription,
    metric,
    *,
    instant=None,
    exclude_pk=None,
    using=DEFAULT_DB_ALIAS,
    refresh=True,
):
    from django.apps import apps

    start, end = utc_month_bounds(instant)
    key = start.strftime("%Y-%m")
    ledger = (
        type(subscription)
        .objects.using(using)
        .values_list("logistics_monthly_usage", flat=True)
        .get(pk=subscription.pk)
        if refresh
        else subscription.logistics_monthly_usage
    )
    if ledger is None:
        ledger = {}
    if not isinstance(ledger, dict) or not isinstance(ledger.get(key, {}), dict):
        raise QuotaError(
            "Workspace usage could not be verified. Please contact the workspace owner.",
            code="quota_unavailable",
        )
    stored = ledger.get(key, {}).get(metric)
    if metric in ledger.get(key, {}):
        if type(stored) is not int or stored < 0:
            raise QuotaError(
                "Workspace usage could not be verified. Please contact the workspace owner.",
                code="quota_unavailable",
            )
        return stored
    query = (
        apps.get_model(MONTHLY_MODELS[metric])
        .objects.using(using)
        .filter(
            business_id=business.pk,
            created_at__gte=start,
            created_at__lt=end,
        )
    )
    if exclude_pk is not None:
        query = query.exclude(pk=exclude_pk)
    return query.count()


def _check(business, metric, usage, *, increase=1):
    from .utils import PLAN_LIMIT_LABELS, resolve_business_plan_limit

    entitlement = resolve_business_plan_limit(business, metric)
    if not entitlement.available:
        raise QuotaError(
            "Workspace capacity could not be verified. Please contact the workspace owner.",
            code="quota_unavailable",
        )
    if entitlement.limit is not None and usage + increase > entitlement.limit:
        label = PLAN_LIMIT_LABELS.get(metric, metric.replace("_", " "))
        raise QuotaError(
            f"This workspace has reached its allowance of {entitlement.limit} {label}. "
            "Please ask the workspace owner to review capacity before adding more.",
            code="quota_exceeded",
        )


def _active(metric, values):
    return bool(
        values.get("is_active")
        and (metric != "clients" or values.get("client_status") not in {"INACTIVE", "ARCHIVED"})
    )


@contextmanager
def _save_scope(instance, kwargs):
    """Lock Business then subscription, respecting partial saves."""
    from .models import Business, BusinessInvitation, BusinessUser
    from .utils import get_business_usage_count

    metric = MODEL_METRICS.get(instance._meta.label_lower)
    using = kwargs.get("using") or instance._state.db or DEFAULT_DB_ALIAS
    business_id = getattr(instance, "business_id", None)
    fields = kwargs.get("update_fields")
    if fields is not None and not fields:
        yield
        return
    origin = (
        type(instance).objects.using(using).filter(pk=instance.pk).values("business_id").first()
        if metric and instance.pk
        else None
    )
    if origin and fields is not None and not {"business", "business_id"}.intersection(fields):
        business_id = origin["business_id"]
    if (
        origin
        and origin["business_id"] != business_id
        and Business.objects.using(using)
        .filter(
            pk=origin["business_id"],
            vertical="LOGISTICS",
            subscription__plan__slug__in=LOGISTICS_TIER_SLUGS,
        )
        .exists()
    ):
        raise QuotaError("Workspace ownership cannot be changed for capacity-managed records.")
    if (
        metric is None
        or business_id is None
        or not Business.objects.using(using).filter(pk=business_id, vertical="LOGISTICS").exists()
    ):
        yield
        return
    with transaction.atomic(using=using):
        business, subscription = lock_capacity_scope(business_id, using=using)
        if not is_capacity_tier(business, subscription):
            yield
            return
        previous = (
            type(instance).objects.using(using).filter(pk=instance.pk).values().first()
            if instance.pk
            else None
        )
        new = previous is None
        projected = dict(previous or {})
        for field in instance._meta.concrete_fields:
            if new or fields is None or field.name in fields or field.attname in fields:
                projected[field.attname] = getattr(instance, field.attname)
        if previous and previous["business_id"] != business_id:
            raise QuotaError("Workspace ownership cannot be changed for capacity-managed records.")
        if (
            previous
            and metric in MONTHLY_MODELS
            and projected["created_at"] != previous["created_at"]
        ):
            raise QuotaError(
                "The creation timestamp cannot be changed for a capacity-managed record."
            )
        consumes = (
            new
            if metric in MONTHLY_MODELS
            else _active(metric, projected) and not _active(metric, previous or {})
        )
        if instance._meta.label_lower == "businesses.businessinvitation":
            now = timezone.now()
            active_email = (
                BusinessUser.objects.using(using)
                .filter(
                    business_id=business_id, is_active=True, user__email__iexact=projected["email"]
                )
                .exists()
            )
            duplicate = (
                BusinessInvitation.objects.using(using)
                .filter(
                    business_id=business_id,
                    email__iexact=projected["email"],
                    status="pending",
                    expires_at__gt=now,
                )
                .exclude(pk=instance.pk)
                .exists()
            )
            was_reserved = (
                previous
                and previous["status"] == "pending"
                and previous["expires_at"] > now
                and previous["email"].casefold() == projected["email"].casefold()
            )
            consumes = (
                projected["status"] == "pending"
                and projected["expires_at"] > now
                and not (active_email or duplicate or was_reserved)
            )
        if consumes:
            if metric in MONTHLY_MODELS:
                usage = monthly_usage(business, subscription, metric, using=using, refresh=False)
            elif metric == "users":
                email = (
                    instance.user.email
                    if instance._meta.label_lower == "businesses.businessuser"
                    else None
                )
                usage = seat_usage(
                    business,
                    exclude_email=email,
                    exclude_invitation_pk=(
                        instance.pk
                        if instance._meta.label_lower == "businesses.businessinvitation"
                        else None
                    ),
                    using=using,
                )
            else:
                usage = get_business_usage_count(business, metric)
            _check(business, metric, usage)
        original_pk, original_adding = instance.pk, instance._state.adding
        try:
            yield
            if consumes and metric in MONTHLY_MODELS:
                # auto_now_add supplies the authoritative insertion time, including
                # a rollover between the preliminary check and actual INSERT.
                instant = instance.created_at
                usage = monthly_usage(
                    business,
                    subscription,
                    metric,
                    instant=instant,
                    exclude_pk=instance.pk,
                    using=using,
                    refresh=False,
                )
                _check(business, metric, usage)
                ledger = deepcopy(subscription.logistics_monthly_usage or {})
                key = utc_month_bounds(instant)[0].strftime("%Y-%m")
                ledger.setdefault(key, {})[metric] = usage + 1
                type(subscription).objects.using(using).filter(pk=subscription.pk).update(
                    logistics_monthly_usage=ledger
                )
                subscription.logistics_monthly_usage = ledger
        except Exception:
            if new:
                instance.pk, instance._state.adding = original_pk, original_adding
            raise


def capacity_guard(save):
    @wraps(save)
    def guarded(instance, *args, **kwargs):
        if args:
            # Preserve Django's legacy positional save options while including
            # using/update_fields in the quota projection.
            names = ("force_insert", "force_update", "using", "update_fields")
            options = {**dict(zip(names, args, strict=False)), **kwargs}
        else:
            options = kwargs
        with _save_scope(instance, options):
            return save(instance, *args, **kwargs)

    return guarded


class CapacityQuerySet(models.QuerySet):
    """Ordinary bulk writes cooperate with model guards; SERVICE keeps SQL paths."""

    def _tier_ids(self):
        return self.filter(
            business__vertical="LOGISTICS",
            business__subscription__plan__slug__in=LOGISTICS_TIER_SLUGS,
        ).values_list("pk", flat=True)

    def _tier_business_ids(self, objs):
        from .models import Business

        ids = {obj.business_id for obj in objs if obj.business_id is not None}
        return set(
            Business.objects.using(self.db)
            .filter(
                pk__in=ids, vertical="LOGISTICS", subscription__plan__slug__in=LOGISTICS_TIER_SLUGS
            )
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
        tier_ids = self._tier_business_ids(objs)
        if not tier_ids:
            return super().bulk_create(objs, **kwargs)
        if kwargs.get("ignore_conflicts") or kwargs.get("update_conflicts"):
            raise QuotaError(
                "Use an idempotent service operation for capacity-managed bulk conflicts."
            )
        originals = [(obj, obj.pk, obj._state.adding, obj._state.db) for obj in objs]
        try:
            with transaction.atomic(using=self.db):
                for business_id in sorted(tier_ids):
                    lock_capacity_scope(business_id, using=self.db)
                protected = [obj for obj in objs if obj.business_id in tier_ids]
                other = [obj for obj in objs if obj.business_id not in tier_ids]
                for obj in protected:
                    obj.save(force_insert=True, using=self.db)
                if other:
                    super().bulk_create(other, **kwargs)
        except Exception:
            for obj, pk, adding, db in originals:
                obj.pk, obj._state.adding, obj._state.db = pk, adding, db
            raise
        return objs

    def update(self, **kwargs):
        if not PROTECTED_FIELDS.intersection(kwargs):
            return super().update(**kwargs)
        ids = list(self._tier_ids())
        # Moving ordinary records into a managed tenant must not evade the guard.
        target = kwargs.get("business_id", getattr(kwargs.get("business"), "pk", None))
        if target and self._tier_business_ids([self.model(business_id=target)]):
            raise QuotaError("Workspace ownership cannot be changed with a bulk update.")
        # Restrict the SQL remainder itself, rather than only excluding the IDs
        # selected above: another writer can insert a managed row in that gap.
        other = self.exclude(
            business__vertical="LOGISTICS",
            business__subscription__plan__slug__in=LOGISTICS_TIER_SLUGS,
        )
        if not ids:
            return super(CapacityQuerySet, other).update(**kwargs)
        if any(hasattr(value, "resolve_expression") for value in kwargs.values()):
            raise QuotaError("Use explicit values for capacity-managed bulk updates.")
        with transaction.atomic(using=self.db):
            rows = list(
                self.model.objects.using(self.db).filter(pk__in=ids).order_by("business_id", "pk")
            )
            for business_id in sorted({obj.business_id for obj in rows}):
                lock_capacity_scope(business_id, using=self.db)
            for obj in rows:
                for field, value in kwargs.items():
                    setattr(obj, field, value)
                obj.save(using=self.db, update_fields=list(kwargs))
            return len(rows) + super(CapacityQuerySet, other).update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        objs = list(objs)
        source = set(
            self.model.objects.using(self.db).filter(pk__in=[obj.pk for obj in objs])._tier_ids()
        )
        targets = self._tier_business_ids(objs)
        if not PROTECTED_FIELDS.intersection(fields) or not (targets or source):
            return super().bulk_update(objs, fields, batch_size=batch_size)
        if any(
            hasattr(getattr(obj, field), "resolve_expression") for obj in objs for field in fields
        ):
            raise QuotaError("Use explicit values for capacity-managed bulk updates.")
        with transaction.atomic(using=self.db):
            for business_id in sorted(targets):
                lock_capacity_scope(business_id, using=self.db)
            protected = [obj for obj in objs if obj.pk in source or obj.business_id in targets]
            other = [obj for obj in objs if obj not in protected]
            for obj in protected:
                obj.save(using=self.db, update_fields=fields)
            if other:
                super().bulk_update(other, fields, batch_size=batch_size)
        return len(objs)

    def update_or_create(self, defaults=None, create_defaults=None, **kwargs):
        with transaction.atomic(using=self.db):
            rows = self.filter(**kwargs)
            ids = set(rows.filter(pk__in=rows._tier_ids()).values_list("business_id", flat=True))
            candidate = (create_defaults or defaults or {}).get("business", kwargs.get("business"))
            candidate_id = (create_defaults or defaults or {}).get(
                "business_id", kwargs.get("business_id", getattr(candidate, "pk", None))
            )
            if candidate_id:
                ids.update(self._tier_business_ids([self.model(business_id=candidate_id)]))
            for business_id in sorted(ids):
                lock_capacity_scope(business_id, using=self.db)
            return super().update_or_create(
                defaults=defaults, create_defaults=create_defaults, **kwargs
            )
