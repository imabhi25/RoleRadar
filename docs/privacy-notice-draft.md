# RoleRadar privacy notice (DRAFT, not for publication)

> **Status:** draft for review. Items marked **[CONFIRM]** are facts the author could not verify; they must be
> filled in or removed by the site operator. Questions for a privacy lawyer or adviser are collected at the end
> under "For legal review". Statements about what RoleRadar's code does were checked against the source in
> `frontend/src/analytics.ts` and `frontend/src/components/AnalyticsPrivacy.tsx`. Statements about Google's
> processing describe Google's published documentation and should be re-checked against it before publishing.

**Last updated:** **[CONFIRM: date of publication]**

## Who we are

RoleRadar (`https://roleradar-jobs.vercel.app`) lists software, AI and data jobs from employers' own career pages
in Canada and the United States.

- Operated by: **[CONFIRM: legal name of the individual or organisation running RoleRadar]**
- Location: **[CONFIRM: country and province or state of the operator]**
- Person responsible for personal information: **[CONFIRM: name or title]**, contact
  **[CONFIRM: email address monitored for privacy requests]**

## What we collect

**Without your consent**
- RoleRadar does not ask you to create an account, and does not ask for your name or contact details.
- Your searches and filters are sent to RoleRadar's own server to find matching jobs, and appear in the page
  address. **[CONFIRM: whether the hosting provider (Vercel) or the API keeps request logs that include page
  addresses or IP addresses, and for how long.]**
- Your choice about Analytics is stored in your browser's local storage (`roleradar-analytics-consent`). It stays
  on your device and is not a cookie.
- RoleRadar checks whether job postings are still open by contacting the employer's job board (Ashby, Greenhouse
  or Lever) from your browser. Those services can see your IP address. **[CONFIRM: whether to mention
  this, and which providers. The checks are in `frontend/src/utils/jobLiveness.ts`.]**

**Only if you accept Analytics (Google Analytics 4)**
- The type of page you view: Jobs, Market analytics, Companies, Company profile or Page not found. Never your
  searches, filters, the jobs you open, or company names you type.
- How long you stay, and how far you scroll **[CONFIRM: whether Scrolls is on in Enhanced measurement]**.
- The site that referred you, reduced to its domain (for example `google.com`).
- Browser and device details: type, operating system, screen size and language.
- Your IP address. Google uses it to estimate your approximate location (country, region, city) and, per Google,
  does not log or store it for Google Analytics 4. **[CONFIRM against Google's current documentation.]**
- Two cookies, `_ga` and `_ga_<id>`, containing a random identifier that lets Google recognise repeat visits from
  the same browser. By default they last up to 2 years. **[CONFIRM: cookie expiration setting in GA Admin, if
  changed.]**

Advertising features are off: no Google signals, no ad personalisation, and no advertising cookies.

We do not collect: clicks on links to employers' sites, form entries, or anything that identifies you by name.
This relies on the GA Admin settings listed in `docs/analytics-and-privacy.md`.

## Why

To count visits and understand which parts of RoleRadar are used, so we can improve it. We do not sell personal
information, use it for advertising, or share it beyond the service providers below.

## Your choices

- Analytics is off until you accept. You can accept, decline or change your choice at any time with
  **Privacy & analytics settings** at the bottom of every page.
- If your browser sends Global Privacy Control or Do Not Track, Analytics stays off and you are not asked.
- Withdrawing consent stops Analytics immediately and deletes the Analytics cookies from your browser. Data
  already sent to Google is kept for the retention period below.
- Your choice is remembered for 13 months, or until this notice changes, and then you are asked again.
- Clearing your browser's site data removes your choice; you will be asked again.

## Who processes the data

- **Google LLC** (Google Analytics), as our service provider. Google may process and store the data outside
  Canada, including in the United States, where it may be accessible to authorities under local law.
  [How Google uses information from sites that use its services](https://policies.google.com/technologies/partner-sites).
  **[CONFIRM: that the Google Analytics data processing terms have been accepted in GA Admin (Admin → Account
  settings).]**
- **Vercel Inc.** hosts the site. **[CONFIRM: Vercel's role and data location for this project; whether its
  Web Analytics or Speed Insights are enabled (they are not referenced in the code).]**
- **[CONFIRM: any other provider, such as the API's database host.]**

## How long we keep it

- Google Analytics event data: **[CONFIRM: the retention set in GA Admin → Data retention, for example 2 months]**.
- Aggregated reports may be kept longer. **[CONFIRM]**

## Your rights

Depending on where you live, you may have the right to access, correct or delete personal information about you,
to withdraw consent, and to complain to a regulator. For example:
- Quebec: Commission d'accès à l'information;
- rest of Canada: Office of the Privacy Commissioner of Canada;
- California: California Privacy Protection Agency.

Because Analytics uses a random identifier rather than your name, we may be unable to find your data unless you
can provide the identifier from your `_ga` cookie. To make a request, contact **[CONFIRM: privacy contact]**.
**[CONFIRM: response time you commit to.]**

## Changes

We will update this notice when what we collect changes, and ask for Analytics consent again.

---

## For legal review (remove before publishing)

1. **Who is the operator,** and does Quebec's Law 25 apply (for example, an operator in Quebec, or serving Quebec
   residents)? If so: a designated person in charge of personal information, published contact details, a
   privacy-impact assessment for transfers outside Quebec (Google, US), and governance policies.
2. **Is opt-in for everyone the intended standard?** It meets Law 25's "off by default" rule for technologies
   that can identify or profile, and GDPR/UK-GDPR prior-consent rules if EU or UK visitors are served.
   PIPEDA and most US state laws would allow notice plus opt-out for non-sensitive analytics.
3. **Is a 13-month consent lifetime appropriate?** It follows common European regulator guidance. Law 25 has no
   fixed figure.
4. **Does the localStorage consent record need disclosing** as a "technology" under Law 25 or as a
   strictly-necessary item under ePrivacy rules? It is drafted as disclosed but not requiring consent.
5. **Live job checks** send visitors' IP addresses to third-party job boards from the browser without consent.
   Is disclosure enough, or should the checks move server-side?
6. **Hosting and API logs:** do Vercel or the API keep IP addresses or full page addresses (which contain search
   terms)? If so, they need to be disclosed with a retention period.
7. **Is "approximate location from IP" accurately described,** and is relying on Google's statement that it does
   not store IP addresses acceptable?
8. **Google's terms:** confirm the Analytics data processing terms are accepted, and whether Google's EU user
   consent policy applies (EEA or UK visitors).
9. **Children:** is any statement needed? (The site is aimed at job seekers; no age gate.)
10. **Access requests** for pseudonymous Analytics data: confirm the drafted approach (identifier needed) is acceptable.
