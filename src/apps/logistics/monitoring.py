"""Privacy-safe operational signals through existing logging, without blockers."""

import json
import logging
from functools import wraps
from time import perf_counter

logger = logging.getLogger(__name__)


def record_signal(signal, *, business_id=None, outcome="success", duration_ms=None, period=None):
    try:
        fields = {"signal": signal, "business_id": business_id, "outcome": outcome}
        if duration_ms is not None:
            fields["duration_ms"] = round(duration_ms, 2)
        if period is not None:
            fields["period"] = period
        logger.info("logistics.monitoring %s", json.dumps(fields, sort_keys=True))
    except Exception:
        # Observability must not interfere with accepted operational work.
        pass


def observe_document(signal):
    def decorate(function):
        @wraps(function)
        def observed(*args, **kwargs):
            business = kwargs.get("current_business") or kwargs.get("business")
            if business is None or business.vertical != "LOGISTICS":
                return function(*args, **kwargs)
            start, outcome = perf_counter(), "error"
            try:
                result = function(*args, **kwargs)
                outcome = "success"
                return result
            finally:
                record_signal(
                    signal,
                    business_id=business.pk,
                    outcome=outcome,
                    duration_ms=(perf_counter() - start) * 1000,
                )

        return observed

    return decorate


def observe_tracking(function):
    @wraps(function)
    def observed(*args, **kwargs):
        start, outcome = perf_counter(), "error"
        try:
            result = function(*args, **kwargs)
            outcome = "resolved" if result is not None else "unavailable"
            return result
        finally:
            # Never log tracking codes, paths, IPs, payloads or recipient data.
            record_signal(
                "tracking_lookup", outcome=outcome, duration_ms=(perf_counter() - start) * 1000
            )

    return observed
