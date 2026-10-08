# Jobber adversarial QA audit

Audit date: September 30, 2026 (America/Toronto). Production: https://jobber-mauve.vercel.app. Public API: https://jobber-api-980d.onrender.com. Repository: imabhi25/Jobber.

## Assessment

The site is usable, and the sampled official application links are healthy. Do not treat it as fully trustworthy yet: Lever ingestion drops disclosed PointClickCare compensation, and optional analytics can prevent job browsing during a failure. Presentation also deletes Stripe’s prominent deadline heading, although its equivalent requirement survives further down. The local development build also crashes on an actual company name. There is no confirmed P0 or security exposure in this audit.

The inventory meets volume more than relevance: **1,198 jobs across 59 active companies, but only 27 Canadian early-career jobs**, with no match for the tested Canada + internship/entry-level + remote combination. **272 dated jobs exceed a rolling 30-day window**; the default policy is 45 days. Expanding stale inventory to reach a target would make the product worse. Correct the policy and prioritize genuinely eligible Canadian internships.

This is a discovery report; no application source fixes, commits, pushes, deployments, accounts, application submissions or production-data mutations were made. Public requests were sequential at modest rates; no load or destructive security testing occurred.

## Environment, provenance and evidence limits

- Checkout HEAD: `9b6473d6a9be7ba063aac3c5d70bc213a3e646e1`, September 30, 2026 15:55:47 EDT, “fix: improve job detail parsing and global job browsing”.
- Production-configured local build JS is **byte-identical** to deployed `index-_JzMm6_L.js`: SHA-256 `7cecd63bddd4fdb4dc3838c1756040e15bf8c96e303c6ce25b625213d3fac5db`. This establishes frontend parity, not backend revision parity.
- Production HTML: Last-Modified September 30 19:58:53 GMT; ETag `a88cacc52849f48dfec431e8a951e02c`; Vercel cache HIT. An exact deployment ID and backend commit were not exposed. Request IDs are not deployment IDs.
- Browser: Chrome on macOS through the connected browser extension. Exact browser version was not available. Viewports tested: 1440×900, 1280×720, 768×1024, 390×844, 320×844. Both themes were exercised; not every viewport/theme permutation.
- Development server on 5173 using the public API reproduces B04. Production preview on 4173 could not call the API because of origin CORS restrictions; that preview failure is not a production defect.
- HTTP-failure and axe tests used an isolated local built-app harness on 8765 with captured public response fixtures. External audit scripts were injected outside the app root; application source was unchanged. Fixture search matching is simplified, so only error behavior/DOM accessibility—not real search accuracy—is inferred from that harness.
- Evidence is under `qa-evidence/`. Public API snapshots, employer HTML, rendered detail DOM, comparisons and screenshots are retained. Earlier audit artifacts that appeared in the workspace were preserved as `qa-evidence/previous-audit-preserved.md`; their unverified counts/claims are not included as findings here.

## Prioritized confirmed issues

| ID | Severity | Category | Issue | User impact | Evidence |
|---|---|---|---|---|---|
| B02 | P1 | Ingestion/data | PointClickCare salary and compensation narrative disappear | Employer compensation should appear accurately | See B02 below |
| B03 | P1 | Resilience | An analytics failure blocks the entire Jobs page | Optional analytics must fail independently | See B03 below |
| B04 | P1 | Local runtime/logos | A company named Constructor crashes development rendering | Unknown company names should use a safe fallback | See B04 below |
| B01 | P2 | Description | Stripe loses its prominent start-date heading | Meaningful employer headings must survive presentation cleanup | See B01 below |
| B05 | P2 | Freshness/requirements | Default visibility remains 45 days rather than requested 30 | The requested default fresh window is 30 days. The site honestly labels its broader option 45 days, but its implementation does not meet that requirement. | See B05 below |
| B06 | P2 | Search/error state | Failed queries retain old cards and counts under the new query | A failed new query must not present the previous query’s results as current matches. | See B06 below |
| B07 | P2 | Description hierarchy | Role duties are moved into About the Company | Company background and role responsibilities should remain distinct | See B07 below |
| B08 | P2 | Accessibility | Navigation and cards use invalid ARIA semantics | Expose valid navigation/control semantics. Automated critical/minor labels are tool impacts, not separate P0/P3 issue severities. | See B08 below |
| B09 | P2 | Deep-link errors | Unknown job IDs remain titled Loading job details after failure | A missing/expired job should show a final unavailable state with close/return guidance rather than a loading heading and connection-style retry. | See B09 below |
| B10 | P3 | URL validation | Very large page numbers produce an unrecoverable connection error | A syntactically valid out-of-range page should be normalized to a supported page, not presented as a network failure. | See B10 below |
| B11 | P3 | Description formatting | Mixed Markdown and ATS tracking tags leak into descriptions | Presentation should preserve meaningful prose while rendering emphasis and removing ATS-only tracking tokens. | See B11 below |
| B12 | P3 | Date accuracy | Date-only sources are displayed with invented hour precision | Show date-level age for date-only sources | See B12 below |
| B13 | P3 | Metadata/routing | robots.txt and sitemap.xml return HTML instead of their formats | Serve valid robots/sitemap resources (or intentional 404 where absent) | See B13 below |

Severity follows the requested P0–P3 scale; tool-level axe impacts do not override it. Multiple occurrences of a common parser, markup or error-state cause are consolidated.

