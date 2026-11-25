# Services Registration & Onboarding — Gate A review

Full Redesign · Motionmate Services · **v1** · Awaiting design-direction approval

The proposed direction modernizes the existing journey:

| Surface | V1 direction |
| --- | --- |
| Public Services pricing | Calm comparison, server-supplied allowances/prices, explicit USD/EUR and monthly/yearly totals; retain Silicon and current links. |
| Account/business creation | One grouped form with a quiet editable plan summary; retain all inputs, validation, CSRF and destinations. |
| Billing/private access | Clear location/currency correction and branch-appropriate trial/Beta/free-test help without changing subscription rules. |
| Checkout returns | Factual pending/active/attention/paused states and existing saved-workspace recovery; hosted Stripe remains unchanged. |
| Welcome and Setup Guide | Refine the existing three journeys/current task and distinguish step position from completed work; retain saved state/actions. |
| Mobile/accessibility | Readable type, native controls, visible help/errors/focus, both themes and deliberate stacked layouts. |

Read the [design brief](brief.md), [actual Django source audit](audit.md) and
[prospective validation](validation.md). The [authorization log](approval-log.md)
records the current planning request and pending gates.

Scope-bound design SHA-256:

`3ef0dfeb90ad954709856ed6759d9338ab509910372720d4de1ea846c75efa83`

| Bound design artifact | SHA-256 |
| --- | --- |
| [brief.md](brief.md) | `02bf479410a5d2fb8c89f437fa27cf0daf008002e147c963bf6de82394ff0a2e` |
| [audit.md](audit.md) | `07b63bb7cb01b48ac5e3435cbe3204c1c1cc7fbf11f644a56d1f150e5285e2a0` |
| [source-audit.json](source-audit.json) | `2905a895e3ec19b6b1b1de8694458e7013109fce888ac03ec1376afb32b76c0e` |
| [validation.md](validation.md) | `96d51bfb7964505b84c5beeed27f8d1bf1cf496dade0336835639198514c1cff` |

Approve **Services Registration & Onboarding v1** within the brief's preservation
rules and exclusions. Gate A approval permits preparation of the exact Gate B
implementation manifest, impact/baseline and disposable validation-resource
proposal only; the workflow then stops at B. It does not authorize application
edits, runtime setup, database/provider operations or release actions.

The audit used actual Django source. No browser audit, interactive BEFORE,
disposable environment, provider verification or accessibility measurement has
occurred. Current preview guards block subscription writes and checkout routes;
Gate B must resolve that validation approach explicitly. After B, capture the
actual working-tree BEFORE before edits, implement/validate, refresh AFTER alone
and present one real Django comparison before Gate C. No duplicate prototype.

Logistics and prior Services screens/source/evidence are preserved. No application
file, database, migration, external service, index, commit or deployment changed.
All three approval fields remain null; no implementation manifest/baseline or
candidate exists. [Offline checks](offline-checks.json) cover artifacts, links,
state and source preservation only.

The user explicitly requested this stop. The
[Motionmate UI workflow skill](../../../../../.agents/skills/motionmate-ui-workflow/SKILL.md)
also requires: “Stop for explicit approval.” This is the requested Gate A decision.
