# Candidate Employers Coverage Investigation Report

**Date:** October 2, 2026
**Subject:** Technical investigation and connection status of 35 candidate employers for Jobber ingestion coverage expansion.

---

## 1. Executive Summary & Verification Rules

Jobber maintains strict ingestion standards:
- **No Synthetic Data:** Every job must originate from an authentic employer career feed or verified ATS endpoint. No placeholder or fake jobs are ever introduced.
- **Scope Discipline:** Only software engineering, data, and technical roles matching Jobber's eligibility predicates are ingested.
- **Company Tracking vs. Active Postings:** A company being registered in the system is distinct from having active matching vacancies in a given geographic or temporal window.
- **Branding & Logo Invariant:** Every connected employer requires an authentic brand mark verified and served via `frontend/public/logos/` and cataloged in `ingestion/company_resolver.py`.
- **Distinct Statuses:** Connected sources are clearly separated from audited feeds pending batch rollout, enterprise portals requiring custom adapters, and excluded non-SWE sources.

Below is the verified audit and connection status of all 35 candidate employers investigated.

---

## 2. Connected & Pipeline-Integrated Sources (3 Employers)

These employers have been fully verified, registered in `config/target_companies.json`, provisioned with official SVG brand marks in `frontend/public/logos/`, and wired into `ingestion/company_resolver.py` and `frontend/src/utils/companyLogos.ts`:

| Employer | ATS Platform | Board Identifier | Jobs Fetched | SWE Accepted | Eligible (US/CA) | Canada Jobs | Connection Status |
|:---|:---|:---|---:|---:|---:|---:|:---|
| **Okta** | Greenhouse | `okta` | 368 | 137 | 62 | 34 | **Connected** (`target_companies.json`, `okta.svg`) |
| **Lyft** | Greenhouse | `lyft` | 192 | 64 | 58 | 36 | **Connected** (`target_companies.json`, `lyft.svg`) |
| **Braze** | Greenhouse | `braze` | 349 | 65 | 58 | 14 | **Connected** (`target_companies.json`, `braze.svg`) |

Dry-run sync verified clean parsing with 0 parse errors across all three feeds.

---

## 3. Audited Candidate Feeds for Future Batch Rollout (12 Employers)

These employers operate standard, publicly accessible API boards (Greenhouse, Ashby, Lever) with active engineering roles. Their endpoints have been verified and audited for future scheduled batch connection:

| Employer | ATS Platform | Board Slug / Endpoint | Active Jobs (Total) | Scope & Canadian / US Relevance |
|:---|:---|:---|---:|:---|
| **Harvey** | Ashby | `harvey` | 326 | Legal AI platform; high-volume AI/SWE hiring. |
| **Cerebras** | Ashby | `cerebras` | 117 | AI hardware and systems engineering. |
| **AppDirect** | Greenhouse | `appdirect` | 69 | B2B subscription commerce platform (Montreal, Toronto, Calgary tech hubs). |
| **Telesat** | Lever | `telesat` | 54 | Canadian satellite communications leader (Ottawa, ON); network & software roles. |
| **Later** | Greenhouse | `later` | 42 | Canadian social media management platform (Vancouver, Toronto). |
| **Litmus** | Ashby | `litmus` | 28 | Email testing platform; remote-first software teams. |
| **Adaptive Financial Consulting** | Greenhouse | `adaptivefinancialconsulting` | 23 | Capital markets software consultancy (Toronto, Montreal, US). |
| **Solink** | Ashby | `solink` | 22 | Canadian cloud video surveillance leader (Ottawa, ON). |
| **HeyGen** | Greenhouse | `heygen` | 22 | AI video synthesis; engineering & ML roles. |
| **Scribd** | Ashby | `scribdinc` | 12 | Digital reading platform; remote engineering positions. |
| **Vasco** | Ashby | `vasco` | 4 | B2B fintech software. |
| **Spare Labs** | Ashby | `spare` | 2 | Canadian transit tech platform (Vancouver, BC). |