## Confirmed issue details

### B02 — P1: PointClickCare salary and compensation narrative disappear

- **Route/environment:** /jobs?job=lever%3A150b07cd-04e9-46c4-9015-114498f3798c; Senior Machine Learning Systems Engineer (CAD). Production, 1440×900, light.
- **Reproduce:** Open the job and compare compensation with the exact Lever listing. The employer shows CAD $154,000–$193,000 per year plus bonus and benefits. Neither the range nor its narrative is in Jobber’s stored description; compensation is null.
- **Expected versus actual:** Employer compensation should appear accurately; it is absent at ingestion, so the frontend cannot recover it.
- **Frequency/scope:** One independently confirmed salary omission; all 25 public Lever postings use this adapter, but not all are proven affected.
- **Likely cause:** ingestion/clients/lever.py:84–118 assembles description, lists and additional sections but ignores Lever salaryRange and salaryDescription. The exact public Lever response contains both.
- **Recommended fix and meaningful regression:** Include separate salary fields in normalized description and structured compensation, preserving currency, interval and caveats. Regression: a real-shaped Lever fixture with salary only in those fields retains both numeric range and narrative.
- **Evidence:** pointclickcare-official-api.json; detail-07.json; original-description-07.html; description-comparison.json. Original: https://jobs.lever.co/pointclickcare/150b07cd-04e9-46c4-9015-114498f3798c

### B03 — P1: An analytics failure blocks the entire Jobs page

- **Route/environment:** Local isolated fixture http://127.0.0.1:8765/jobs; built application, 1440×900, light. Fault injection only locally.
- **Reproduce:** Serve the captured public API fixtures; set failure-mode.txt to stats_error so only /api/stats/skills returns 500; reload /jobs. Jobs and search disappear behind Unable to load dashboard data although job endpoints remain healthy. Restore normal and retry to recover.
- **Expected versus actual:** Optional analytics must fail independently; they currently prevent the core job browser from mounting.
- **Frequency/scope:** Deterministic local reproduction. Production outage was not induced. Same App code is in the byte-identical production-configured build.
- **Likely cause:** frontend/src/App.tsx:199–215 uses Promise.all for six dashboard requests; :375 renders JobExplorer only when the shared loading/error state succeeds.
- **Recommended fix and meaningful regression:** Load job browsing independently, lazy-load Stats and isolate widget errors. Regression: skills/companies stats 500 with jobs 200 still permits searching, opening and applying to a job.
- **Evidence:** stats-failure-blocks-jobs.jpg; failure-server.py; failure-server.log.

### B04 — P1: A company named Constructor crashes development rendering

- **Route/environment:** http://127.0.0.1:5173/jobs and dev-only /logos or /companies; 1440×900, light.
- **Reproduce:** Run Vite with the production public API. The /api/companies response includes Constructor (id 228, no logo, zero active jobs). When the hidden development contact sheet mounts, the React tree goes blank; console: TypeError: url.startsWith is not a function.
- **Expected versus actual:** Unknown company names should use a safe fallback; the whole development app crashes.
- **Frequency/scope:** Local development only in this inventory: production excludes CompanyContactSheet and remains usable. This is not a production P0.
- **Likely cause:** frontend/src/utils/companyLogos.ts:315 indexes a normal object with normalized name constructor and receives the inherited Object constructor. frontend/src/api/client.ts:130 assumes a string. frontend/src/App.tsx:551 mounts the development contact sheet even when hidden.
- **Recommended fix and meaningful regression:** Use Map, a null-prototype dictionary or own-property checks; validate URL types and isolate preview errors. Regression: Constructor, toString and __proto__ names plus the captured 318-company inventory never throw or blank Jobs.
- **Evidence:** local-crash.jpg; local-crash.json; companies.json.

### B01 — P2: Stripe loses its prominent start-date heading

- **Route/environment:** /jobs?job=greenhouse%3A8212517; Stripe, Software Engineer, Early Career — Immediate Start. Production, 1440×900, light/dark.
- **Reproduce:** Open the exact job; compare the first employer heading with About the Job. The employer and stored API description state that applicants must start before December 1, 2026. That standalone statement is absent from the rendered description. Crucially, the same deadline survives later as a minimum-requirements bullet, so eligibility is not completely lost.
- **Expected versus actual:** Meaningful employer headings must survive presentation cleanup; the prominent deadline heading is deleted while an equivalent requirement remains lower in the page.
- **Frequency/scope:** Confirmed on this job. The same parser handles every description; broader loss is possible, not counted as confirmed.
- **Likely cause:** frontend/src/utils/descriptionSections.ts:132–146 removes a heading whose following section has no non-heading content; removeEmptySections at :170 is used by JobDetailContent.tsx. The next peer heading makes the informative first heading look empty.
- **Recommended fix and meaningful regression:** Preserve informative heading text. Remove only genuinely empty nodes or a narrowly defined empty field label. Regression: a full-sentence deadline in h2 followed by a peer h2 remains visible and in source order.
- **Evidence:** stripe-deadline-heading-omitted.jpg; detail-04.json; rendered-04.json; original-description-04.html; render-comparison.json. Original: https://stripe.com/jobs/search?gh_jid=8212517

### B05 — P2: Default visibility remains 45 days rather than requested 30

