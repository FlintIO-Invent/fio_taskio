# Shipment write safety

Shipment writes continue to use the existing services, lifecycle and Parcel rules.
All writes hold the Business lock, then lock the affected Shipment/Parcel rows inside
a database transaction. Parcel status/event updates and Shipment status changes roll
back together. Creation/editing with optional Parcel assignment is also one transaction.

Create forms carry a UUID retry key; a database constraint makes it unique per Business.
Each Shipment retains hashed receipts for its successful keyed operations. The hashes
bind the operation, actor, submitted payload and loaded revision without copying private
notes into the receipts. Matching retries return the existing result/current row without
writing again. A key reused with different input fails clearly. Receipts survive later
edits, membership changes and lifecycle transitions, so an old retry cannot restore old
details, repeat a departure, or remove a later reassignment.

Edit, assignment, removal and status forms carry a hidden Shipment revision and a UUID
retry key. New detail/membership/status writes increment the revision under the row lock.
A new write from an older revision fails with a reload message. Recorded retries are
recognized before stale-revision/lifecycle checks, but current tenant, actor and access
checks still apply. Replaying a completed operation on a frozen Shipment is a no-op;
new writes remain subject to the existing frozen/terminal rules.

Services accept retry keys for non-UI callers. Editing requires an explicit loaded
revision or derives it from the supplied Shipment instance. Other existing service
callers retain their current optional precondition behavior; UI writes require both
tokens. Legacy Shipments start at revision 1 with no creation key or receipts, and
existing forms without the new hidden fields must be reloaded. No SERVICE behavior
or Parcel lifecycle transition is changed.

Receipts are stored on the existing Shipment row, so existing tenant inspection,
demo reset and controlled purge paths continue to own their retention and deletion.
