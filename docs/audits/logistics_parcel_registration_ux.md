# Motionmate Logistics parcel registration — UI/UX redesign specification

**Design: Option A, one compact registration form with visible review, a clear saved result, and optional independent processing.** Put the new parcel first, keep Billing Client/Sender/Recipient separate, and make consecutive registration a deliberate Save → Register Next cycle. Retain Phoenix and the existing services, validation, permissions and transaction boundaries.

Date: **13 November 2026**. Source baseline: working tree at `79f5dd4`, including existing template edits. Inputs: [current-state audit](logistics_parcel_registration_current.md), [workflow proposal](logistics_parcel_registration_proposed.md), root `AGENTS.md`, Motionmate UI skill in Audit/design mode, its Phoenix map, and the current code referenced below. This specification refines Option A; it does not implement it or reopen Option B as a second production mode.

**Evidence boundary:** this is an audit of actual source, including loaded asset paths and responsive rules. No application page was opened, form submitted, fixture created, database accessed, test runner executed or external service contacted. Layout measurements, computed contrast, screen-reader behavior, deployed asset versions and real-device usability were not observed. Statements about present markup/handlers are source findings; layout risks and proposed outcomes are labeled accordingly. Wireframes and all dimensions/targets describe the proposed design, not screenshots or measured improvements.

The only authorized addition is this document. Existing code, both prior audit documents, Services, database state, migrations, commits, pushes and deployments remain unchanged.

## A. Evidence-based current UI/UX audit

### A1. What actually renders and initializes

- Entry is `src/templates/logistics/parcel_form.html`, inherited from the shared Phoenix dashboard. It also serves Parcel edit and tracking-update contexts; a new entry layout must not accidentally change those modes. The four numbered entry panels are one POST form, not four server pages (`src/apps/logistics/views.py:344`, `src/apps/logistics/views.py:387`, `src/templates/logistics/parcel_form.html:22`).
- The shell selects `theme.min.css` / `theme-rtl.min.css` and the matching **compiled** `user.min.css` / `user-rtl.min.css`, loads Nunito Sans, and adds Logistics mobile assets only for LOGISTICS. Do not assume editing `user.css` changes the loaded bundle. `parcel-wizard.css` loads inside the page's content block (`src/templates/inheritance/dashboard_parent.html:43`, `src/templates/inheritance/dashboard_parent.html:65`, `src/templates/logistics/parcel_form.html:4`).
- Page scripts execute before Bootstrap/Choices at the bottom of the parent. `logistics-workflows.js` initializes route behavior immediately and enhances selects on DOMContentLoaded; `parcel-wizard.js` changes panel visibility immediately. Preserve this dependency distinction and native select behavior while vendors load (`src/templates/logistics/includes/scripts.html:1`, `src/templates/logistics/parcel_form.html:161`, `src/templates/inheritance/dashboard_parent.html:439`, `src/static/assets/js/logistics-workflows.js:60`).
- Actual reusable field components are `logistics/includes/form_field.html`, `form_errors.html`, `client_fields.html`, `client_modal.html` and `route_location_fields.html`. They already supply labels, required markers, field errors, hidden values, CSRF and separate modal markup. Use these contracts before introducing another parallel field renderer. Django's installed BoundField code also supplies automatic ARIA attributes; a custom include alone does not establish that rendered inputs lack `aria-invalid` or `aria-describedby`.

### A2. Findings, strengths and redesign response

P1 = task completion/safety; P2 = repeated-use/accessibility friction; P3 = polish. “Risk” is a source-based inference awaiting browser evidence.

