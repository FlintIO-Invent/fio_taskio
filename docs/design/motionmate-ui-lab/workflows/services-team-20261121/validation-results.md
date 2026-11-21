# Team validation results

20 focused Django tests and 5 preview-boundary tests passed. Real Django browser
checks passed at 1440/768/390/320px in light/dark, five fixture scenarios and all
five role boundaries. Native invalid invitation, create/signup/deactivate, draft,
RTL, keyboard and scoped axe checks passed. Logistics fallback rendering matches
frozen BEFORE; original source outside the 15-file scope is preserved.

See [exact results](validation-results.json) for hashes, initial fixture identity,
raw evidence location and limitations. Three legacy Settings assertions reproduce
on BEFORE and AFTER; do not report the full 30-test run as passing. Full-page axe
retains two shared sidebar contrast nodes and an incomplete. Existing-user
acceptance controls remain a separate repair. No provider/ordinary DB verification.
