# Data Import validation results

All runtime checks used the verified owned session
`/tmp/motionmate-preview-session-_k8z05ah` or its AFTER cluster's runner-owned
`test_services_rollout`; no ordinary database, provider or customer data.

- **221 Django tests passed** covering parsing/optional fields, client previews
  and execution, lead/service execution, atomicity/revalidation/retry, permissions,
  tenant/actor isolation, active capacity, combined category/service import, history
  privacy, shared UX contracts and relevant Logistics import quotas.
- **One native LiveServer CSV journey passed**, then passed again after the
  disclosure/style refinements. Real login; upload/preview/confirm/result; invalid
  email blocked; no editable preview; service update/category creation; file draft
  retained through theme change; metadata-only history; no unintended Client,
  Appointment or Invoice writes. Final log: after/native-final.log.
- **Two superseded copy-only tests passed on frozen BEFORE**. They expect the old
  preparation-step labels and “Nothing is saved” phrase. AFTER tests cover the
  approved five stages and accurate domain-record save guidance. Existing test
  source was not changed and those obsolete assertions are not claimed as AFTER
  passes. Log: after/before-copy-baseline.log.
- **Three offline setup refusal checks passed** with the existing identity guards.
- Real BEFORE and AFTER each completed **48 core screen/theme/viewport cases**,
  plus blocked/expired/detail/Client Import and empty/long/read-only/history/320px
  scenarios. AFTER core cases had zero module axe violations, document overflow,
  undersized checked targets or JavaScript errors.
- The initial AFTER runner ended on an incorrect inherited Catalogue role rule.
  Its 48 case findings are retained, not rewritten. The corrected Data Import
  checker performed **10 fresh actual role cases**: Staff can import Clients/Leads;
  Accountant Clients; Owner/Admin additionally Services/history; Viewer denied.
  Logistics retains its original branch/assets. No permission change was made.
- **Five final current-source cases passed**, with native keyboard file-to-submit
  navigation, Enter-operated disclosure and Tab access to copyable CSV. Initial
  domain/financial inventory and all complete **44-job metadata/payload facts**
  remain unchanged on both review databases. Writes were confined to test data.
- Raw axe retains **24 incomplete core-case findings** for manual review.
  Full-page findings include the unchanged shared Phoenix sidebar contrast issue
  (['color-contrast']); module content has no reported axe violations. No AA certification.
- Exact 31-file ownership, eleven original non-Services content-block byte strings,
  original/current Logistics rendered output, accepted Client Import source/assets
  and frozen Catalogue candidate were verified. Ruff/format and diff checks passed.

Raw evidence: BEFORE before/evidence/data_import-1795209362117773993/report.json;
AFTER after/evidence/data_import-1795209635995538021/report.json; corrected roles
after/evidence/data_import-1795209949696074788/report.json; final current source
after/evidence/data-import-final-1795210064822347633/report.json. Four selected
screenshots are durable; full reports/logs remain in the owned external session.

Reproduce with installed Chrome and the unchanged guarded boundaries:

```sh
export PWA_CHROMIUM=/home/mzero/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome
PYTHONPATH=scripts .venv/bin/python -B -m ui_preview.data_import_checks --session /tmp/motionmate-preview-session-_k8z05ah --suite backend
PYTHONPATH=scripts .venv/bin/python -B scripts/services_data_import_browser_check.py --session /tmp/motionmate-preview-session-_k8z05ah --side after
```

Live providers, ordinary runtime/database health and full assistive-technology
coverage remain unverified. Existing debug allocator workaround is disclosed.