| ID / priority | Current evidence and implication | Redesign requirement / original finding |
| --- | --- | --- |
| UX01 / P2 | A four-panel wizard hides submit actions until Review. The route and optional-details steps precede review even for a minimal parcel. Direct Review navigation can be faster after valid inputs. `src/templates/logistics/parcel_form.html:30`; `src/static/assets/js/parcel-wizard.js:79`; `src/static/assets/js/parcel-wizard.js:163`. | One form, no stepper/empty Details transition; review and Save stay connected. F09. |
| UX02 / P2 | Header `mb-5`, form `mb-9`, card body/footer and repeated explanatory paragraphs add vertical structure. Phoenix defines spacing 5=2rem and 9=4rem; this is confirmed class usage, not a measured whitespace defect. `src/templates/logistics/parcel_form.html:14`; `src/templates/logistics/parcel_form.html:22`; `design_references/phoenix/src/scss/theme/_variables.scss:14`. | Reduce page-specific spacing, use thin section separators and short helper text; avoid nested cards. F09/F10. |
| UX03 / P2 | Optional fields require Details → Additional details → six tabs. Sender prefill is inside its tab. Error handling must reveal the panel, disclosure and tab. `src/templates/logistics/parcel_form.html:75`; `src/static/assets/js/parcel-wizard.js:103`. | One-level independent disclosures, no containing “Additional details” disclosure or inner tabs. F14/F15. |
| UX04 / P1 | The selector says Client and sender/recipient are elsewhere; continuation describes an empty recipient as “Client recipient,” although labels use stored snapshots only. `src/apps/logistics/forms.py:620`; `src/templates/logistics/parcel_registration.html:32`; `src/apps/logistics/shipping_labels.py:42`. | Billing Client, Sender and Recipient labeled separately; honest “Not supplied” states and explicit copy source/target. F08/F15. |
| UX05 / P2 | Client queryset loads every tenant Client, including inactive ones. Choices searches locally; only eight non-facility results are shown by its configured search result limit. `src/apps/logistics/forms.py:634`; `src/static/assets/js/logistics-workflows.js:60`. | Scoped paginated search for scale; selected identity pinned; inactive status explicit, eligibility unchanged pending policy. F16. |
| UX06 / P1 | Add Client correctly uses a separate form/fragment endpoint and preserves the parcel DOM. Six fields are required. The handler disables creation while pending but displays a generic error and re-enables after uncertainty; there is no verified durable create replay contract. `src/templates/logistics/includes/client_modal.html:4`; `src/apps/crm/forms.py:494`; `src/static/assets/js/logistics-workflows.js:234`; `src/apps/crm/views.py:1305`. | Retain independent save/draft preservation. Show field errors or an uncertain-result recovery state, not automatic duplicate creation. F03/F08. |
| UX07 / P2 | Existing sender prefill is explicit, fills empty values only, and leaves Client independent. It applies immediately without a separate source preview; no prior-Parcel/recipient reuse control is rendered. `src/templates/logistics/parcel_form.html:99`; `src/static/assets/js/logistics-workflows.js:191`. | Keep copy-empty behavior; add preview/apply/edit with distinct party roles and scoped sources. F14/F15. |
| UX08 / P1 | Mode comes from configured modes; origin defaults from work site. Destination facility can be chosen before country and can set country. Native/select-enhanced option refresh and pageshow restoration are already handled. `src/apps/logistics/forms.py:487`; `src/apps/logistics/location_forms.py:96`; `src/static/assets/js/logistics-workflows.js:109`. | Preserve these useful behaviors; show dependency changes and work-site constraints before save. F06. |
| UX09 / P2 | Mode/country changes rebuild choices; invalid current options can clear. Sea fields are hidden and disabled outside SEA, retaining browser text but omitting it from POST. `src/static/assets/js/logistics-workflows.js:90`; `src/static/assets/js/logistics-workflows.js:147`. | Explain cleared/omitted values, preserve an opportunity to restore, and distinguish fresh-entry omission from historical edit preservation. F14. |
| UX10 / P1 | Both hub actions receive based on server-side current hub context. Button text remains generic; explicit custody explanation appears in Review. `src/templates/logistics/parcel_form.html:125`; `src/templates/logistics/parcel_form.html:150`; `src/apps/logistics/views.py:406`. | Put custody meaning in work context, inline review and explicit save label. Preserve the two-event atomic service. F04. |
| UX11 / P1 | Entry view can render before a current operating-site failure is discovered by the service. It generates a key but has no parcel-specific pending/unknown-result UI. `src/apps/logistics/views.py:390`; `src/apps/logistics/views.py:429`; `src/apps/logistics/parcel_services.py:162`. | Readiness first, authoritative save checks retained, stable key and explicit uncertain-result handling. F06/F17. |
| UX12 / P2 | Review safely uses textContent and displays supplied fields, but builds a bordered group per prior panel and shows empty optional-group text. Focus moves to panel headings. `src/static/assets/js/parcel-wizard.js:38`; `src/static/assets/js/parcel-wizard.js:100`. | Keep safe text rendering; replace repeated groups with a concise definition list and edit targets. No new empty optional review block. F09/F14. |
| UX13 / P2 | Field/error includes provide labels, errors and a focusable summary. Wizard browser errors link to fields; generic form errors are plain list text. Enhanced-field focus targets the Choices wrapper; its effective keyboard focus needs rendered verification. `src/templates/logistics/includes/form_field.html:7`; `src/templates/logistics/includes/form_errors.html:1`; `src/static/assets/js/parcel-wizard.js:127`. | Unified linked error summary, field descriptions, focus the real input/combobox, expand errors without adding a step. |
| UX14 / P2 | An error handler explicitly requests smooth scrolling without checking reduced-motion preference. Native/Choices ARIA, modal focus return and tab keyboard behavior have not been observed in this audit. `src/static/assets/js/logistics-workflows.js:55`; `src/static/assets/js/logistics-workflows.js:231`. | Respect reduced motion; specify focus return and keyboard behavior rather than assuming component compliance. |
| UX15 / P2 | Below 991.98px mobile CSS supplies 44px minimum targets, 16px input text, wrapping Choices labels, maximum 240px dropdown lists and a sticky action area. Wizard CSS reduces circle/label size below 576px. These are rules, not proof of actual touch/overflow passes. `src/static/assets/css/logistics-mobile.css:2`; `src/static/assets/css/logistics-mobile.css:32`; `src/static/assets/css/parcel-wizard.css:67`. | Retain target sizes and wrapping; simplify structure instead of shrinking text. Scope new layout locally and avoid a keyboard-covering mobile footer. |
| UX16 / P2 | Detail presents multiple peer actions; Continue Registration is primary. No direct Register Next action appears in its action row. In continuation, register-another is within Charges; labels appear in Summary. `src/templates/logistics/parcel_detail.html:29`; `src/templates/logistics/parcel_registration.html:47`; `src/templates/logistics/parcel_registration.html:147`. | Saved result promotes Next, label actions and optional processing without visiting billing first. F10/F11. |
| UX17 / P1 | The shared work-location control is already above content. Its POST always redirects to Scan Parcel, accepting no return target. A site switch during drafting risks interruption. `src/templates/logistics/includes/work_location.html:1`; `src/apps/logistics/location_access_views.py:108`. | One site selector, explicit dirty-draft handling and a fixed authorized registration return context; preserve default Scan return for other callers. F06/F11/F17. |
| UX18 / P2 | Continued processing is another five-panel wizard, with repeated saved-Parcel content, large `p-3` action tiles and per-Invoice/per-Shipment bordered groups. Its dedicated outstanding-task alert is commented out. `src/templates/logistics/parcel_registration.html:13`; `src/templates/logistics/parcel_registration.html:41`; `src/templates/logistics/parcel_registration.html:114`. | Replace sequential progress with compact independent task sections and persistent saved identity. F10/F13. |
| UX19 / P1 | JavaScript blocks later panels until the session payment decision is complete. POST assign/defer does not use that as authority. `src/static/assets/js/parcel-wizard.js:163`; `src/apps/logistics/registration_views.py:140`; `src/apps/logistics/registration_views.py:362`. | Navigate freely among authorized tasks; derive unresolved work from persisted records, not session visits. F12. |
| UX20 / P1 | Candidate Shipments are filtered by route and billed Client then capped at 25, with no mode filter; service checks mode but no endpoint-equality invariant. `src/apps/logistics/registration_views.py:94`; `src/apps/logistics/shipment_services.py:381`. | Mode compatibility before pagination; no invented strict route enforcement. Retain explicit assignment/revision checks. F01/F02. |
| UX21 / P1 | Summary restricts detailed finance; authorized operating staff can still open a complete writable Parcel-only Invoice/receipt form. Balance and clearance come from existing services. `src/templates/logistics/includes/workflow_summary.html:6`; `src/apps/logistics/registration_views.py:297`; `src/apps/logistics/financial_access.py:107`. | Scope before serializing; distinguish restricted overview from explicit authorized receipt entry. No blanket “staff see no finance” assumption. F07/F12. |
| UX22 / P2 | Financial summary tables have a 34rem minimum inside scroll wrappers. Charges/Invoice editors use a separate full-page generic field loop. These create possible horizontal scrolling and repeated navigation; current overflow was not measured. `src/templates/logistics/includes/workflow_summary.html:9`; `src/templates/logistics/billing_form.html:8`. | Compact rows, local overflow where unavoidable, optional editors in context with full-page fallback and distinct POSTs. F10. |
| UX23 / P3 | Entry breadcrumb contains an empty `ol` followed by the populated list. `src/templates/logistics/parcel_form.html:7`. | One semantic breadcrumb list; no decorative duplicate navigation. |
| UX24 / P1 | Existing browser scripts include useful 390/1440 coverage but some still target removed “Save customer receipt” controls. Source tests do not establish current light/dark/tablet/focus behavior. `scripts/logistics_parcel_wizard_browser_check.py:263`; `scripts/logistics_registration_changes_browser_check.py:59`. | Update meaningful scenarios later; no inherited browser-pass claim. F05. |

Existing safeguards to retain include same-form draft preservation, empty-only prefill, escaped review text, native select fallback, explicit work-site context, role/module gates, CSRF, UUID/revision fields, authoritative services and private label exports. F18's historical declared-value currency problem is a data-policy limitation, not something a visual redesign can repair.

## B. Proposed desktop and mobile wireframes

Wireframes show **proposed information hierarchy**, not extra domain records. Brackets represent controls; `>` is a disclosure. Names/locations/amounts are fictional examples. Required markers follow actual configured rules, not a fixed new validation policy.

### B1. Desktop entry — wide available content

```text
Parcels / Register parcel
Register parcel
Active work location: MIA-HUB · Miami    [Change location]
Physical intake: saving records receipt here.     Parcel capacity: available
--------------------------------------------------------------------------------
MAIN FORM (flexible)                             REVIEW (280–320px)
Billing Client *                     [Add Client] Review before saving
[ Search name, company or email              v ] Billing Client   Island Trading
Selected: Jordan Ellis · Island Trading          Package          Books, 1 box
                                                 Route            Miami → Roseau
Package description *                            Mode             Sea
[ Books, 1 box                                ]  Sender           Not supplied
                                                 Recipient        Not supplied
Weight (kg), optional      Reference, optional    Action           Receive at MIA-HUB
[                        ][                    ]  [Edit Client] [Edit route]
                                                 > Review supplied optional values
Route
Transport mode * [Sea v]                          [Register & receive at MIA-HUB]
Origin                           Destination     [Register, receive & process]
[United States v]                [Dominica v]     [Cancel]
[MIA-HUB · Miami v]               [Roseau v]
Origin follows your active work location.

Sender · Not supplied                    [Add / edit] [Use saved details]
Recipient · Not supplied                 [Add / edit] [Use saved details]
--------------------------------------------------------------------------------
> Size and handling          Optional
> Customs and documents      Optional
> Transport references       Optional · Sea
> Internal notes             Optional · Workspace only
```