- **Route/environment:** Production /jobs, /stats and Date posted menu; 1440×900, light/dark.
- **Reproduce:** Load the default inventory and select Past 30 days. Default total is 1,198 versus 925 with the rolling 30-day filter; 272 dated postings are older than 30×24 hours and one has no date.
- **Expected versus actual:** The requested default fresh window is 30 days. The site honestly labels its broader option 45 days, but its implementation does not meet that requirement.
- **Frequency/scope:** Entire default public feed. Age count is a rolling timestamp comparison, not rounded calendar labels; boundary counts may differ by one day and audit time.
- **Likely cause:** ingestion/freshness.py:241 sets PUBLIC_VISIBILITY_DAYS = 45. Frontend exposes a 45-day recent window.
- **Recommended fix and meaningful regression:** Apply the requested 30-day public visibility policy, define handling of unknown dates and keep older active records internally if needed. Regression: 30-day exact boundary, unknown/future dates and Toronto/UTC midnight cases; default count agrees with policy.
- **Evidence:** all-jobs.json; data-analysis.json; api-30d.json; api-checks.json.

### B06 — P2: Failed queries retain old cards and counts under the new query

- **Route/environment:** Local isolated fixture /jobs; 1440×900, light.
- **Reproduce:** Load the 1,198-job fixture, set mode list_error, then search Python. The Python input is shown with the old 1,198 count and old cards alongside an error. Set normal and Retry: the Python result set recovers.
- **Expected versus actual:** A failed new query must not present the previous query’s results as current matches.
- **Frequency/scope:** Deterministic list-request 500 reproduction; filters, sorts and pages share the same error path. Production failures were not induced.
- **Likely cause:** frontend/src/components/JobExplorer.tsx:234–238 sets error without clearing/qualifying jobs and total; list/count rendering retains previous state.
- **Recommended fix and meaningful regression:** Bind displayed results to the query that produced them; hide them or explicitly label them as previous results on failure. Regression: query A succeeds, query B fails; B never announces A’s count as B matches, and Retry recovers B.
- **Evidence:** failed-search-old-results.jpg; failed-search-logs.json; failure-server.py.

### B07 — P2: Role duties are moved into About the Company

- **Route/environment:** /jobs?job=workday%3AStaff-Software-Engineer---AI-Platform_JREQ201848; Thomson Reuters Staff Software Engineer — AI Platform. Production, 1440×900, light.
- **Reproduce:** Open the job. The About the Company region contains As a Lead Software Engineer…you will own… and This role is for… sentences describing the applicant’s actual job.
- **Expected versus actual:** Company background and role responsibilities should remain distinct; the classifier relocates mixed content misleadingly.
- **Frequency/scope:** Confirmed supplemental job beyond the 20-job baseline. Other candidate paragraphs were not counted as confirmed.
- **Likely cause:** frontend/src/utils/descriptionSections.ts:509–522 and :549–555 prioritizes startsAboutCompany before a role signal, moving whole mixed paragraphs/sections.
- **Recommended fix and meaningful regression:** Keep ambiguous mixed content under the role or split conservatively while preserving order. Regression: a paragraph opening with company background followed by duties remains available in the role section.
- **Evidence:** tr-company-role.jpg; rendered-tr-staff.json.

### B08 — P2: Navigation and cards use invalid ARIA semantics

- **Route/environment:** /jobs and shared navigation; isolated build DOM at 1440×900, both themes; production markup/source also inspected.
- **Reproduce:** Run axe-core 4.11.0 over #root with populated cards. Both themes report aria-required-children for the tablist containing a focusable GitHub anchor, and aria-allowed-role for 20 article elements assigned role=button.
- **Expected versus actual:** Expose valid navigation/control semantics. Automated critical/minor labels are tool impacts, not separate P0/P3 issue severities.
- **Frequency/scope:** One shared semantic issue with two markup sites; not 21 separate bugs. No full assistive-technology session was performed.
- **Likely cause:** frontend/src/App.tsx:297 tablist wraps Jobs, Stats and GitHub; frontend/src/components/JobCard.tsx:65–69 overrides article with button role.
- **Recommended fix and meaningful regression:** Use ordinary navigation links for route navigation, or a complete tabs pattern with external links outside. Use an appropriate native control/link for card activation. Regression: axe plus keyboard navigation, names and focus behavior on Jobs/Stats and cards.
- **Evidence:** axe-light.json; axe-dark.json. Contrast passed for checkable elements; incomplete checks remain listed in those files.

### B09 — P2: Unknown job IDs remain titled Loading job details after failure

- **Route/environment:** /jobs?job=qa-no-such-id; production, 1440×900, light.
- **Reproduce:** Navigate directly to this nonexistent ID. The API responds 404. The modal retains Loading job details… above Unable to load job details; Retry repeats the same permanent error.
- **Expected versus actual:** A missing/expired job should show a final unavailable state with close/return guidance rather than a loading heading and connection-style retry.
- **Frequency/scope:** Direct unknown ID reproduced. A real recently closed job was not available to reproduce this state.
- **Likely cause:** frontend/src/components/JobDetailContent.tsx:61 uses a generic fetch error; :150 falls back to Loading job details whenever head is absent even after loading ends.
- **Recommended fix and meaningful regression:** Handle 404 separately and render a stable unavailable title. Retry only transient errors. Regression: unknown ID, known removed ID fixture, 500 and recovery, with no contradictory loading announcement.
- **Evidence:** Public /api/jobs/qa-no-such-id returned 404; source above.

