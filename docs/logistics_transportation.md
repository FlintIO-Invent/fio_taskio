# Shipment transportation V1

`Shipment.transport_mode` uses the shared `TransportationMode` taxonomy:
Sea, Air, Road / Truck, and Rail. Null means unknown. There are no mode-specific
models, legs, route constraints, or classification-based capability gates.

Migration `0011_shipment_transport_mode` adds the nullable field and a database
constraint accepting only known modes or null. It backfills a LOGISTICS tenant's
shipments only when its profile contains exactly one known mode. Missing,
unconfigured, or multiple-mode profiles leave historical shipments unknown.
The backfill preserves timestamps, revisions, lifecycle, membership, and retry
receipts. Apply this migration before deploying code that reads the new field.

Shipment forms normally offer the current profile's known modes. New shipments
require one when modes are configured; a single mode is preselected on the new
form. Services enforce the same policy using persisted configuration at write
time. They require an explicit mode rather than guessing an API caller's intent.

When the profile has no known modes (including a missing profile or an operating
area other than Transportation), all four modes are available optionally, with
an explicit Unknown choice. This is the compatibility behavior for legacy
customers. Parcels and Shipments remain available under the existing access rules.

Existing shipments may retain their saved mode after profile changes, including
unknown. Unrelated draft edits and lifecycle operations do not require mode
correction. A changed mode must use the current configured choices, if known.
Forms loaded before this field existed may omit it on edit; omission retains
the saved value. Historical viewing, manifests, filters and inspection do not
depend on the current profile. Geography is unrestricted.

Transactional services retain tenant authorization, revision checks and exact
request receipts. Authorized replay is recognized before current profile policy;
a replay with altered payload is rejected. Creation fingerprints omit null mode
to preserve pre-V1 receipts, including after migration backfill.

The HTML manifest adds a mode badge; CSV adds a `Transportation mode` metadata
row with the display label (or Unknown). Parcel columns and totals remain the
same. Consumers using fixed metadata row offsets must accommodate the new row.
`inspect_business_data` includes tenant-scoped `shipment_transport_mode_summary`
counts with an `unknown` bucket; these are informational, not dashboard KPIs.

The default Logistics demo still configures Transportation with SEA and ROAD.
It creates four Sea shipments on Miami/inter-island routes and two Road / Truck
shipments on the Philipsburg to Cole Bay route. Existing seed ownership,
dry-run, reset and financial safeguards remain in effect. Existing demo runs
are not automatically rewritten; use the existing reset/reseed workflow.

Optional carrier and mode-aware operational references are documented in
[Transportation Details V1](logistics_transportation_details.md). Shipment
retains its current lifecycle without legs or separate operational modules.