There is one registration form. Review is a plain aside within it, with a thin separator/subtle background rather than another large card. Optional fieldsets open in the main column and retain their values. Page header and current site are compact; there is no hero area, progress ring, KPI tile row, illustration or numbered wizard.

### B2. Mobile entry —390px reference layout

```text
Parcels / Register parcel
Register parcel
MIA-HUB · Miami                  Change location
Saving records physical receipt at this hub.
------------------------------------------------
Billing Client *                     Add Client
[ Search name, company or email            v ]
Jordan Ellis · Island Trading

Package description *
[ Books, 1 box                               ]
[                                            ]
Weight (kg), optional    Reference, optional
[                    ] [                    ]

Route
Transport mode * [Sea                       v]
Origin country * [United States             v]
Origin facility  [MIA-HUB · Miami            v]
Destination country * [Dominica             v]
Destination facility  [Roseau               v]

> Sender       Not supplied · optional
> Recipient    Not supplied · optional
> Size and handling               Optional
> Customs and documents           Optional
> Transport references            Sea · optional
> Internal notes                  Workspace only
------------------------------------------------
Review before saving
Billing Client   Island Trading
Package          Books, 1 box
Route / mode     Miami → Roseau · Sea
Shipping         Sender/recipient not supplied
Action           Receive at MIA-HUB
Edit Client · Edit package · Edit route

[ Register & receive at MIA-HUB                ]
[ Register, receive & process                 ]
Cancel
```

Review and save controls are **in normal document flow on mobile**, directly adjacent. There is no unconditional floating footer covering content or the software keyboard. This refines Option A's placement without adding a review step. The existing global `.mobile-form-actions` stickiness must not be blindly applied to this new local layout. On desktop the aside may stick below the existing header only when it fits the available height; at zoom/short heights it stays in flow.

At very narrow widths, Weight/Reference also stack. The country/facility controls retain separate identities and labels even when a current origin is displayed read-only; canonical values remain part of the validated form.

### B3. Saved result — desktop and mobile

```text
Registration saved                                 Current state: Received
Received at MIA-HUB · [verified event time]
Tracking  [full saved code, selectable and wrapping]     [Copy tracking code]
Island Trading · Miami → Roseau · Books, 1 box

[Register Next Parcel]  [Print label]  [Preview label]  [Download PDF]
Continue processing · View parcel detail

For next parcels: [ ] Keep Billing Client   [ ] Keep destination & mode
Origin is checked again. Sender/recipient and parcel measurements will be cleared.

Remaining work
Charges: Not recorded / accounting review     Shipment: Unassigned · optional at intake
Movement clearance: Pending review            [only information actor may receive]
```

```text
Registration saved
Current state: Received
MIA-HUB · [verified event time]
Tracking
[full saved code wraps; no ellipsis]   [Copy]
Island Trading
Miami → Roseau · Books, 1 box

[ Register Next Parcel                       ]
[ Print label                                ]
[ Preview label        ] [ Download PDF      ]
Continue processing · View parcel detail

For next parcels
[ ] Keep Billing Client
[ ] Keep destination & mode
Origin checked again; shipping details clear.

Remaining work
Charges not recorded / review
Shipment unassigned · optional at intake
Movement clearance pending
```

“Registration saved” does not mean paid, cleared, shipped or operationally complete. Use actual current status and event evidence. Revisiting an older saved parcel must not state it was just received or create another receipt. Register Next appears only when the actor can register; read-only users retain permitted detail/label navigation.

### B4. Optional processing — one page, independent sections

```text
Parcels / [saved parcel] / Process parcel
Process parcel                          [Register Next Parcel] [Print label]
[tracking] · Billing Client · route · actual state
Saved records remain saved when another action fails.
Charges · Invoices & receipts · Shipment · History     [plain section links]
--------------------------------------------------------------------------------
Charges                                            Shipment
Description      Qty    Unit price    Saved total    [Search compatible shipments]
Freight          1      USD 20.00     USD 20.00      Ref · route · mode · state
[Add charge]                                        [Assign to selected shipment]
  Service/custom selector and compact form           Browse all · Create Shipment*
                                                     *Owner/admin only
Invoices & receipts
Draft INV-[id] · server-presented amount/status       Clearance
[Create / append Invoice] [Issue Invoice]             Pending / approved by evidence
Issued INV-[id] · Paid / Partial / Unpaid / Review     No invented progress score
[Record payment received] [Open Invoice]
Optional authorized receipt editor opens here.

History  > View saved events and audit records
```

Mobile uses the same source order in one column: saved identity/actions, safe task summary, Charges, Invoices & receipts, Shipment, History. Do not use CSS visual reordering that disagrees with keyboard order. Actors without a finance area see the safe clearance message and permitted Shipment content rather than empty finance controls. Each area has its own compact heading/separator; no dashboard grid of oversized action cards.

## C. Detailed screen sections and field placement

### C1. Visual system and responsive contract

| Element | Specification |
| --- | --- |
| Shell | Keep current Motionmate dashboard/navigation/theme controls and Phoenix 1.23.0. Do not import Silicon marketing CSS or introduce another framework. |
| Content width | Use available shell width, capped around 1200px as a design target. Enable side-by-side review only when available content is at least 1000px; typical 1440px viewport with navigation should be evaluated. Below that, one column. This is not a claim about current shell measurements. |
| Grid | Main form grows; review 280–320px; 24px gutter. Medium widths can pair related fields. Under roughly 700px available content, stack route controls and party editors; under 360px, all optional paired controls stack. Avoid viewport-only assumptions with an open sidebar or200% zoom. |
| Surfaces | One body surface, thin section separators, modest review emphasis; no card around each fieldset. Borders/separators use existing theme tokens. Avoid gradients, decorative counters, floating action bubbles and ornamental icons. |
| Density | 4px label-to-control, 8px helper separation, 12–16px field gaps, 24px major-section gap as targets. Use verified Phoenix spacing tokens/utilities; current theme spacing 5 is 32px and 9 is 64px at a 16px root. Do not globally reduce theme spacing. |
| Type | Existing Nunito Sans/font inheritance. Use Phoenix heading/body utilities; maintain readable body/help text, and 16px form text on touch layouts. Compactness comes from structure, not tiny text. |
| Controls | At least 44px touch targets; persistent visible labels above controls. No placeholder-only or floating-label dependency. Required markers follow server field requirements; optional groups are labeled once without drowning the form in repeated explanations. |
| Color | Existing primary for one main action; Phoenix secondary/outline controls for related actions; success for confirmed save; warning/review for incomplete evidence; danger for errors. Include text, not color alone. Use body/bg/border/secondary/focus tokens for both themes. |
| Actions | Same-size related controls where practical; side by side only when labels fit without truncation, stacked otherwise. Long hub names wrap. No split-button hiding the main save meaning. |
| RTL | Logical spacing, wrapping and semantic order; route text remains origin→destination semantically without relying on arrow direction alone. Preserve existing theme asset order and RTL selection. |

Reference patterns inspected read-only: Phoenix `modules/components/accordion.pug` for flat disclosed sections, `modal.pug` for client/copy dialogs, `forms/validation.pug` for labeled fields/feedback, and theme variables for spacing/tokens. Reuse application field/error includes first; configure independent disclosure behavior rather than the reference example's mutually exclusive `data-bs-parent`. No reference demo data/assets are copied.

### C2. Entry sections and fields

