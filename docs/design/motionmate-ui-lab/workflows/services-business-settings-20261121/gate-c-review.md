# Business Settings revision 1 — Gate C review

**Revised locally; awaiting your approval. No acceptance recorded.** The rejected
candidate is retained in [the review archive](revisions/rejected-candidate-1/).
This revision changes seven paths inside the existing 21-file authorization;
no additional functionality, files or resource scope was required.

| Real Django application | Interactive URL |
| --- | --- |
| Original BEFORE | http://127.0.0.1:8820/businesses/settings/ |
| Revised AFTER | http://127.0.0.1:8821/businesses/settings/ |
| Local launcher and synthetic sign-in details | http://127.0.0.1:8822/ |

Use `owner@preview.test` and the password shown by the local launcher. The same
existing verified pair is running; BEFORE was preserved and only AFTER refreshed.
Both began with identical synthetic fixtures. Later native review saves remain
independent; the changed synthetic business/person names and final saved test
logo are intentional review writes, not data loss or fixture resynchronization.

## What changed

The business profile is prominent again: saved invoice logo or building fallback,
business identity, industry, access role, workspace type, country, currency,
timezone and contact information. Edit business profile and invoice-logo shortcuts
lead to their existing fields. The logo remains the existing invoice-branding
setting; it does not add a new shell-branding feature.

A workspace overview brings the existing Team, Services, Booking and owner-only
Subscription destinations forward. Icon navigation reveals focused sections with
an active state, keyboard focus and working hash/back/forward navigation. Drafts
and chosen files remain in place across section changes. Each business section
exposes the same full-form save; invalid sections reveal automatically. All
sections and native forms remain available without JavaScript.

Personal account identity, details and security have a separate card and navigation
group. Business and personal forms retain their own field names and saves. Existing
permissions, subscription gates, records, invoice defaults and booking behavior
remain authoritative. No backend or authentication change was made.

## Review

1. Open the revised overview and inspect the business profile and operational links.
2. Use Edit business profile; move between address, region and invoice sections.
   Confirm the hierarchy, saved logo and same Save business settings action.
3. Try an unsaved draft, switch sections and return. Follow Edit personal details
   and Security to assess the distinction between workspace and personal settings.
4. Review Online booking Copy/Open and the existing Booking rules and availability
   page at `/businesses/settings/booking/`, whose operational behavior is preserved.

Real captures: [BEFORE](evidence/revision-1/before-1440-light.png),
[revised desktop overview](evidence/revision-1/settings-final-1440-light.png),
[revised mobile dark overview](evidence/revision-1/settings-final-390-dark.png),
[invoice section](evidence/revision-1/invoice-final-1440-light.png).

57 Django and 3 boundary tests passed. Browser checks cover 16 screen cases per
side, 64 focused-section cases, light/dark, 320–1440px, native saves/errors,
drafts/files, history, keyboard focus, logo, clipboard, JavaScript-disabled native
forms and RTL. Scoped axe checks pass. The unchanged shared-header accessible-name
finding, select contrast incompletes, blocked vendor requests and runtime/zoom
limits remain in [validation](validation-results.md); no full accessibility or
ordinary-runtime certification is claimed.

Team's 15 candidate files, workflow and running pair are unchanged; Team keeps its
independent review and acceptance. Logistics and previous Services work remain
protected. No ordinary database changes, resets, commits, pushes or deployments.

Current candidate/source/initial-fixture hashes are in
[validation-results.json](validation-results.json), current server/database
identities in [runtime-current.json](runtime-current.json), and the original
approval/resource boundaries in the retained Gate A/B records. The original
BEFORE identity and baseline are unchanged. The latest revision authorization and
rejected candidate are recorded in state without rewriting previous approvals.

Please review this revised design for approval. Workflow v2 requires
“Stop for explicit acceptance” at [Gate C](../../../../../.agents/skills/motionmate-ui-workflow/SKILL.md).
Acceptance is separate from release authorization. Both previews remain available;
see the [runbook](review-runbook.md) for local accounts and ownership-checked commands.

Exact revised review binding: [revision-1-review-identity.json](revision-1-review-identity.json).