### B10 — P3: Very large page numbers produce an unrecoverable connection error

- **Route/environment:** /jobs?page=999999999; production, 1440×900, light.
- **Reproduce:** Navigate to the large positive page. Its calculated offset exceeds the backend’s accepted bounds, returning 422 and showing an unable-to-load/connection error; Retry resends it. In contrast, ordinary page=999 successfully clamps to the last page (60).
- **Expected versus actual:** A syntactically valid out-of-range page should be normalized to a supported page, not presented as a network failure.
- **Frequency/scope:** Large accepted safe integers; normal out-of-range pagination works.
- **Likely cause:** frontend/src/utils/urlState.ts:140–147 accepts safe positive integers without an API-compatible maximum; list offset is calculated before total-based clamping.
- **Recommended fix and meaningful regression:** Clamp/validate against supported API limits and distinguish invalid parameters from transport failures. Regression: negative, decimal, unsafe, huge-safe and ordinary out-of-range pages yield canonical, recoverable states.
- **Evidence:** huge-page-error.jpg; api-checks.json (huge_page captured as HTTP error).

### B11 — P3: Mixed Markdown and ATS tracking tags leak into descriptions

- **Route/environment:** PointClickCare sample 07, Notion sample 01, Thomson Reuters sample 13 and CIBC sample 19; production detail, desktop and mobile, both themes across sample coverage.
- **Reproduce:** Read the complete descriptions. PointClickCare renders literal **Travel to Office expectations**; #LI tracking tags remain in four of 20 rendered descriptions.
- **Expected versus actual:** Presentation should preserve meaningful prose while rendering emphasis and removing ATS-only tracking tokens.
- **Frequency/scope:** Four independently observed tracking-tag instances in the 20-job sample; one confirmed raw Markdown heading. Not a claim that all jobs are affected.
- **Likely cause:** frontend/src/utils/sanitizeDescription.ts:46–52 converts Markdown in the plain-text conversion path (:826), leaving mixed HTML/text cases; tracking-token cleanup is incomplete.
- **Recommended fix and meaningful regression:** Normalize inline Markdown safely within text nodes and remove only recognized standalone ATS tracking tags. Regression: mixed HTML with Markdown emphasis and standalone #LI tags, retaining C++/C# and meaningful hashtags.
- **Evidence:** rendered-01.json; rendered-07.json; rendered-13.json; rendered-19.json.

### B12 — P3: Date-only sources are displayed with invented hour precision

- **Route/environment:** Recent Workday cards such as Thomson Reuters sample 13; production /jobs, 1440×900, light/dark.
- **Reproduce:** Compare the employer’s date-only startDate with the card age. Workday converts September 30 to 00:00 UTC and the card reports a number of hours ago, although the employer did not supply a posting time.
- **Expected versus actual:** Show date-level age for date-only sources; do not imply a measured hour timestamp.
- **Frequency/scope:** All 551 Workday plus 87 Amazon records use date-only adapters; misleading hourly labels concern their first day, not every record’s current label.
- **Likely cause:** ingestion/clients/workday.py:78 and amazon.py:28 assign UTC midnight; frontend/src/utils/formatters.ts:16–31 displays elapsed minutes/hours without precision metadata.
- **Recommended fix and meaningful regression:** Retain source date precision and format Today/Yesterday/calendar date for day-level data. Regression: date-only and timestamp sources at UTC/Toronto boundaries and small future skew.
- **Evidence:** detail-13.json; employer-13-ld.json; source adapters and formatters.

### B13 — P3: robots.txt and sitemap.xml return HTML instead of their formats

- **Route/environment:** Production /robots.txt, /sitemap.xml and /qa-missing-route; HTTP read and desktop dark browser.
- **Reproduce:** GET robots.txt and sitemap.xml: both return the SPA HTML shell with HTTP 200 and text/html. Unknown routes also return HTTP 200, although the browser correctly displays Page not found.
- **Expected versus actual:** Serve valid robots/sitemap resources (or intentional 404 where absent); avoid misleading resource success and soft-404 metadata.
- **Frequency/scope:** Confirmed three representative paths. Search ranking impact was not measured.
- **Likely cause:** Production SPA fallback serves index.html for absent assets/routes; inspect Vercel rewrite/static asset configuration. Application title remains generic on job pages.
- **Recommended fix and meaningful regression:** Add actual crawl resources and distinguish asset misses from client routes; provide meaningful unavailable-page metadata/status where hosting permits. Regression: response type/body, sitemap URLs and unknown-route behavior.
- **Evidence:** robots.html; sitemap.html; missing-route.html; browser Page not found confirmed.

## Inventory and data findings

Counts are from the captured public inventory, not estimates. Live changes can alter them after the audit.

| Measure | Result |
|---|---:|
| Unique public job IDs / duplicate source URLs | 1,198 / 0 |
| Active companies / locations / skills | 59 / 133 / 22 |
| Canada-eligible by any listed country location | 412 |
| US-eligible by any listed country location | 839 |
| Jobs spanning both countries | 53 |
| Primary-country Canada / US | 381 / 817 |
| Full-time / internship / new grad / co-op / entry-level | 1,120 / 50 / 15 / 12 / 1 |
| Canadian internship / co-op / new grad / entry-level | 17 / 7 / 3 / 0 |
| Remote / hybrid / onsite / unspecified workplace | 228 / 205 / 16 / 749 |
| Workday / Greenhouse / Ashby / Amazon / Lever | 551 / 389 / 146 / 87 / 25 |
| Rolling ≤30-day filter / dated older / undated | 925 / 272 / 1 |