The existing field names remain unchanged. R=required, O=optional, C=conditional, S=server-controlled. Exact lengths/precision/legacy exceptions remain as documented in the current audit and enforced by current forms/models.

| Order / section | Field placement and labels | Behavior |
| --- | --- | --- |
| 0. Context/readiness | Existing active work-location control once, page title/breadcrumb, compact site/custody/readiness line | Do not add a second competing site selector inside the Parcel form. Readiness is read-only and does not reserve quota. Block only the action actually unavailable. |
| 1. Billing Client | `client` R, full-width search; Add Client beside label on wide layouts and reachable beside search on mobile; selected name/company/email below | Explain “Linked customer/account for this parcel and its invoices.” No automatic sender/recipient copy. Preserve existing selection when search query changes. |
| 2. Package | `package_description` R full width; `weight_kg` O and `internal_reference` O on the next row | Description starts with 2 rows and grows as needed; preserve max 1000/line breaks. Weight >= 0 with existing precision. Reference max 100. Registration still creates operational quantity1, not a new count control. |
| 3. Route | `mode_of_transport` C; origin country then facility; destination country then facility | Required country/mode markers follow configuration. Current origin defaults and work-site rules remain. Destination facility can be selected before country. Keep country-only routing without making a facility universally required. |
| 4. Sender | Summary row and one-level editor: `sender_name`, `sender_contact`, address lines 1/2, city, region, postal code, country, `sender_tax_id`, legacy `sender_address` | All O. Name/contact first, address on following rows. Country uses all-ISO party choices, not the route subset. Use saved details is secondary. No field appears twice. |
| 5. Recipient | Same layout without tax ID: `recipient_name`, `recipient_contact`, structured address, country, legacy `recipient_address` | All O. Never infer from Billing Client or destination. Separate editing and copy source from Sender. |
| 6. Size and handling | `length_cm`, `width_cm`, `height_cm`; then `volume_m3` and legacy `dimensions`; then `fragile_goods`, `biodegradable_goods`, `expiry_date` | All O; existing dimension minimums and nonnegative volume. No automatic volume calculation/all-three rule, expiry dependency or copied handling flags. |
| 7. Customs/documents | `hs_code`, `marks_numbers`; `declared_value`, `incoterms`; applicable `master_bl_no`, `house_bl_no`, `issue_date` | All O. Value label includes current Business currency for new entry; it is not freight. No invented HS/Incoterms catalogue or new customs requirement. |
| 8. Transport refs | `origin_reference_code`, `destination_reference_code`; `vessel_name`, `voyage_no`, `imo_no`; loading/discharge codes | All O; existing mode/territory applicability and configured vessel suggestions. Explain route reference versus `port_load_unlocode` / `port_discharge_unlocode`; do not write one into the other automatically. |
| 9. Internal notes | `internal_notes`, one flat disclosure, full-width textarea | O, max 2000; “Workspace only.” Never in public tracking/copy defaults/label assumptions. |
| 10. Review/actions | Live critical-value summary, optional supplied-value review, explicit register buttons and Cancel | S derived text; not an independent editable payload. Keep original hidden operation/CSRF fields in the form. |

Sender/Recipient summary toggles open their editors directly. Other disclosures are independent: opening Transport does not close Sender or hide its error. Legacy address controls are visible under a simple labeled legacy subsection when editing a populated value, not another tab hierarchy. Do not silently convert existing legacy text to structured address fields. Every field remains accessible through the native/no-JavaScript form as well as enhanced controls.

Keep decimal keyboard hints and existing numeric bounds for measurements/value, native date inputs for dates, email/tel controls for the Client modal, and text controls for codes/references that may contain leading zeros or letters. Party contact remains a generic contact field; do not add phone-only validation. Browser autofill must not silently conflate Sender and Recipient or create a repeat-retention preference.

Review always names Billing Client, package, origin/destination, mode, sender/recipient presence and the intended custody action. Critical identity/route values are not ellipsized into ambiguity. Long descriptions may use an explicit “Show full description” control; supplied optional values have one compact definition-list disclosure with Edit links to the matching controls. Do not duplicate all empty fields or build one card per prior step.

### C3. Client and copy dialog layouts

Client creation retains the existing six required fields: first/last name paired where space permits, company full width, email/phone paired, street address full width. Do not add fake placeholders to satisfy identity requirements. Duplicate suggestions appear above the editable fields with Select existing controls; they never auto-merge or prove identity. Company/Individual policy and geographic Client inputs remain unresolved in H.

Use the existing Bootstrap modal pattern: constrained width on desktop, full available width on narrow screens, scrollable body and always-reachable heading/close/actions. No page-scroll plus multiple inner-scroll trap. For reuse, open one separate dialog **after closing any other dialog**: source picker → preview/diff within that dialog, not stacked modals. Apply is a draft action, not a database write.

## D. Interaction specification

### D1. Focus and keyboard order

1. On a fresh empty entry, focus Client search after normal page navigation only if that does not override an error, deep-linked field, assistive navigation or user interaction. On a retained Client/route draft, focus package description.
2. In document order: Billing Client search, Add Client, package description, optional visible Weight/Reference, mode, origin country/facility where editable, destination country/facility, Sender controls, Recipient controls, remaining disclosure summaries/expanded fields, review Edit links, primary Save, optional Save & process, Cancel. Read-only context is readable without introducing fake focusable controls. Skip genuinely disabled controls; never use positive tabindex.
3. Search uses Arrow keys to move results, Enter to select, Escape to close; Tab continues naturally and does not select an unconfirmed result. Native selects retain platform behavior. The actual combobox/search input receives focus, not an arbitrary wrapper.
4. Enter in normal single-line entry fields does not implicitly register; Enter on a focused save button intentionally submits, while textarea newlines, IME composition and component keyboard actions are preserved. Do not globally intercept every Enter or trap Tab.
5. Error-summary links reveal the fieldset and focus the native/Choices input. Review Edit links do the same without clearing anything. Opening a disclosure does not move focus away from its trigger unless the operator explicitly selected Edit/Add.
6. Client modal opens at first relevant empty field. Invalid save focuses the modal error summary/first invalid field. Confirmed creation selects Client, closes modal and returns to the next logical parcel field. Cancel/Escape returns to Add Client without changing the parcel. Copy dialog Apply returns to that party's summary/editor; Cancel returns to its opener.
7. Confirmed parcel save focuses the saved-result heading (`tabindex=-1`) once and announces success. It does not automatically focus/activate Print or Register Next. A later independent task save announces its own outcome and keeps focus in that area.

Provide an optional **Skip optional details to review** link after the essential route fields. It reveals/focuses the review heading in this same page without submitting, changing values or creating a mandatory navigation step. Keyboard users can review the critical context and reach Save without tabbing through every unused disclosure.

### D2. Billing Client search/create states

| State/action | Required UI and behavior | Authority/boundary |
| --- | --- | --- |
| Empty | Search name/company/email; explicit Add Client if permitted; no assumed selected identity | Same tenant parcel-selection access as today; CRM read is not newly required merely to select Billing Client. |
| Query pending | Brief “Searching…” status after debounce; selected Client remains pinned; keep input focus | Target debounce 250ms; ignore/cancel older responses. No unsaved parcel mutation. |
| Results | Minimal name/company/email rows; inactive marker where applicable; keyboard/touch selection; “More results” pagination | Proposed target<=20/page for server search. This is backend read work; current local search can remain an interim stage without claiming scale improvement. |
| No results / no Clients | “No Clients match” / “No Clients yet”; Add Client only if authorized; otherwise explain authorized colleague/setup needed | Do not expose global Clients, fabricate a placeholder Client or broaden creation role. |
| Search failure | Inline Retry search; retain selected identity and all draft fields; distinguish failed lookup from no matches | Do not submit a stale/free-text name as an ID. Server independently validates selected ID. |
| Open/create | Preserve parcel DOM; existing `workflow=parcel`, `new_client-` prefix, fields, CSRF and separate endpoint | Client capacity checked for creating, not for choosing an existing Client. No Parcel/Invoice side effect. |
| Client validation error | Keep modal open with field errors and entered values; parcel unchanged | Existing HTTP 400 fragment contract retained in full-page/fragment adapters. |
| Confirmed Client saved | Select result; show “Client saved and selected”; return focus; keep it even if parcel later fails | Existing HTTP 201 fragment contract; Client is already independently committed. |
| Client save uncertain | “Client save could not be confirmed. Check existing results before creating again.” Keep draft and recovery search | Do not auto-retry creation. Durable exact-once Client behavior needs separately approved persistence; a spinner/disabled button is insufficient. |

