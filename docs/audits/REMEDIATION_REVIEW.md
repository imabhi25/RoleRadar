# Independent review of Claude's remediation

Reviewed October 1, 2026. Changes remain unpublished. This report supplements both preserved audits; it does not replace their evidence or certify every audit finding as resolved.

## Confirmed defects corrected during this review

1. Lever salary deduplication suppressed the entire salaryDescription when the body mentioned the minimum salary or contained a compensation heading. This lost bonus, benefits and overtime caveats. It now checks the complete normalized narrative, preserves additional disclosure, and avoids adding a second heading. Regression tests cover repeated figures, existing headings and complete narrative duplication.
2. Greenhouse guessed hourly versus annual pay from numeric magnitude. It now leaves unknown intervals unspecified and refuses to combine ranges with different intervals. Separately published pay-range blurbs are retained when missing from the description.
3. Public visibility used midnight 30 days ago, admitting timestamped postings almost 31 days old. SQL and Python now use the exact rolling cutoff, inclusive at the boundary. The legacy freshness helper default is also 30 days. Unknown dates require first-seen evidence plus a source observation in the last 48 hours; last-seen is no longer used as a substitute for first-seen by the Python mirror. Future-date tolerance remains documented through tomorrow UTC; farther future dates use the undated policy.
4. Loose company paragraphs could override job signals or reader-directed responsibilities. The job signal check now runs before company-name matching. NVIDIA/Toast/mixed paragraph tests cover this.
5. Workday fetched software-role descriptions only for North American or unknown locations. It now fetches details for software/student roles regardless of country, while unrelated roles still avoid unnecessary detail requests. A Germany fixture verifies description/date preservation. Existing rows have not been backfilled during this review.
6. An ingestion-safety fixture used September 1, 2026 as its posting date and expired during the full test run today. It now uses a relative date; its location-preservation assertions are unchanged.

## Verification performed independently

- Python: 730 passed, no skips against populated jobber_work; one Starlette dependency deprecation warning.
- Frontend: 301 passed; ESLint, TypeScript and production build succeeded.
- Git diff whitespace check: passed.
- Browser: local app loads the reconciled 1,024 count; accented search with surrounding whitespace yields six results. Real Enter opens the Amazon detail; real Tab/Shift+Tab stay inside the mobile dialog; Escape closes it, returns focus to the originating card and releases scroll lock.
- 320px light and dark screenshots inspected with the long bilingual Amazon title; dark layout has no horizontal document overflow. 390px modal behavior exercised. This is a focused check, not every viewport/theme permutation.
- Followed the exact Amazon employer URL for job 10565854. The live employer page confirms the same title, job ID, Montreal location and CAD 126,000–210,400 annual compensation shown in the stored/rendered description. No application submitted.
- Default list profiled locally with EXPLAIN ANALYZE BUFFERS: count execution 12.94 ms, list execution 19.969 ms; planning 8.273/7.497 ms. Local API test request 126 ms. The production latency remains unconfirmed; no speculative query rewrite made.

## Inventory reconciliation

One read-only REPEATABLE READ transaction at 2026-10-01T11:24:54.184422-04:00:

| Stage | Jobs | Empty descriptions |
|---|---:|---:|
| Stored records, including inactive | 4,197 | — |
| Active eligible-role records, 68 employers | 4,192 | 191 |
| Existing official-source + US/Canada geography rules | 3,125 | 0 |
| Deduplication rules | 3,125 | 0 |
| Rolling 30-day public window | 1,024 | 0 |

Jobs and Stats both return 1,024. Canadian public jobs: 335. Canadian internship/co-op/new-grad/entry-level counts: 10/4/2/0. Public workplace counts: remote 177, hybrid 203, onsite 14, unspecified 630.

The 191 empty descriptions are excluded by geography before the freshness filter. Thus the earlier concern that these blank records reach the default public feed was not confirmed. The existing API is US/Canada scoped despite historical references to global browsing; this review does not expand its geography. Config and latest source status total 68 employers, correcting the handoff's 62 claim. Counts differ from the handoff because the snapshot time and cutoff policy differ. These are LOCAL scratch counts, not production counts.

## Work still outstanding

- Production deployment, ingestion backfill and production validation have not occurred.
- Google/Apple/Meta/Tesla coverage investigation remains incomplete. An HTML page or a redirect is not sufficient evidence of a source blocker. No new coverage adapters were added in this review.
- Generic Workday/Amazon logo discovery remains absent; unresolved identities must remain unresolved.
- No independent full-inventory parser run after the changes in this review; focused fixtures validate corrected classification cases. Claude's earlier whole-inventory metrics are not proof of all section classification.
- No fresh axe run, Firefox/Safari, real 200% zoom, reduced-motion emulation, or complete tablet/desktop/theme matrix in this review. Claude's fault-harness checks were not rerun here.
- No production query plans or live deployment header/robots/sitemap validation.
- Revised compensation and Workday ingestion must go through a verified normal sync before production backfill. This review made no employer-data mutations; database test fixtures are isolated/rolled back.

## Git and evidence

Existing edits and both audit evidence directories preserved. No commit, push, pull request, deployment or production mutation. This review adds targeted fixes on top of Claude's working tree. Audit captures, secrets and bulk inventory data were not staged.
