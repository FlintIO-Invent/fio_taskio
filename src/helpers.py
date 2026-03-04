from __future__ import annotations
from typing import Tuple
from django.db import transaction
from apps.crm.models import Client, Lead
# from .models import Client, Lead

# def convert_lead_to_client(lead: Lead) -> Client:
#     client, _ = Client.objects.get_or_create(
#         email=lead.email,
#         defaults={
#             "first_name": lead.first_name,
#             "last_name": lead.last_name,
#             "phone": lead.phone,
#             "message": lead.message,
#             "consent_to_contact": lead.consent_to_contact,
#         },
#     )

#     # Optional: keep it updated if the lead had newer info
#     changed = False
#     for field in ["first_name", "last_name", "phone"]:
#         val = getattr(lead, field)
#         if val and getattr(client, field) != val:
#             setattr(client, field, val)
#             changed = True
#     if changed:
#         client.save()

#     return client





@transaction.atomic
def upsert_client_from_lead(lead: Lead) -> Tuple[Client, bool]:
    """
    Create or update a Client from a Lead.

    Returns (client, created).
    Uses email as primary match key; you can switch to phone if that's better.
    """
    defaults = {
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "phone": lead.phone,
        "street_address": getattr(lead, "street_address", ""),
        "district": getattr(lead, "district", None),
        "country": getattr(lead, "country", "Sint Maarten"),
        "postal_code": getattr(lead, "postal_code", "N/A"),
        # add more mappings as needed
    }

    client, created = Client.objects.update_or_create(
        email=lead.email,
        defaults=defaults,
    )
    return client, created