Inactive Clients remain selectable under current policy with an honest label; approval is required before excluding or reactivating them. Phone-based duplicate suggestions are tenant-scoped and reveal only information authorized for that workflow. A potential match never causes an automatic reassignment/merge.

### D3. Route and dropdown behavior

- **Origin:** display current site clearly and default country/facility as today. Staff cannot use destination selection to operate remotely. If origin is constrained to one value, show a readable explanation and preserve canonical server validation; do not invent an alternate hidden authority value. Owners/admins retain existing policy and pre-rollout compatibility, without implying hub receipt when no authorized hub exists.
- **Destination:** keep facility-first selection across active tenant facilities. Selecting a facility sets its country and announces the change. Selecting country first filters facilities. “No company facility” remains a valid option when country-only routing is allowed; missing facilities do not trigger fake facility creation or grants.
- **Mode:** use current configured SEA/AIR/ROAD/RAIL choices and sole-mode default. Keep historical saved-mode exceptions in edit forms. If none configured, retain current Unknown behavior and separately explain configuration that actually prevents a valid route; do not require a newly invented mode globally.
- **Dependent changes:** rebuild only affected options, retain valid values, and identify any option removed by a changed country/mode. Announce “Destination facility cleared because it is outside the selected country” rather than silently blanking it. Keep an opportunity to undo/reselect; do not automatically select the first remaining facility.
- **Sea references:** new-entry controls hide/disable when not applicable, as current submission behavior requires; retain browser values for switching back. If nonempty values will be omitted, show that fact in the transport summary and inline review. Historical edit values are preserved by existing form/service rules; no blanket new-registration reset applied to edits.
- **Searchability:** use current Choices/native controls, visible labels and clear empty states; full control names remain available with long names. Facility lists are local authoritative options, not fuzzy geocoding. Port/airport references remain from the current offline verified list, filtered by territory/mode.
- **No-JavaScript/delayed vendor:** all form fields/errors remain reachable. Dependent-option refresh, where required without JavaScript, must use a read-only form refresh path and keep data/key; it must not register just to populate options. This fallback is future backend presentation work, not verified current behavior.

### D4. Sender/Recipient reuse and overwrite rules

1. The operator chooses the target party first. Sender may explicitly use Billing Client details or a readable same-Client Parcel's Sender; Recipient may explicitly use a readable same-Client Parcel's Recipient. No ambiguous “same as customer” switch. A new recipient source must not invent a linked recipient CRM record.
2. Fetch from the resolved Business and current source-read policy. Client address prefill retains CRM read gating. Prior-Parcel reuse requires new scoped read support; it is not currently an existing button. Do not show sources after permission revocation or serialize inaccessible snapshots.
3. Preview source type/identity, target role and exact proposed fields. Default action **Fill empty fields**; identify which supplied fields will be skipped. **Replace selected fields** requires deliberate field selection and visible old/new values, not a second generic confirmation modal.
4. Apply changes ordinary draft fields only. Show “Copied from Billing Client” or “Copied from saved Parcel Sender/Recipient” and an Edit control. Display current geographic values, including a Client default country; do not silently substitute the parcel route country.
5. If Billing Client changes, preserve independent typed snapshots; mark copied-source context for review and let the operator keep/edit/clear. Do not silently copy new Client data over existing parties. Optional parties remain optional.
6. When saving, submit actual accepted snapshot values through the existing form. No live synchronization or new party FK, no Client update and no history rewrite. Invalid historical data copied onto a new parcel must satisfy current new-entry validation.

### D5. Validation, review, site changes and feedback

Validate on explicit save and useful field completion, not every keystroke. Client-side validity improves feedback; Django/forms/domain services remain final authority. One error summary above the form links to actual fields; field errors retain labels/help IDs and ARIA associations through enhancement. Expand all fieldsets containing errors. Nonfield/domain errors remain visible in the summary and beside the relevant action when a safe mapping exists; do not invent a specific field error when the service only reports a general conflict.

The summary uses current field values, safe text rendering and no client-side settlement calculation. Update critical text without announcing the entire summary on every keystroke. Show concise changes on blur/selection; field-level error messages use appropriate alert timing. Missing optional parties/value/weight are not validation failures.

Before typing, show ready/blocked/unable-to-verify using a proposed read-only readiness projection. Reuse existing permission/site and capacity semantics; `monthly_usage(refresh=True)` rereads evidence and is not a write. Client limits affect Add Client; Invoice/Shipment limits affect those later actions. Existing login/module/role denials still apply. Monitoring budgets and legacy unlimited allowances must not become new hard blocks.

For a dirty draft, Change location must explain that current origin/custody will need review. Do not submit the Parcel form as part of changing site. A future fixed registration return/response context may reuse the existing work-location POST/service and keep the live draft during an enhanced request; existing direct callers still return to Scan. Without that support/native navigation, explicitly warn of draft loss and do not claim that an in-memory draft survives a full redirect. A successful site change refreshes origin/readiness and requires review; never silently downgrade hub receipt or keep the old location as authority.

### D6. Parcel save and retry states

| State | UI specification | Operation rule |
| --- | --- | --- |
| Editing | Current values/review visible; exactly one primary registration action | Stable registration UUID; editing/display changes and Client save do not regenerate it. |
| Blocked | Safe reason and permitted recovery; Save unavailable; entered values remain in place when still authorized | No bypass via hidden controls; server rechecks. |
| Saving | Button “Registering…” with progress indicator and `aria-busy` on the relevant form; disable duplicate save actions | Preserve submission snapshot/key and chosen redirect action. Do not disable canonical fields before serializing them, accidentally dropping them from POST. |
| Validation rejected | “Parcel was not saved. Correct the highlighted fields.” Summary/fields visible; review still available | Keep submitted payload/key; do not clear selected Client or optional fields. Domain permission errors may remain HTTP 403 rather than a successful-form response. |
| Context/permission/quota changed | Explain current safe reason; offer recheck/review where authorized, never weaken denial | Readiness was advisory. Final Business/membership/site/quota checks and existing locks apply; no partial Parcel/events. |
| Outcome uncertain | “Registration could not be confirmed. Check or retry this registration before starting another parcel.” Keep attempted payload/key; Next unavailable | Retry exact operation only when still authorized; do not auto-generate a new UUID, edit an uncertain payload or blindly submit another parcel. No offline queue/closed-tab recovery promise. |
| Confirmed saved | Navigate to saved result or requested processing route via POST/redirect/GET | Server returns actual saved identity/events; no new money/Shipment operation implied. |

At a hub the primary label is **Register & receive at [hub code]**, with full site name readable in review. Outside hub it is **Register Parcel**. The secondary action is **Register, receive & process** or **Register & process**, retaining `continue_registration=1` semantics. Keep `save_and_receive`, CSRF, field names and retry service behavior compatible. A proposed reviewed-context comparison is backend guard work, not permission conferred by the summary.

