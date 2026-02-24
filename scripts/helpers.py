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