Canada + US counts intentionally overlap; Stats explains this, so their sum exceeding 1,198 is not a bug. Canada-filtered jobs with US primary display locations can have legitimate Canadian secondary locations; sampled country matches were checked against the full locations arrays. Remote is not permission to work from any country. 749 unspecified workplace values (62.5%) significantly limit remote discovery, but were not reclassified from guesses.

All job IDs were unique; no duplicated source URL was found. Seventy same-company/same-title groups are only duplicate candidates: different requisitions or locations can be legitimate. No job was conclusively proven closed while still listed active in the 20-employer sample. This does not prove all 1,198 remain open.

The single undated job is D2L `greenhouse:260466`. No future posted timestamps were found. Employer dates for sampled timestamp-bearing postings align with `posted_at`; relative ages use this field rather than ingestion time. The date-only precision defect is B12. Overview last refresh was `2026-09-30T17:39:58.434717Z` (13:39 EDT), a few hours before audit observations, within the configured six-hour cadence. Public overview does not expose per-company failure state; backend scheduler runs and database freshness could not be independently inspected. Source review found failure-aware ingestion safeguards; running live ingestion would violate audit scope.

## Job-detail and employer comparison sample

Twenty distinct employers were opened in production and compared with their exact public employer postings. Additional Thomson Reuters job JREQ201848 confirmed B07. All five available ATS families are covered. Long titles, multiple locations, remote/hybrid jobs, missing salary and lengthy descriptions are represented. Comparison files distinguish employer HTML/structured descriptions, stored API description and rendered UI.