An identical authorized retry must reuse the existing registration result, including stable hub receipt history and no rewind after later movement. Starting a genuinely new parcel uses a fresh key only after the preceding result is known. A fresh key still cannot prove the physical parcel is different; no automatic duplicate-detection claim is made.

## E. Saved result, Register Next and continued processing

### E1. Saved-result content and actions

Use a focused top section on the existing Parcel detail route, and reuse that identity header on the continuation route. Do not invent a new Parcel-completion model or hide existing detail/history. Separate the action outcome from current state when revisiting an older parcel.

| Content/action | Specification |
| --- | --- |
| Outcome | “Registration saved.” If evidence supports it: “Received at [hub] · [event time].” Actual current status is separate; no “All done” or “Registration 100% complete” badge. |
| Identity | Full selectable tracking code with accessible Copy tracking code; readable Billing Client, package and route/mode. Copy success/failure is announced; manual selection remains possible. |
| Register Next Parcel | Primary, only when authorized to register. Opens a fresh form/key, checks context/capacity and applies only explicit retained preferences. Never a save/update of the previous record. |
| Print / Preview / Download | Existing scoped routes; actions available without visiting Charges. Print opens appropriate preview/print behavior only by deliberate activation; generation is not evidence of hardware printing. A render HTTP 422 leaves the parcel saved and offers permitted Edit shipping details/Retry label. |
| Continue processing | Secondary link to existing `logistics_parcel_registration`; saved identity and unfinished work remain visible. Not the primary required exit from intake. |
| View detail / history | Existing routes and saved events; detail remains available during repeat registration through a clearly labeled last-saved link. Do not expose bearer codes in analytics/debug/return tokens. |

### E2. Explicit opt-in retention

Offer two initially unchecked preferences in the saved result: **Keep Billing Client for next parcels** and **Keep destination & mode for next parcels**. They belong to the next-form navigation controls, not another registration POST. Setting them does not mutate the parcel or persist a payment/completion flag. First-cycle setup adds these optional choices; estimated repeat-action counts exclude that one-time setup.

The Next action carries a short-lived scoped source/context and allowlisted keep flags through ordinary GET/POST-redirect navigation, using validated IDs/mode rather than shipping/financial text. A signed context is not an authorization grant; every source/choice is revalidated for actor/Business/current configuration. Add backend support before claiming this behavior exists.

On the new form, show “Retained: Billing Client, destination & mode” with Reset/End repeat controls. Changing retained values affects the next preference only after explicit retention remains selected; the operator must see what the next form will keep. Do not infer retention from browser autocomplete or the previous user's session.

Always reset package description, internal reference, weight/dimensions/volume, declared value, shipping parties, document refs/dates, handling flags, notes, payment/Invoice/charge choices, Shipment association, tracking/status/event fields and all operation identities. Origin is recalculated from current site. Reusing a party requires its separate preview/apply action for that parcel. Keep/Reset preferences never clear the actual existing saved parcel.

### E3. Persisted task summary

Show short rows using `resolve_parcel_workflow` and shared authoritative Invoice presentation after scope checks:

| Area | Example state / rule |
| --- | --- |
| Registration/custody | Saved REGISTERED and, when present, RECEIVED/history evidence. Receipt at a hub must not be inferred just from selecting origin. |
| Charges | Recorded, pending invoicing, or “Charges not recorded / accounting review.” No obligations does not mean zero debt or clearance. |
| Invoices | Active related draft/issued/cancelled/review evidence. Mark issued separately from paid and sent-by-email. |
| Customer payment | Existing unpaid/partial/paid/no-payment-required/review projection; shared Invoice balances in full where authorized; cancellation allocations/refunds separate. |
| Movement clearance | Current action-specific settlement/valid credit/evidence result; pending/review or authorized clearance. Credit does not claim a payment receipt. |
| Shipment | Actual association or “Unassigned — optional at intake.” A chosen suggestion, browsing context or Assign later is not a saved attachment. |
| Label details | Honest optional snapshot presence and known render failure. No “Printed” or fully-addressed claim without the relevant evidence. |

Restricted actors receive safe review/clearance wording, not hidden amounts. Refresh after each successful mutation and when returning to the page. Session navigation choices may preserve harmless focus for compatibility, but must not declare tasks complete or force an unrelated Payment visit. No durable “deferred,” task owner or due date is invented.

### E4. Optional independent processing areas

Replace the five-step continuation navigation with plain section links and one-level sections. Preserve old anchor IDs (`registration-parcel`, `registration-billing`, `registration-payment`, `registration-shipment`, `registration-summary`) as appropriate section/identity targets so existing deep links continue to resolve. Do not keep wizard code that re-hides sections or restores the session gate.

1. **Charges.** A compact saved-charge list, then Add Charge opens one reusable editor in the same area. Existing service/custom choice, description, quantity, price, occurrence and UUID remain. Suggested service price is clearly a suggestion; changing service must not silently overwrite an operator's dirty price override. Quantity is billing quantity, separate from Parcel quantity. Save Charge remains one independent operation; server snapshot totals populate the saved row.
2. **Invoices.** Select current/eligible same-Client charges and either a new draft or authorized existing draft using existing validation. Keep Create/append Invoice distinct from Issue Invoice. Protected lines, active bindings, saved currency/tax and existing reissue/cancellation rules remain. Review the saved draft before its separate issue action. Email uses the existing explicit accounting-authorized action; no automatic email, collection or lifecycle assumption.
3. **Payment receipts.** Record payment received opens the related authorized issued Invoice form. Opening it is an explicit record intent; retain current `action=payment`/`decision=record` payload compatibility rather than a required visit/skip step. Use actual amount/currency/method/reference/UUID and existing conditional allocation fields. Preserve current defaults and CASH/BANK_TRANSFER/ONLINE manual-receipt policy; do not market it as verified external collection. Other areas remain navigable without submitting a payment decision.
4. **Shipment.** Compact searchable rows/picker showing reference, route, mode, state and explicit Assign. Filter permitted state/site/role/modules, billed Client, known-mode compatibility and conservative route suggestions before pagination. Unknown/ambiguous historical modes need review, not invented normalization or new automatic grants. Owners/admins alone see Create Shipment; operating staff retain permitted assignment, not management rights. Final assignment service/revision/key is authoritative.
5. **History.** Retain saved events and audit information in a simple disclosure/link; do not delete, rewrite, merge or replace immutable records to make the UI look cleaner.

Each operation uses its existing service boundary: `add_charge`, `invoice_charges`, `change_invoice_status`, `record_invoice_payment`, `assign_parcel`; new Shipment creation+assignment retains its existing atomic unit. No Save Everything button or nested aggregate form. If charge succeeds and Invoice fails, say **Charge saved; Invoice was not created** and preserve the remaining form, without replaying the charge. If a receipt fails, the earlier issued Invoice remains visibly saved. Disable only the pending mutation's controls, preserve other drafts and refresh authoritative scoped fragments after a result. Full-page POST/redirect behavior stays available as a fallback.

### E5. Financial/location visibility and return navigation

| Actor/state | Entry and result | Optional processing |
| --- | --- | --- |
| Owner/admin | Existing role/module authority and current-site/custody rules; legacy compatibility retained | Existing broader accounting and Shipment management within current guards; related-record validation still applies. |
| Operating staff | Registration requires approved current operating site; origin current site; no destination-derived grant | Authorized Parcel charges and complete writable Parcel-only Invoices/receipts. Restricted overview can coexist with an explicitly authorized receipt form; do not expose every Invoice by default. Assignment allowed where current service permits; no new Shipment management. |
| Read-only location staff | Scoped read/result/label only where existing guards allow; no Register Next/save | Safe clearance/review projection; no financial/assignment mutations. |
| Unassigned/revoked actor | Explain permitted recovery or preserve existing deny/404 behavior | Never return stale snapshots, amounts or actions from cached prior authority. |
| Accountant/viewer | Existing parcel read scope, role and module rules; do not equate accounting scope with operational wide access | Existing financial read/write capability where applicable; no new parcel creation/Shipment management because processing is on one page. |

