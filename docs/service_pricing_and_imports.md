# Motionmate Service Pricing and Imports

Service prices and tax rates are stored as `Decimal` values. Display formatting is based on the current `Business` profile:

- `currency` controls the visible symbol or currency code.
- `default_locale` and `country` control decimal and thousands separators.
- European-style locales such as `nl-NL` display comma decimals, for example `€1.234,56`.
- Caribbean and English-style workspaces display decimal points, for example `$1,234.56`.

Service setup accepts regular decimal input such as `1234.56`. For comma-decimal workspaces, service setup and CSV import also accept values such as `1.234,56`.

New services default to the business tax rate from Business Settings when the service tax rate is left blank. Changing the business tax default affects new services only; existing services keep their current tax rate until edited manually.

The service import page shows required columns, optional columns, sample rows, and copyable CSV text in the browser. Users can still download the sample CSV when they prefer a file.
