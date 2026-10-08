# Canadian employer coverage expansion

## Combined preview correction, October 1, 2026

The initial expansion preview used a separate database and omitted the original preview inventory. This is now corrected: all eight new sources were verified against fresh official snapshots and ingested normally into the original local jobber_work database. Its 4,197 original posting rows were checked by ID, active state and full-row hash: every original posting remains unchanged. Added 146 stored postings; combined stored total is 4,343. All eight source ingestions completed with zero parsing or record errors and zero deactivations. Cohere was already present and was left untouched.

The combined default feed increased from 1,016 to 1,115 postings. Jobs and Stats both return 1,115, across 63 employers. Canada has 429 public postings, including 34 internships/co-ops/new-grad/entry-level roles. Exact company filters return Google 13, Bell 7, Rogers 2, Scotiabank 67, Shopify 1, Clio 4, EQ Bank 5 and Cohere 6. TELUS remains zero. Original employers remain available, including Amazon 58 and NVIDIA 198 in the current public window.

Both preview APIs now read jobber_work; ports 5173 and 5174 therefore show the same combined inventory. The original preview servers had stopped and were restarted on their free ports, with port 5173 connected directly to the local API rather than the fault-injection proxy. Production remains unchanged. Counts below describe the earlier isolated verification snapshot, not the current combined preview.

Implemented October 1, 2026. Local changes and local ingestion only; nothing committed, pushed or deployed. Existing changes and audit evidence from other agents were preserved.

## Connected sources

Added Google (official Canada careers search), Shopify (official careers pages), Bell (public Phenom feed), Rogers, Scotiabank and TELUS (public SuccessFactors pages), Clio (official Workday board) and EQ Bank (Lever). Cohere already had an Ashby adapter and was refreshed rather than duplicated. RBC, TD, BMO and CIBC were already configured; their complete coverage was not re-audited in this expansion.

New adapters retain descriptions, source locations, compensation/benefits prose and exact official posting destinations. Unknown dates remain unknown. Shopify's broad Americas/Global labels do not establish Canadian eligibility. An explicitly US internship stays US. Bell's future-opportunities talent-community signup is excluded from public jobs, with its old record retained internally as inactive.

Pagination totals, duplicate source IDs, malformed responses and failed details make a snapshot incomplete. Incomplete snapshots suppress closed-job reconciliation; failed details cannot overwrite a complete description with a blank. Rogers/Scotiabank/TELUS IDs include tenant identity. Ambiguous technical graduate programs require software evidence; generic HR, finance and physical-network programs are excluded.

Official employer logos were downloaded from verified employer assets, inspected and mapped locally. Original brand colors are retained; dark or white marks have suitable backplates. No Indeed or guessed LinkedIn/Simplify applications were added.

## One local inventory snapshot

Snapshot: October 1, 2026, 13:32:27 Toronto. Local Unix-socket `jobber` database: 858 stored records, 166 default public postings, 14 public employers. These are not production counts and must not be combined with earlier audit inventories. The default window includes recently discovered undated postings under the existing policy; it is not proof that every posting was published within 30 days. Google's 13 posting dates are unknown.

| Employer | Default public | Canadian | Canadian internship/co-op/new-grad/entry |
|---|---:|---:|---:|
| Google | 13 | 13 | 1 |
| Shopify | 1 | 0 | 0 |
| Bell | 7 | 7 | 4 |
| Rogers | 2 | 2 | 0 |
| Scotiabank | 67 | 64 | 10 |
| TELUS | 0 | 0 | 0 |
| Clio | 4 | 4 | 0 |
| EQ Bank | 5 | 5 | 3 |
| Cohere, existing source | 6 | 6 | 0 |

Whole local public inventory: 102 Canadian postings, including 4 internships, 6 co-ops, 4 new-grad and 4 entry-level roles (18 early-career total). Public workplace classification: 75 hybrid, 2 on-site, 8 remote and 81 unspecified. These workplace totals cover all countries.

Local updates used the normal `sync_company` ingestion path after verification. The nine employer fetches were complete with no parse errors. Bell's confirmed talent-community exclusion was then reconciled through that same path. No unrelated compensation backfill was performed. Cohere's 26 active stored records have structured compensation; source salary and benefit prose is preserved elsewhere without inventing ranges or intervals.

## Verification

- Python: 777 tests passed against a populated local database; one existing Starlette/httpx deprecation warning.
- Frontend: 381 tests passed across 24 files. Lint, TypeScript, production build and `git diff --check` passed.
- Regression coverage includes pagination, source-count changes, duplicate IDs, failed/missing details, strict adapter registration, source date handling, multi-location separators, official source links, description caveats, tenant IDs, Shopify eligibility and public-field-only loader extraction, technical graduate programs and talent-community exclusions.
- Desktop in-app browser: Google/Bell/EQ Bank searches, result counts and URL synchronization; representative details; Google internship description compared with its exact official posting, including residency, deadline and CAD compensation caveats. Opened the exact official Google destination without submitting an application. EQ Bank internship opened using Enter; Escape closed it and restored focus to its activation button. Primary EQ Bank application URL is the exact Lever role application.
- Google browser verification caught decorative source glyphs, an extra separator location and relative legal links. Adapter fixes preserve meaningful announcements and resolve employer links. The final Google records were refreshed through normal ingestion after verification.

This turn did not rerun axe, the mobile/theme viewport matrix, Firefox/Safari, 200% zoom, reduced motion, offline/slow or reordered browser responses, or live browser API-failure injection. Adapter failure behavior was tested with controlled fixtures. Logo files were inspected; a complete new two-theme layout audit was not performed.

## Remaining gaps and preview

TELUS's connected feed currently has no clearly eligible software postings; this does not establish comprehensive coverage of all TELUS technology hiring. Shopify's current broad regional roles lack explicit Canadian eligibility. Cohere has an older Canadian internship stored internally that falls outside this snapshot's default window. Additional employers such as Lightspeed and National Bank need maintainable custom adapters; discovery failures elsewhere are not evidence of no vacancies.

Google coverage is the Canada search slice, not its worldwide inventory. Employer HTML can change; adapters fail incomplete rather than falsely closing jobs. Earlier language-correspondence issues documented in `REMEDIATION_REVIEW.md` remain a separate unresolved concern. This report does not claim the original audits are entirely fixed.

Expanded local preview: http://localhost:5174/jobs?q=google, using the separate local API on port 8004. The existing preview on port 5173 and API on port 8000 were left running untouched and use a different dataset. Production data and deployment remain unchanged. All work is uncommitted and ready for review.