Server scope must precede HTML/JSON/fragment generation. Amounts or restricted identities must not be serialized and hidden with CSS. Do not change subscription/read-only behavior to get someone through a blocked screen.

Use a fixed named-route + scoped Parcel + allowlisted section return contract through edit, labels, Shipment browse/filter/pagination/detail/assignment/create and permitted site changes. Preserve existing `?client=`, `?registration=1`, `registration_parcel`, payment selection and old direct-route defaults. No arbitrary external return URL. An entry link from Shipment can retain a proposed later target, but must never attach cargo automatically during registration. Strict route equality remains a business decision in H; a filtered picker alone cannot establish a backend invariant.

## F. Before/after and prioritized implementation stages

### F1. Comparison

| Area | Current source | Option A specification |
| --- | --- | --- |
| Entry navigation | Four panels plus separate continuation | One essential form, optional flat disclosures, inline review, saved result |
| Optional depth | Step + disclosure + six tabs | One-level fieldsets with direct error/Edit reveal |
| Review | Rebuilt bordered group per prior panel | Persistent concise critical-value list and optional supplied-value detail |
| Parties | Client selection apart from optional Sender/Recipient; misleading empty recipient fallback | Explicit independent Billing Client/Sender/Recipient with honest empties |
| Lookup | Full tenant select/local search; separate Client modal | Scaled scoped lookup plus preserved modal/selected identity and uncertainty handling |
| Custody | Generic submit labels; explanation on Review | Context + review + explicit Register & receive at hub label |
| Repeat entry | Register-another buried in Charges, Client preselection only | Primary Next from result, explicit Client/route retention, safe resets/new key |
| Processing | Five-panel session-gated path and separate form pages | Independent compact sections, separate transactions and factual remaining tasks |
| Mobile | Several taps, nested fields, existing sticky action CSS | One column, 44px controls, in-flow review/actions, no keyboard overlay |
| Authority | Existing server services/guards | Same services/guards, earlier explanation, no client-side settlement or permission inference |

**Efficiency estimate only:** for the proposal's minimal existing-Client repeat scenario, ordinary current navigation is 3 forward transitions + Save + register-another = 5 actions; optimized Review-jump use can be 3. Option A targets Save + Next = 2, excluding data entry, first retention setup, optional copying, printing and financial work. That is an estimated 60% reduction versus ordinary controls and 33% versus the optimized baseline, not a measured time improvement. Current site/single-mode defaults and Client preselection already exist and are not counted as new savings. No claim that four server pages disappear.

### F2. Implementation stages for later authorization

| Priority/stage | Scope | Completion boundary |
| --- | --- | --- |
| P0 — contracts and design review | Confirm this Option A field/DOM/focus/custody specification; settle only decisions that block chosen scope; preserve dirty-worktree baseline and record existing test failures | Design approval does not authorize implementation/deployment. No schema work hidden in UI scope. |
| P1 — entry and saved result | Logistics new-registration template branch, flat disclosures, inline review, truthful labels, consistent error focus; result/Next/label hierarchy | Pure presentation can start with current local Client search. Preserve edit/update consumers, all POST fields and old routes. No repeat/retry capability falsely claimed before backend support. |
| P1 — readiness and reliable repeat | Read-only readiness, reviewed-context check, retained-source/keep flags, stable-key pending/unknown states and safe site/return handling | Backend read/presentation/context work; unchanged authority/commit boundaries; no persisted draft or exact-once Client promise. |
| P2 — scoped search/reuse | Paginated lookup, selected-ID validation, source preview/diff/apply, precise Client error/recovery states | No new required fields/party relations/global customer data; durable Client idempotency remains separate unless explicitly approved. |
| P2 — independent processing | Task projection/section navigation, contextual editors/fragments, accurate partial-save feedback, mode-compatible suggestions and return context | Existing financial/Shipment services and native fallback; no auto issue/email/collection/attachment or stricter route policy without approval. |
| P3 — polish and verification | Long/empty/restricted/error states, themes/RTL, keyboard/assistive/real mobile evidence and repaired browser scripts | Accept against G with an authorized disposable environment; no ordinary database fixtures/providers. Commit/push/deployment remain separately authorized actions. |

Scope future styling under a Logistics parcel-registration wrapper and preserve the existing asset load order. Shared `parcel_form.html` has register/edit/update consumers; shared Logistics includes also serve Shipment/other forms. Review consumers before modifying them, or use narrow new-entry compositions. Do not edit shared theme bundles/dashboard shell just to shrink this page. Services templates, defaults, permissions, client/booking flows and billing contracts remain unchanged; use vertical-specific adapters where shared code is necessary. Do not edit collected `src/staticfiles/` or read-only Phoenix sources.

## G. Acceptance criteria and regression evidence

These are requirements for a later implementation, **not passes from this audit**. Use meaningful existing service/endpoint tests and targeted browser scenarios after an authorized disposable target is identified. Do not run existing browser scripts blindly: some still refer to removed receipt buttons and create fixtures/artifacts.