| Sample | Company | ATS | Exact original posting | Job ID |
|---|---|---|---|---|
| 00 | Palantir | lever | [Forward Deployed Infrastructure Engineer, New Grad - US Government](https://jobs.lever.co/palantir/701a9307-0619-45d3-b077-cabe9897cd12) | `lever:701a9307-0619-45d3-b077-cabe9897cd12` |
| 01 | Notion | ashby | [Software Engineer Intern, Mobile (Winter 2027)](https://jobs.ashbyhq.com/notion/2b587e66-deac-421a-a824-9415ba78b5a7) | `ashby:2b587e66-deac-421a-a824-9415ba78b5a7` |
| 02 | OpenAI | ashby | [Data Scientist, Cybersecurity](https://jobs.ashbyhq.com/openai/894ce80d-c587-4ef0-92d2-b16deb9a06b9) | `ashby:894ce80d-c587-4ef0-92d2-b16deb9a06b9` |
| 03 | Replit | ashby | [Staff Site Reliability Engineer](https://jobs.ashbyhq.com/replit/f508992f-5b26-4ab1-816d-d17f121d208b) | `ashby:f508992f-5b26-4ab1-816d-d17f121d208b` |
| 04 | Stripe | greenhouse | [Software Engineer, Early Career — Immediate Start](https://stripe.com/jobs/search?gh_jid=8212517) | `greenhouse:8212517` |
| 05 | Plaid | ashby | [Security Engineer - Platform Security](https://jobs.ashbyhq.com/plaid/bc64da24-0699-4611-8e62-49ffafe2a3e9) | `ashby:bc64da24-0699-4611-8e62-49ffafe2a3e9` |
| 06 | Cohere | ashby | [Software Engineer, Security](https://jobs.ashbyhq.com/cohere/a10a96b5-f772-466d-9297-f021f78ca9c0) | `ashby:a10a96b5-f772-466d-9297-f021f78ca9c0` |
| 07 | PointClickCare | lever | [Senior Machine Learning Systems Engineer (CAD)](https://jobs.lever.co/pointclickcare/150b07cd-04e9-46c4-9015-114498f3798c) | `lever:150b07cd-04e9-46c4-9015-114498f3798c` |
| 08 | Waabi | lever | [Software Engineer, Commercial Software](https://jobs.lever.co/waabi/6bcfed90-b577-4b09-a893-5c07186a1e0f) | `lever:6bcfed90-b577-4b09-a893-5c07186a1e0f` |
| 09 | Scale AI | greenhouse | [Software Engineer, Public Sector - New Grad](https://job-boards.greenhouse.io/scaleai/jobs/4736426005) | `greenhouse:4736426005` |
| 10 | Figma | greenhouse | [Data Engineer Intern (2027)](https://boards.greenhouse.io/figma/jobs/6178851004?gh_jid=6178851004) | `greenhouse:6178851004` |
| 11 | Amazon | amazon | [Software Development Engineer II, Amazon Fulfillment Technologies (AFT) - Workforce Optimization](https://www.amazon.jobs/en/jobs/10561786/software-development-engineer-ii-amazon-fulfillment-technologies-aft-workforce-optimization) | `amazon:10561786` |
| 12 | Coinbase | greenhouse | [Senior Software Engineer, Retail DEX](https://www.coinbase.com/careers/positions/8243517?gh_jid=8243517) | `greenhouse:8243517` |
| 13 | Thomson Reuters | workday | [Lead Software Engineer (SAP ABAP)](https://thomsonreuters.wd5.myworkdayjobs.com/External_Career_Site/job/Canada-Toronto-Ontario/Lead-Software-Engineer--SAP-ABAP-_JREQ203860) | `workday:Lead-Software-Engineer--SAP-ABAP-_JREQ203860` |
| 14 | Sun Life | workday | [Data Scientist](https://sunlife.wd3.myworkdayjobs.com/Experienced-Jobs/job/Toronto-Ontario/Data-Scientist_JR00128241) | `workday:Data-Scientist_JR00128241` |
| 15 | TD | workday | [Data Engineer II (Production Support)](https://td.wd3.myworkdayjobs.com/TD_Bank_Careers/job/Toronto-Ontario/Data-Engineer-II--Prod-Support-_R_1502910-1) | `workday:Data-Engineer-II--Prod-Support-_R_1502910-1` |
| 16 | Wealthsimple | ashby | [Senior Software Developer, Build Platform](https://jobs.ashbyhq.com/wealthsimple/c6dfa59f-cf09-4a11-9e35-a0cf4ab23cd0) | `ashby:c6dfa59f-cf09-4a11-9e35-a0cf4ab23cd0` |
| 17 | Autodesk | workday | [Principal Software Developer](https://autodesk.wd1.myworkdayjobs.com/Ext/job/AMER---Canada---Ontario---OffsiteHome/Principal-Software-Developer_26WD97119-1) | `workday:Principal-Software-Developer_26WD97119-1` |
| 18 | Manulife | workday | [Senior Full Stack Software Engineer - Capital Markets](https://manulife.wd3.myworkdayjobs.com/MFCJH_Jobs/job/Toronto-Ontario/Senior-Full-Stack-Software-Engineer_JR26060496) | `workday:Senior-Full-Stack-Software-Engineer_JR26060496` |
| 19 | CIBC | workday | [Senior Fullstack Developer](https://cibc.wd3.myworkdayjobs.com/search/job/Toronto-ON/Senior-Fullstack-Developer_2613845) | `workday:Senior-Fullstack-Developer_2613845` |

Priority employers absent from the public active inventory: Stability AI, Google, Meta, Apple, Tesla and SpaceX/Starlink. They were not implied to be tested.

**Regression outcomes:** Palantir’s substantial opening, requirements and duties survive in this sample; Notion headings are rendered; sampled description links remain navigable; Stripe does not show the prior duplicate section-heading defect but now loses the standalone deadline (B01). Workday/Amazon opening prose and bare top-level text survive. No “Jump To” section was present in all 20 detail renders. Amazon salary CAD 114,800–191,800 and its accommodation link survive. Links were compared against original destinations, allowing normal absolute-URL resolution and ATS redirects. Stored-to-rendered comparison identifies the Stripe loss and intentional section rearrangements; similarity scores are diagnostic aids, not proof of integrity.

The six sampled Workday structured employer descriptions contain generic company footer prose beyond the job-specific CXS body. Differences in those footers were not misreported as missing responsibilities/benefits without evidence that the source adapter supplied that content. Confirmed job-specific salary loss is B02. Tracking tags and mixed Markdown are B11. Long details remain scrollable; opening/closing modal checks preserve usable navigation.

## Application links

All 20 exact employer source pages returned successful HTTP responses and matched the selected roles; normal redirects were followed. Nine destinations were additionally visited in the browser, including ATS application views, without filling or submitting forms. Saved details: `employer-responses.json`, `apply-browser.json` and `extra-responses.json`.

Stripe’s `gh_jid=8212517` URL redirects to the exact role listing: it is not an unrelated careers search. Figma redirects to its new official board, preserving the role. Coinbase’s locale redirect preserves its role. Some direct scripted ATS application requests returned 403 while normal browser visits succeeded; those are tooling/access restrictions, not proven broken application links.

Across the complete inventory, per-job LinkedIn and Simplify URLs were absent. No Indeed application option was observed. Company social LinkedIn links use company-specific labels; they are not misrepresented as role application links. Disabled/missing primary-link behavior was reviewed in source because no sampled live job lacked both source and apply URLs; runtime missing-link testing remains unperformed.

## Logos and branding

All 59 active companies have verified API logo status. A local audit gallery loaded their actual API assets against light and dark backgrounds: **118 image instances, none broken**. Cards/details were checked across the 20-job sample and additional results. This gallery is an audit artifact, not a production route. Original brand colors were preserved; no global CSS inversion was found. No confirmed wrong company identity, stretching or invisible logo was found in the active sample. Datadog’s purple mark remains recognizable but faint on its dark card; improve the backplate (design recommendation, screenshot `datadog-dark.jpg`).

`ingestion/company_resolver.py:625` uses curated branding; :693 onward discovers Lever, Greenhouse and Ashby branding. Catalog assets can be persisted as bytes and served through `/api/company-logos/<id>` (:935 onward), avoiding reliance on remote hotlinks. This is more than a handful of manual card overrides. However, arbitrary future Workday/Amazon employers do not have equivalent generic discovery and may fall back without a catalog entry. Theme suitability remains partly controlled by company-specific presentation rules. Existing 59 logos cannot prove future unseen logos will be correct. Constructor’s dictionary collision is independently confirmed in B04.

## Design recommendations — separate from confirmed bugs

| Recommendation | Concrete impact and evidence |
|---|---|
| Prioritize Canadian early-career discovery | Only 27 eligible Canadian early-career postings exist; the first 100 Canada recommended results include 99 full-time and one co-op. Add an explicit internship preset or early-career ranking instead of forcing repeated filtering. Current Recommended tooltip accurately describes Canada-first/newest behavior; this is a product recommendation, not incorrect sort evidence. |
| Show the country/location that matched the filter | US primary location plus “+N locations” on a Canada-filtered card makes legitimate Canadian matches look wrong. Highlight the matching Canadian location, retaining the full location list. |
| Reduce detail-header height on narrow screens | At 320px, stacked facts and identity consume substantial screen height before the actual description. Compact facts and place the application CTA near identity; retain the full title and close control. See mobile320-detail-dark.jpg. |
| Give Apply a clearer visual priority | The external application text competes with job facts and long prose. Use a clearly identifiable primary control while retaining its destination label and accessible external-link behavior. |
| Remove redundant Remote labels | Replit cards repeat Remote in both location and workplace facts. Collapse redundant wording without deleting geographic eligibility. |
| Separate actual employer introductions conservatively | Some Greenhouse company intros remain inside About the Job. This is readable and preserves prose; improve hierarchy only when confidently classifiable. B07 is the opposite confirmed mistake. |
| Support small touch controls better | Modal close is around 32px and theme control around 34px. Increase comfortable hit area; do not claim these automatically violate WCAG’s 24px minimum. |
| Improve dark logo backplates | Datadog’s genuine purple mark is low prominence on dark cards. Use a suitable backing rather than changing brand colors or blanket inversion. |
| Reduce initial JS and analytics gating | Build JS is about 736KB (224KB gzip), CSS about 152KB (66KB gzip); build warns about a large chunk. Lazy-load charts and unnecessary font subsets. This is a payload signal, not a measured Core Web Vitals failure. |
| Make per-company refresh problems visible | A single healthy global timestamp cannot show which employers failed or how long their records have gone unverified. Expose last successful refresh and degraded source coverage honestly. |

Typography and spacing are generally readable in sampled desktop/detail views. Theme switches preserve branding; focus outlines were visible. No persistent horizontal overflow was observed at the tested widths. The tablet screenshot was captured during an opening fade; its transient translucency is not classified as a contrast failure.

## Suspected issues requiring more evidence

- Same-title requisitions (70 groups) need employer requisition/location comparison before deduplication; counting them as duplicates now would inflate the findings.
- Stale/closed active records outside the 20 successful sampled employer postings remain possible. Verify a statistically meaningful sample and source refresh provenance before claiming all links are healthy.
- Unknown workplace type could conceal explicit remote/hybrid policies; 749 unknown records need source-level classification review.
- Future company logos, especially new Workday/Amazon employers, need a previously unseen employer fixture and actual asset/theme checks. Current verified flags are not proof of all future visual correctness.
- Large payloads and slower unfiltered API reads deserve profiling. Observed single-request times ranged roughly 0.13–4.26 seconds, with an unfiltered newest request at 4.26 seconds. No repeatable performance regression or memory leak was established from these one-off timings.

## Coverage matrix

| Area | Executed coverage | Outcome / limitation |
|---|---|---|
| Routes/navigation | Root canonical Jobs, /jobs, Stats click and direct refresh, GitHub destination, unknown route; source inventory of dev /logos and /companies | Jobs/Stats work; 404 UI works with HTTP soft-404; dev contact sheet crashes. No saved-jobs feature exists in this checkout. |
| Viewports/themes | 1440×900 both; 1280×720 dark; 768×1024 light; 390×844 light; 320×844 dark, results/details/Stats | No persistent overflow; narrow header/touch recommendations above. Evidence screenshots retained. |
| Search | Company Notion, location Toronto, skill Python, title/content queries; case/whitespace, C++, accented Développement, 1,000-character query, zero query | Python/case-space 622; Notion 7; Toronto/C++ each 235; accent 5; long and zero query 0. Punctuation is literal (Python comma produced a much narrower match), not assumed token-equivalent. |
| Filters | Every visible filter menu; API 37 cases spanning countries, five roles, three workplace types, company, skill, terms, date windows, five sorts; adding/removing/clear | Counts and sampled returned classifications matched; representative Canada + internship =17, internship/entry + remote =0. filter_checks saved; large sets verified in samples up to 100, not every entry for each case. |
| Sorting | Recommended/newest/oldest/company/title API queries and browser menu | First 100 returned jobs independently verified monotonic for newest, oldest, company and title; SQL tie-breaking/null ordering source reviewed. Not exhaustive multi-page tie verification. No salary sort exists, so missing-salary sort is not a supported control. |
| Pagination | First, Next to page2, API offset600, last offset1180 (18 items), out-of-range5000; page999→60; filter reset from later page | Ordinary boundaries/reset work; huge page B10. |
| Race/loading | Rapid Python→Notion→Replit input, then settled result | Final searchbox Replit and nine Replit cards agreed; transient previous cards during debounce observed, not counted as a stale-response bug. Arbitrary reordered network responses and rapid filter races were not force-controlled. |
| URL/history | Actual filter→job→Back→Forward, refresh selected/filtered state, direct sampled IDs, invalid ID, repeated q/unknown sort/unknown parameter/negative page | State retained in exercised flows. Repeated q=Notion&q=Replit chose first; negative page/unknown sort normalized and unknown field removed; canonical /jobs?q=Notion. Invalid-job and huge-page defects above. Scroll behavior checked in sampled flow, not every combination. |
| Details | Twenty employer detail views, five ATS families, one additional TR job | Original/stored/rendered comparisons and full prose/link inspection; B01/B02/B07/B11. |
| Apply | Twenty exact official postings, nine browser destinations | Exact roles/redirects successful; no submissions. LinkedIn/Simplify absent, Indeed absent. |
| Logos | 59 distinct assets × two gallery themes, 20 card/detail employers plus Datadog | No broken active logo; dark Datadog recommendation; local Constructor crash. |
| Accessibility | axe4.11 light/dark populated #root; manual search/card/modal keyboard, dialog labels, Tab wrap, ShiftTab, Escape, restoration, background scroll | B08; modal naming/trap/Escape/restoration and scroll lock worked. Not a full screen-reader audit. |
| Reflow/motion | CSS viewport720×450 as 1440×900 at 200% reflow equivalent; stylesheet reduced-motion rules reviewed | Reflow usable; actual browser200% zoom and runtime reduced-motion preference unavailable, not claimed tested. |
| Failure/recovery | Isolated stats500 and list500, restore fixtures and retry; real404 and422 | B03/B06/B09/B10; local recovery works. No production faults injected. |
| Performance/assets | Bundle sizes/build warning, public response timing, screenshots/fonts/logos, browser console capture | Local crash captured; no confirmed production console crash in normal flows. No Lighthouse, controlled slow-network/offline or measured CLS/Core Web Vitals. |
| Data | All1,198 summaries, unique IDs/URLs, dates/types/countries;20 exact originals | Freshness mismatch and salary omission confirmed; whole-inventory closure accuracy not established. |
| Validation | Existing Python/frontend tests, lint, typecheck/build | Results below; passing tests missed observable defects. |

## Validation results

- Python: **613 passed, 91 skipped, 404 subtests passed**. Database-dependent tests were skipped; this is not database integration validation. One Starlette/httpx deprecation warning.
- Frontend: **13 test files, 232 tests passed**.
- ESLint: passed.
- TypeScript check and Vite production build: passed; large chunk warning retained.
- Production-configured build: passed; deployed JS byte parity verified.
- Files: `pytest.txt`, `frontend-tests.txt`, `lint.txt`, `build.txt`, `build-production-config.txt` under qa-evidence.

## Blocked or not performed

Exact deployment/back-end revision; authenticated scheduler runs and per-company live failure history; database integration tests; live ingestion; full inventory employer closure checks; absent priority employers; runtime missing-application-link behavior; LinkedIn/Simplify per-job controls because no data exists; exact browser version; full screen-reader interaction; actual 200% browser zoom; runtime reduced-motion emulation; controlled slow/offline/reordered requests; exhaustive rapid filter races; Lighthouse/Core Web Vitals and quantitative CLS; measured listener/memory growth over repeated modal use. A production-configured preview origin4173 was CORS-blocked; parity was established statically, and local fixture behavior tested independently. No bypass was attempted.

## Five fixes first, in order

1. **B02: Preserve Lever salaryRange and salaryDescription.** Compensation is core decision information; verify it before backfilling affected records.
2. **B03: Decouple job browsing from analytics success.** A minor widget outage must not disable the site’s purpose.
3. **B04: Remove prototype-key collisions in logo lookup.** Restore a usable development environment and safe unknown-company handling.
4. **B01: Stop deleting meaningful description headings.** Keep the employer’s prominent deadline visible; the equivalent lower requirement currently survives.
5. **B05: Enforce the requested 30-day default and prioritize eligible Canadian early-career jobs.** Reach useful coverage rather than padding the headline count.

Then address stale query results (B06), role/company classification (B07), invalid semantics (B08), unavailable-job handling (B09) and remaining polish. The three P1 findings should be corrected before treating this build as dependable.

## Screenshot index

Representative views are linked here; raw JSON/HTML evidence is retained alongside them.

- [Desktop light Palantir](qa-evidence/palantir-desktop-light.jpg), [desktop dark Notion](qa-evidence/notion-desktop-dark.jpg), [dark Datadog](qa-evidence/datadog-dark.jpg).
- [Laptop detail](qa-evidence/laptop-detail-dark.jpg), [tablet detail (opening fade)](qa-evidence/tablet-detail-light.jpg), [390px detail](qa-evidence/mobile-detail-light.jpg).
- [320px results](qa-evidence/mobile320-results-dark.jpg), [320px details](qa-evidence/mobile320-detail-dark.jpg), [320px Stats](qa-evidence/stats-mobile320-dark.jpg).
- [Empty results](qa-evidence/empty-desktop.jpg), [Canada internship remote empty](qa-evidence/canada-intern-remote.jpg), [desktop Stats](qa-evidence/stats-desktop-light.jpg).
- [Role duties under company](qa-evidence/tr-company-role.jpg), [local development crash](qa-evidence/local-crash.jpg), [analytics500](qa-evidence/stats-failure-blocks-jobs.jpg), [failed query retains old results](qa-evidence/failed-search-old-results.jpg), [huge-page error](qa-evidence/huge-page-error.jpg).
- [All59 logos in both backgrounds](qa-evidence/logos-all59.jpg), [720×450 zoom-equivalent reflow](qa-evidence/zoom-equivalent720x450.jpg).
