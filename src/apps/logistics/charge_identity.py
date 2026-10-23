"""Stable purpose/occurrence identity, independent of price and retry tokens."""

import hashlib
import json


def purpose_key(service_id, description):
    return (
        ["service", service_id]
        if service_id
        else ["custom", " ".join(description.split()).casefold()]
    )


def logical_charge_key(*, parcel_id, shipment_id, service_id, description, occurrence_reference=""):
    identity = [
        "parcel" if parcel_id else "shipment",
        parcel_id or shipment_id,
        purpose_key(service_id, description),
        occurrence_reference.strip().casefold(),
    ]
    return hashlib.sha256(
        json.dumps(identity, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
