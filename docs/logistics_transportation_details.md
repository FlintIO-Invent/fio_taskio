# Shipment transportation details V1

Migration `0012_shipment_transport_references` adds eight nullable, optional
strings to the existing Shipment. Carrier, vessel and driver names have a
160-character limit; operational references have a 100-character limit. No
backfill is needed: existing shipments retain null values. Apply the additive
migration before deploying code that reads these fields.

Carrier is available for all modes, including unknown. Sea permits vessel,
voyage, container and bill of lading; Road / Truck permits vehicle, driver and
dispatch. Air, Rail and unknown do not accept new specialized references yet.
Forms and services use the same policy. Empty/whitespace-only entries become
null, and populated entries are trimmed.

New or changed wrong-mode references are rejected with field errors. Unchanged
historical references remain valid when mode or profile configuration changes.
Mode changes never automatically clear saved references. The staff Shipment
detail shows all populated saved references, including historical ones. Normal
forms hide unsupported groups; historical fields can still be cleared through
the update service. HTML and CSV manifests include only populated shared and
current-mode references. They remain staff-only and retain existing parcel
privacy and spreadsheet-formula escaping.

The mode and carrier fields always appear on create/edit. JavaScript switches
specialized groups without discarding input values, and groups with validation
errors remain visible. Without JavaScript, select a mode and use **Update
transportation fields** to refresh the server-rendered groups. Refresh preserves
entries, retry token and loaded revision, and performs no writes. A mode change
followed directly by Save also undergoes full server validation.

All writes use the existing transactional services and draft-only editing rule.
Missing optional fields in old submissions/partial service updates preserve
saved values. Null new fields are omitted from creation fingerprints, preserving
pre-details receipts. Exact receipt replay precedes mode-specific policy checks;
changing a retry payload remains an error. Revision, assignment and tenant
authorization checks remain in force.

The list/dashboard retain their compact mode badges. No new frontend search
framework or usage counters were added. Admin retains its tenant-scoped,
read-only inspection boundary and extends its existing search to carrier,
vessel, voyage, container, bill of lading, vehicle and dispatch references.

Demo Sea shipments receive fictional carrier/vessel and unique DEMO voyage,
container and BOL references. Road shipments receive fictional carrier/driver
and unique DEMO vehicle/dispatch references. Profile modes remain SEA + ROAD;
existing demo runs are upgraded through the normal reset/reseed workflow.

Suggested next block: tenant-scoped Shipment document attachments for bills of
lading and dispatch documents, using existing staff authorization and audit
patterns, before considering multimodal legs or separate operational modules.
