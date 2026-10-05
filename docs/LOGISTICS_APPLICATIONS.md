# Logistics applications (Block 3)

The public page is `/logistics/apply/`. A valid submission creates only a
`LogisticsApplication` and an immutable decision record. All outcomes receive the
same `/logistics/apply/received/` response; existing-user/business matches and
decision reasons stay internal. Submission performs no conversion, subscription or Stripe call.

Application statuses are SUBMITTED, APPROVED, UNDER_REVIEW, DECLINED and WITHDRAWN.
Decisions do not encode payment/enrollment state. `LogisticsApplicationDecision` records
each evaluation/manual decision, its application revision, result and deterministic
recommendation, ordered reason codes, time, rule/config snapshot, relevant operational
inputs, relationship flags, and reviewer/reason for overrides. Reviewer IDs are also
snapshotted so deletion of a reviewer does not erase audit attribution.

Material changes through `save()` (including Django Admin) increment the revision
and evaluate again in the same transaction. A manual approval does not survive
changes without reevaluation. `approved_revision` is set only by the new decision;
reviewing a stale revision fails. Decision/status fields are read-only in forms and
cannot be assigned through ordinary model saves. Do not use bulk updates/raw SQL to
edit application inputs or audit history; future enrollment must revalidate the
stored approved revision. Block 4 enrollment is documented in [LOGISTICS_ENROLLMENT.md](LOGISTICS_ENROLLMENT.md).

## Pilot eligibility configuration

Typed configuration follows the existing environment settings pattern:

| Setting | Default | Meaning |
| --- | --- | --- |
| LOGISTICS_RULE_VERSION | pilot-v1 | Evaluator rule version |
| LOGISTICS_AUTO_APPROVE_MONTHLY_PARCELS | 1000 | Ordinary-volume band |
| LOGISTICS_REVIEW_ABOVE_MONTHLY_PARCELS | 5000 | Mandatory volume review above this value |
| LOGISTICS_HIGH_RESOURCE_MONTHLY_PARCELS | 10000 | Mandatory high-resource review at/above this value |
| LOGISTICS_AUTO_APPROVE_STAFF_COUNT | 10 | Staff threshold |
| LOGISTICS_AUTO_APPROVE_LOCATION_COUNT | 1 | Location/branch threshold |
| LOGISTICS_SUPPORTED_TERRITORIES | empty | Comma-separated or JSON country/territory names eligible for automatic approval |
| LOGISTICS_REGISTRATION_REQUIRED_FOR_AUTO_APPROVAL | True | Missing company registration sends the application to review |

Territories require an explicit pilot decision. Empty or unknown territories review;
country matching ignores case, spacing and punctuation. A registration number remains
optional on the form: its absence can request further review rather than reject intake.
Thresholds are eligibility decisions, not commercial limits, pricing or cost estimates.
Configuration validates `auto <= review < high-resource` before use; every decision
stores its complete snapshot, so threshold changes do not rewrite historical audits.

Up to 1000 parcels and the 1001–5000 band both approve when every other dimension is
simple and supported. Above 5000 reviews. At 10000+ high-resource review is also
recorded. High staff/location counts, custom workflow/details, multi-jurisdiction,
API/integration, custom pricing, relationship/duplicate matches, missing required
registration or unsupported territory all review. Standard tracking and manifests
are ordinary features. High volume with those requirements, middle-band custom/API
requirements, and unknown operation/process types record HIGH_RESOURCE_INTENSITY.
There are no financial cost coefficients or automatic declines in this pilot.

## Internal review and inventory

Django Admin provides application details, current reasons and decision history.
The **Review decision** page requires the existing Django change permission. Manual
approve/decline requires a reason and the displayed application revision. Reevaluate
applies current rules and records a new decision with the requesting reviewer.
Reviewers can also record an applicant's withdrawal with a reason; withdrawn
applications are excluded from active duplicate checks and cannot be edited/reopened.
None of these actions provisions
an account, starts billing or sends applicant notifications.

`inspect_logistics_application --application-id <uuid>` provides a read-only inventory
without contact details. Converted applications now have explicit protected Business/User
links; unconverted applications have none. Matching an email/name is only an eligibility signal and never a purge selector.
Application deletion is blocked by decision PROTECT; Admin deletion is disabled.
The nullable conversion link is registered in tenant inventory and protects
ordinary Business deletion. Controlled purge retains application history and
releases only the Business FK into a conversion identity snapshot (Block 11).
Existing SERVICE tenant and demo behavior is unchanged.

Checkout and operational workflows are implemented. Explicit pilot territories,
commercial activation and delivery of private enrollment grants must be configured
before pilot. Application decision/approval notification delivery remains manual.
