# MotionMate Service Pricing and Imports

Services are the saved work items a business can reuse in invoices, appointments, public booking, and service requests.

Service prices and tax rates are stored as decimal money values. Display formatting is based on the current business profile:

- `currency` controls the visible symbol or currency code.
- `default_locale` and `country` control decimal and thousands separators.
- European-style locales such as `nl-NL` display comma decimals, for example `€1.234,56`.
- Caribbean and English-style workspaces display decimal points, for example `$1,234.56`.

Service setup accepts regular decimal input such as `1234.56`. For comma-decimal workspaces, service setup and CSV import also accept values such as `1.234,56`.

New services default to the business tax rate from Business Settings when the service tax rate is left blank. Changing the business tax default affects new services only; existing services keep their current tax rate until edited manually.

All CSV fields are optional for client, lead, and service imports. Users can omit columns or leave cells blank and use the template header names for the data they have. Supplied values still undergo validation, and entirely empty rows are skipped. Missing contact consent remains false; leads without a type default to `INTEREST`.

New services missing a name or price are imported as inactive and unavailable for online booking. Missing names use `Imported service (row N)` and missing prices use zero; these defaults appear in preview. When `external_code` matches an existing service, omitted columns retain their current values, as do blank name and price cells.

The service import page shows optional columns, sample rows, and copyable CSV text in the browser. Users can still download the sample CSV when they prefer a file.

Current service setup supports:

- service name
- category
- external code
- description
- unit price
- tax rate
- active or archived status
- online booking availability
- default booking duration
- booking buffer
- public booking description
- manual confirmation flag

Invoice line items now let users choose a **Service type**:

- **New service**: enter a one-off service name, quantity, and unit price.
- **Saved service**: select an existing saved service and use its saved description and price.

For a new one-off invoice line, users can turn on **Save to services** to add that service to the business catalog for future invoices and bookings.