| ID / category | Acceptance criterion |
| --- | --- |
| G01 / structure | New registration has one page/form with essentials visible and no numbered stepper or compulsory empty-details transition. Optional fields use at most one disclosure layer in normal entry; review is visible and directly adjacent to Save. Edit/update modes retain their own behavior. |
| G02 / fields | All current registration fields remain accessible with original names/hidden keys and current conditional requirements/validators. No new mandatory Sender/Recipient/address/weight/value field, no registration price quantity, no automatic measurement/value calculation. |
| G03 / responsive | Inspect 390/768/1440px plus 320px reflow and 200% zoom with navigation both relevant states. Essential content has no page-level horizontal overflow beyond 1px; long Client/site/tracking text wraps. Any unavoidable table scroll stays local and operable. These are design test targets, not current measurements. |
| G04 / actions | Controls and dropdown rows provide at least 44px touch targets; normal flow review/actions do not cover focus or software keyboard. No truncated custody/action meaning; main/secondary actions retain hierarchy in mobile and desktop. |
| G05 / appearance | Verify light/dark and supported RTL using existing tokens, asset order and Motionmate fonts. No global palette, new framework, marketing CSS, decorative tiles or reference/collected-asset edits. Measure text/control/focus contrast rather than assuming token names prove it. |
| G06 / semantics | One meaningful breadcrumb list, coherent heading hierarchy, explicit labels/required markers, valid fieldset/legend/disclosure relationships. Enhanced inputs preserve help/error associations and invalid states; accessible names identify target party/action. No nested forms/stacked modals/positive tabindex. |
| G07 / keyboard | Full fresh, retained, Client-create, copy, error and processing journeys work by keyboard. Enter selects search results without registering, save requires intended activation, textareas/IME remain normal, focus follows D1 and never lands on an inert Choices wrapper. Dialog focus traps/restores correctly and Escape/Cancel preserve drafts. |
| G08 / feedback | Search/save/created/copied/error statuses use restrained live announcements. Errors open their fieldset and link to the real control. Reduced-motion preference disables requested smooth scrolling/optional animations. No blanket whole-summary live announcement per keystroke. |
| G09 / lookup | Server lookup returns only authorized minimal tenant results; stale responses do not replace selections; selected ID validation does not depend on its presence in the current result page. Check no Clients/no matches/inactive/large catalogue/network denial/vendor delay/native fallback. Target<=20 results/page and the proposal's controlled lookup latency budget if implemented. |
| G10 / Client creation | Required six fields and independent transaction remain until identity policy changes. Creation success/error preserves the parcel. Unknown response never auto-creates again; lost-response/concurrent duplicate safety is not described as fixed until an approved durable replay mechanism is verified. |
| G11 / copies | Client/Sender/Recipient remain distinct; copy-empty and overwrite preview behave as specified; typed data is not silently replaced. Cross-tenant/revoked source reads fail; later Client edits do not alter saved snapshots/labels. No prior recipient/value/payment is silently carried into a new parcel. |
| G12 / routes | Preserve configured-mode/defaults, origin/work-site restriction, destination-first/country-only flow, all-tenant destination visibility and mode/territory reference validation. Check changed countries/modes, inactive facilities, historical edits, pageshow restoration, partial JavaScript/no-JavaScript option refresh. |
| G13 / readiness | Missing site/role/module/review/configuration or applicable exhausted Parcel quota is explained early without a domain write. Client/Invoice/Shipment quotas block only relevant creation actions. Unlimited/legacy and monitoring-only states remain accurate; save-time races are still authoritative. |
| G14 / custody and replay | Hub save produces one Parcel, one REGISTERED event and one RECEIVED event with correct actor/site and stable keys, atomically. Nonhub registration remains REGISTERED. Exact concurrent/replayed saves do not duplicate usage/history or rewind later movement; changed payload/actor keys conflict. Context changes never silently switch a reviewed custody action. |
| G15 / unknown saves | Parcel pending/timeout keeps exact attempted payload/key; no Next/fresh UUID/implicit resubmit until known result. UI prevention does not replace service idempotency. Authentication/permission revocation remains enforced; no closed-tab recovery/offline-queue promise. |
| G16 / next and labels | Next requires confirmed save and current registration capability, uses a fresh identity/key and only opt-in Client/destination/mode; everything else clears per E2. Label preview/download/422/print/copy failure retains saved parcel; no automatic print/next/email/collection or inferred hardware success. |
| G17 / task evidence | A new session/reload with the same records/actor has the same factual tasks regardless of Payment visits/skip choice. Missing obligations and unverified legacy PAID remain review/uncleared; paid/no-payment-required/refund/credit/clearance stay distinct. Summary never implies full operational completion. |
| G18 / ledger boundaries | Save Charge, create/append Invoice, issue and record receipt retain independent service POSTs, keys, protected snapshots/lines, full shared balances and conditional allocations. Inject later failures and verify earlier saved records remain accurately displayed; no aggregate retry duplicates them. New Shipment+assignment remains its existing atomic operation. |
| G19 / authority | Direct POST, read/JSON/fragment and rendered DOM checks across owner/admin/operating staff/read-only staff/accountant/viewer, tenants/sites/revocation/read-only subscription. No hidden restricted money/identity payloads, no new staff Shipment management, no destination-derived operating grants. |
| G20 / movement | Departure/delivery still recheck existing settlement/action-specific credit/evidence services under lock. Saving/issuing/recording navigation intent/assigning does not bypass clearance. No automatic email/payment-provider calls introduced; explicit email submission is not claimed as delivery. |
| G21 / Shipment and returns | Known incompatible modes filtered before pagination; discover an eligible older candidate beyond previous 25; labels accurately flag unknown/ambiguous cases. Direct service behavior matches only approved route policy. Edit/label/browse/filter/pagination/create/assignment/site changes return safely to the scoped Parcel when explicit context supplied; old direct routes still work, foreign/external context does not. |
| G22 / regressions | Preserve CSRF, named routes/methods/query parameters, form prefixes, UUID/revision/optimistic edit fields, public tracking privacy, audit history and native POST/redirect fallback. Include Services isolation checks and unchanged source snapshot verification; retain scanner typed/pasted/keyboard/camera fallback when affected navigation is reviewed. |
| G23 / efficiency | Count Option A's minimal repeat Save+Next target separately from typing, retention setup, copying, labels/finance. Measure a matched operator scenario before claiming speed; proposal target of at least 20% lower median versus ordinary current path with no increase in Client/route/custody errors and p95 no worse remains unverified. |

Relevant existing coverage to retain/revise includes `test_parcels.py`, `test_parcel_intake.py`, `test_registration.py`, `test_registration_changes.py`, `test_registration_concurrency.py`, `test_route_entry.py`, `test_shipping_labels.py`, `test_workflows.py`, financial access/coverage/credit/receipt suites and their concurrency tests. Browser scripts `logistics_registration_changes_browser_check.py` and `logistics_route_entry_browser_check.py` have useful scenarios, while `logistics_parcel_wizard_browser_check.py` and older registration scripts need their changed controls reviewed. Inspect browser sources for fixture writes before future execution; neither their existence nor historical results prove a current pass.

## H. Unresolved business decisions — separate from the layout specification

The requested task selects Option A. That selection does **not** decide the policies below or authorize implementation. The conservative initial behavior is specified so visual work need not invent answers.

| Decision | Initial design position | What needs a separate decision |
| --- | --- | --- |
| Hub pre-advice | Preserve current authorized hub receipt on both save branches; explicit label | A registration-only option at the same hub would change operational custody policy. |
| Shipment leg compatibility | Conservative route/mode suggestions; existing assignment authority retained | Same complete route versus intermediate consolidation leg, strict service equality and any audited override. UI filtering alone does not fix F01. |
| Client individual/company identity | Keep current six required inputs; no fabricated company/address | Honest Individual flow, required-field changes and geographic defaults/input, scoped to Logistics without changing Services. |
| Inactive Client selection | Show inactive label, preserve eligibility | Exclusion, required reactivation or additional confirmation. |
| Durable Client retries | Independent save, duplicate suggestions, conservative unknown-result recovery | Transactional persisted request/result binding; any schema needs its own authorization. No UI exact-once promise. |
| Retention/drafts | Explicit short-lived same-operator Client/route preference; shipping copy per parcel | Cross-session/device/shared-terminal retention, persisted drafts, PII lifetime and copy-source audit provenance. |
| Manual online receipt evidence | Preserve current CASH/BANK_TRANSFER/ONLINE receipt policy and wording | Provider verification, additional proof/approval, custody/reconciliation requirements. |
| Label requirements | Parties/weight optional, advisory missing details, explicit print | Mandatory shipping data, auto-print, printer selection or auto-advance after printing. |
| Declared-value currency | No automatic value reuse; current new-entry currency label, no historical inference | Saved currency field/verified backfill or conversion policy; F18 remains a data-policy issue. |
| Durable deferral/cleanup | Factual persisted tasks; independent saved Client remains if parcel abandoned | Audited “payment deferred,” task assignees/due dates, abandoned-Client deletion or automatic cleanup. |

## Verification record for this specification

- Read requested instructions/documents and inspected current template inheritance, loaded assets, CSS breakpoints, field/error/modal components, route/Client/copy/wizard JavaScript, relevant forms/views/services/policy and test sources. Consulted Phoenix examples read-only. Presentational risks are not represented as browser observations.
- Checked this document's referenced files/line bounds, Markdown structure/wireframes, required A–H sections and whitespace. No rendered/browser/contrast/performance/real-device claim is made.
- Compared hashes for all pre-existing changed/untracked files, including both earlier audit documents, before and after this task. The only new task file is `docs/audits/logistics_parcel_registration_ux.md`.
- Stopped at specification. No application code, existing working-tree file, Services behavior, database, migration, write-producing test, commit, push or deployment was changed/performed.