---

## 4. Enterprise ATS Requiring Tenant Adapters (14 Employers)

These enterprise employers host active software vacancies but use enterprise ATS systems (Workday, SuccessFactors, Phenom, Taleo) requiring tenant-specific session handling and pagination:

| Employer | Platform | Career Portal Endpoint | Notes |
|:---|:---|:---|:---|
| **Workday** | Workday | `workday.wd5.myworkdayjobs.com/Workday` | Enterprise Workday tenant. Large Canadian presence (Victoria, Vancouver). |
| **Marvell Technology** | Workday | `marvell.wd1.myworkdayjobs.com/MarvellCareers` | Semiconductor & data infrastructure. |
| **Altera** | Workday / Intel | `intel.wd1.myworkdayjobs.com/External` | FPGA business unit (formerly Intel PSG). |
| **Expedia Group** | Workday | `expedia.wd5.myworkdayjobs.com` | Travel tech platform. Active US/Canada engineering hubs. |
| **Foresters Financial** | Workday | `foresters.wd3.myworkdayjobs.com` | Canadian financial services (Toronto, ON). |
| **GE Vernova** | Phenom / Workday | `jobs.gevernova.com` | Energy transition technology. |
| **eBay** | Workday | `ebay.wd5.myworkdayjobs.com` | Global e-commerce platform. |
| **Intuit** | Workday | `jobs.intuit.com` | Fintech software (Toronto hub - TurboTax, QuickBooks). |
| **Equifax** | Workday | `equifax.wd5.myworkdayjobs.com` | Credit analytics & software. |
| **Citi** | Workday | `citi.wd5.myworkdayjobs.com` | Global financial institution; technology centres in Mississauga, ON. |
| **Warner Bros. Discovery** | Workday | `warnermediacareers.com` | Streaming & digital technology engineering. |
| **NTT Data** | SuccessFactors | `careers.services.global.ntt` | Global IT and enterprise solutions. |
| **Nokia** | Taleo / Phenom | `nokia.com/about-us/careers` | Telecom equipment & software (Ottawa, ON campus). |
| **BGIS** | Dayforce / Ceridian | `bgis.com/ca/careers` | Real estate technology and facilities management. |

---

## 5. Inaccessible, Non-Tech, or Out-of-Scope Exclusions (6 Employers)

These candidates were investigated and excluded from ingestion based on direct probe results:

1. **Tubi (`tubi` on Greenhouse):**
   - *Status:* Probed active board. Contains only 1 active listing: "Tubi College Brand Manager" (campus marketing ambassador).
   - *Reason for exclusion:* Zero active software engineering, product, or data roles.
2. **SALT XC (`saltxc` on Greenhouse):**
   - *Status:* Advertising and experiential marketing agency (41 non-technical listings).
   - *Reason for exclusion:* No active software engineering, backend, frontend, or data infrastructure roles.
3. **Flynn Companies (`flynncompanies` on Lever):**
   - *Status:* Commercial roofing and architectural building envelope contractor (175 non-technical listings).
   - *Reason for exclusion:* Postings are construction trades, field roofing, and sheet metal fabrication; zero software engineering positions.
4. **Rivian and Volkswagen Group Technologies:**
   - *Status:* Joint venture architecture.
   - *Reason for exclusion:* No dedicated standalone ATS board. Requisition pipelines are handled individually through Rivian and Volkswagen Group parent entities.
5. **Evolving Web:**
   - *Status:* Web development and Drupal agency (Montreal, QC).
   - *Reason for exclusion:* Uses BambooHR portal (`evolvingweb.bamboohr.com`) with Cloudflare anti-bot challenge and no public unauthenticated JSON feed.
6. **exacare ai:**
   - *Status:* Seed-stage healthcare AI startup.
   - *Reason for exclusion:* No dedicated public job board or active ATS feed at this time.
