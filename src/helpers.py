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

    Returns:
        (client, created)

    Matching strategy:
        - Uses email as the primary unique match key.

    Mapping strategy:
        - Copies shared contact/location fields from Lead to Client.
        - Applies sensible CRM defaults for fields that do not exist on Lead.
    """

    defaults = {
        # Basic identity
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "company_name": lead.company_name,
        "email": lead.email,
        "phone": lead.phone,

        # CRM defaults
        "client_type": Client.ClientType.BUSINESS,
        "client_status": Client.ClientStatus.LEAD,
        "preferred_contact_method": Client.PreferredContactMethod.EMAIL,
        "priority": Client.Priority.MEDIUM,
        "lead_source": Client.LeadSource.WEBSITE,

        # Carry over service interest / notes
        "interested_services": (
            lead.category.name if lead.category else ""
        ),
        "message": lead.message,
        "notes": f"Auto-created from lead #{lead.id}",

        # Address
        "street_address": lead.street_address or "",
        "district": lead.district or "",
        "country": lead.country or "Sint Maarten",
        "postal_code": lead.postal_code or "N/A",

        # Consent / status
        "consent_to_contact": lead.consent_to_contact,
        "is_active": lead.is_active,
    }

    client, created = Client.objects.update_or_create(
        email=lead.email,
        defaults=defaults,
    )

    return client, created