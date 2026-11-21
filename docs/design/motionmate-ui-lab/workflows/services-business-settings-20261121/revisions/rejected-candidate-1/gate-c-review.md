# Business Settings — Gate C review

Implementation complete within the **21-file approved manifest**; final acceptance
is pending. Design v1 and Gate B/resource authorizations are recorded separately.

| Real Django application | URL |
| --- | --- |
| BEFORE Business Settings | http://127.0.0.1:8820/businesses/settings/ |
| AFTER Business Settings | http://127.0.0.1:8821/businesses/settings/ |
| BEFORE Booking rules/availability | http://127.0.0.1:8820/businesses/settings/booking/ |
| AFTER Booking rules/availability | http://127.0.0.1:8821/businesses/settings/booking/ |
| Local launcher and synthetic sign-in details | http://127.0.0.1:8822/ |

| Review identity | SHA-256 |
| --- | --- |
| Current Settings candidate | `b7e55cfdbf1b7cbb3b30a5aa3a1e95cf3e65e154590427343f1132fc8975d27b` |
| AFTER runtime source | `77a9687bdb245b87c5875ad8aa01127b58540b4f7259da0eeecb23680bce2268` |
| Matching initial synthetic fixture | `b611cf5386e43b0c5dac8c5d3b1a9441cf530ef444a31dc5240b6f5fb1c130db` |
| Preserved Team candidate | `75eff468999c7f9360ba94327784190615d008be0a896cf7e49dbb57de587319` |

[Runtime/ownership evidence](runtime-current.json), [validation results](validation-results.json)
and [preservation proof](preservation-results.json) identify the actual independent
loopback PostgreSQL clusters, processes and immutable sources. BEFORE is the
working tree containing completed Team work; it is not a historical Git substitute.

Representative real AFTER evidence: [desktop Settings](evidence/settings-1440-light.png),
[mobile dark Settings](evidence/settings-390-dark.png),
[mobile dark booking configuration](evidence/booking-390-dark.png).
The full BEFORE/AFTER records and raw axe/progress/failure logs remain in the
owned session described in the runtime record.

## What to review

Compact current-workspace/sign-in context and section index; existing company,
address, region and invoice fields, with saved invoice logo scope explained.
Company settings and personal details still save separately; password and legacy
profile navigation retain their original flows. Booking rules, Single/Bulk entry,
active windows and existing deactivation remain separate actual Django forms.
Bulk field IDs are unique without changing payloads, prefixes, guards or tab hooks.
Phoenix stays in place; new styles are Services-scoped and no model/view/form/
resolver/migration/provider behavior was changed.

57 Django tests passed, with five targeted Settings reruns after the markup fix;
three fixture-boundary tests passed. Each side has 16 screen/width/theme browser
cases (1440/768/390/320, light/dark). AFTER passed eight active Bulk pointer/axe
checks and native personal/business/logo/invalid/bulk/deactivation journeys.
No scoped axe violations, duplicate IDs, measured sub-44px control-label targets
or page JavaScript exceptions remain. Initial checkbox/layout failures were fixed
and retained as evidence; no forced clicks bypassed them. Logistics/fallback
rendering and all 15 Team candidate source files are preserved.

## Limits retained for acceptance

- Full-page axe flags an unchanged shared-header search link without an accessible
  name at 720px; the Team desktop full-page run retains two shared sidebar contrast
  nodes. Select-background contrast incompletes are retained. No full accessibility,
  assistive-technology or other-browser certification is claimed.
- Unchanged external vendor requests are blocked by preview routing/CSP and logged;
  no providers, external email or ordinary databases are contacted. Debug-allocator
  synthetic runtime checks do not prove ordinary-runtime/provider/release readiness.
- The older Settings assertions recorded by Team fail identically on BEFORE.
  Team's broad workspace helper now reports authorized sibling drift; its warning
  is retained with exact candidate/source ownership proof, not called a helper pass.
- Actual browser zoom was not certified; 720px CSS reflow is a desktop-200-percent
  proxy. Real mobile/tablet/desktop widths and both themes were exercised.
- AFTER holds browser verification edits to synthetic account/business/logo and
  availability records. Initial fixtures matched; later writes persist independently.
  No automatic reset, reseed or synchronization has occurred.

Review and accept this Settings candidate independently, or request scoped changes.
The [Team review](../services-team-20261121/gate-c-review.md) has its own candidate
and pair at http://127.0.0.1:8812/. Both previews stay available. Gate C acceptance
is not permission to stage, commit, push, merge, deploy or clean up.

See the [local review runbook](review-runbook.md) for synthetic account names,
launcher sign-in details, ownership-checked status/start/stop commands and the
separate cleanup boundary. Both pairs remain running for review.
