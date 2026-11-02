import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import sanitizeHtml from 'sanitize-html';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const API_BASE = 'https://roleradar-api.vercel.app';

/**
 * Restrictive allow-list configuration for sanitize-html.
 * Allows safe semantic typography and layout tags while eliminating
 * scripts, styles, iframes, objects, forms, inline event handlers, and unsafe URLs.
 */
export const RESTRICTIVE_SANITIZER_CONFIG = {
  allowedTags: [
    'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'strong', 'b', 'em', 'i', 'u', 's', 'strike',
    'blockquote', 'code', 'pre', 'div', 'span', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a'
  ],
  allowedAttributes: {
    a: ['href', 'target', 'rel', 'title']
  },
  allowedSchemes: ['http', 'https', 'mailto'],
  allowedSchemesByTag: {
    a: ['http', 'https', 'mailto']
  },
  allowProtocolRelative: false,
  transformTags: {
    a: (_tagName, attribs) => ({
      tagName: 'a',
      attribs: {
        ...attribs,
        target: '_blank',
        rel: 'noopener noreferrer'
      }
    })
  }
};

/**
 * Sanitizes untrusted job descriptions into safe, sanitized HTML using
 * the maintained, server-compatible `sanitize-html` library with a restrictive allow-list.
 */
export function sanitizeJobHtml(rawHtml) {
  if (!rawHtml || typeof rawHtml !== 'string') {
    return '<p>No description provided.</p>';
  }

  const clean = sanitizeHtml(rawHtml, RESTRICTIVE_SANITIZER_CONFIG).trim();
  const textContent = clean.replace(/<[^>]*>/g, '').trim();
  if (!textContent) {
    return '<p>No description provided.</p>';
  }

  return clean;
}

/**
 * Validates untrusted Apply URLs to ensure they only use http: or https:,
 * preventing javascript:, data:, vbscript:, or malformed protocols.
 */
export function validateApplyUrl(url) {
  if (!url || typeof url !== 'string') return null;
  const trimmed = url.trim();
  if (trimmed.length < 10 || /[\s\r\n\t<>"'`]/.test(trimmed)) {
    return null;
  }
  if (!/^https?:\/\//i.test(trimmed)) {
    return null;
  }
  try {
    const parsed = new URL(trimmed);
    if ((parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.hostname && parsed.hostname.includes('.')) {
      return parsed.href;
    }
  } catch {
    return null;
  }
  return null;
}

/**
 * Reads built Vite index.html to obtain the exact, active JavaScript and CSS filenames
 * dynamically without hardcoding chunk hashes.
 */
let cachedTemplate = null;
let cachedTemplateTime = 0;

export function getHtmlShellTemplate() {
  const now = Date.now();
  if (cachedTemplate && now - cachedTemplateTime < 60_000) {
    return cachedTemplate;
  }

  // Look for dist/index.html in root or relative to api folder
  const candidatePaths = [
    resolve(__dirname, '../dist/index.html'),
    resolve(__dirname, '../../dist/index.html'),
    resolve(process.cwd(), 'dist/index.html'),
    resolve(process.cwd(), 'frontend/dist/index.html')
  ];

  for (const p of candidatePaths) {
    if (existsSync(p)) {
      try {
        const content = readFileSync(p, 'utf8');
        cachedTemplate = content;
        cachedTemplateTime = now;
        return content;
      } catch (err) {
        console.warn('Failed reading template from', p, err);
      }
    }
  }

  // Graceful fallback if dist is unavailable (e.g. during local tests)
  return `<!doctype html>
<html lang="en" data-theme="light">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <!-- HEAD_INJECTIONS -->
  </head>
  <body>
    <div id="root"><!-- BODY_INJECTIONS --></div>
  </body>
</html>`;
}

export async function fetchJob(jobId, apiBase = API_BASE) {
  try {
    const url = `${apiBase}/api/jobs/${encodeURIComponent(jobId)}`;
    const res = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(8000)
    });
    if (res.status === 200) {
      const job = await res.json();
      return { status: 200, job };
    }
    // Return 404, 410, 500, etc. directly
    return { status: res.status, job: null };
  } catch (err) {
    console.warn('fetchJob failed for', jobId, err);
    return { status: 503, job: null };
  }
}

export function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function safeJsonLdString(obj) {
  return JSON.stringify(obj, null, 2)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

function mapEmploymentType(roleType) {
  if (!roleType) return undefined;
  const n = String(roleType).trim().toLowerCase();
  if (n === 'full_time') return 'FULL_TIME';
  if (n === 'part_time') return 'PART_TIME';
  if (n === 'contract' || n === 'contractor') return 'CONTRACTOR';
  if (n === 'temporary') return 'TEMPORARY';
  if (n === 'internship' || n === 'co_op') return 'INTERN';
  return undefined;
}

function mapSalaryUnit(interval) {
  if (!interval) return undefined;
  const norm = String(interval).trim().toLowerCase();
  if (/(?:yr|year|annual|annually|p\.?a\.?)/.test(norm)) return 'YEAR';
  if (/(?:mo|month|monthly)/.test(norm)) return 'MONTH';
  if (/(?:wk|week|weekly)/.test(norm)) return 'WEEK';
  if (/(?:day|daily)/.test(norm)) return 'DAY';
  if (/(?:hr|hour|hourly)/.test(norm)) return 'HOUR';
  return undefined;
}

function periodOf(text) {
  const t = String(text || '');
  if (/year|annual|\byr\b|\bp\.?a\.?\b/i.test(t)) return 'year';
  if (/month|\bmo\b/i.test(t)) return 'month';
  if (/week|\bwk\b/i.test(t)) return 'week';
  if (/\bday\b|daily/i.test(t)) return 'day';
  if (/hour|\bhr\b/i.test(t)) return 'hour';
  return '';
}

export function buildSchemaPlace(locStr, defaultCountry = '') {
  if (!locStr) return null;
  const clean = String(locStr).replace(/\s+/g, ' ').trim();
  const parts = clean.split(/[,·]/).map((p) => p.trim()).filter(Boolean);
  const address = {
    '@type': 'PostalAddress'
  };

  const isCountry = (s) => /^(?:Canada|United States|United Kingdom|USA|US|UK)$/i.test(s);
  const normalizeCountry = (s) => {
    if (/^(?:United States|USA|US)$/i.test(s)) return 'United States';
    if (/^(?:United Kingdom|UK)$/i.test(s)) return 'United Kingdom';
    if (/^Canada$/i.test(s)) return 'Canada';
    return s;
  };

  if (parts.length === 1) {
    if (isCountry(parts[0])) {
      address.addressCountry = normalizeCountry(parts[0]);
    } else {
      address.addressLocality = parts[0];
      if (defaultCountry) address.addressCountry = normalizeCountry(defaultCountry);
    }
  } else if (parts.length === 2) {
    address.addressLocality = parts[0];
    if (isCountry(parts[1])) {
      address.addressCountry = normalizeCountry(parts[1]);
    } else {
      address.addressRegion = parts[1];
      if (defaultCountry) address.addressCountry = normalizeCountry(defaultCountry);
    }
  } else if (parts.length === 3) {
    address.addressLocality = parts[0];
    address.addressRegion = parts[1];
    address.addressCountry = normalizeCountry(parts[2]);
  } else if (parts.length >= 4) {
    address.streetAddress = parts.slice(0, parts.length - 3).join(', ');
    address.addressLocality = parts[parts.length - 3];
    address.addressRegion = parts[parts.length - 2];
    address.addressCountry = normalizeCountry(parts[parts.length - 1]);
  }

  return {
    '@type': 'Place',
    address
  };
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function formatAmountPatterns(val) {
  if (typeof val !== 'number' || isNaN(val) || val <= 0) return [];
  const raw = String(val);
  const withCommas = raw.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const res = [escapeRegex(withCommas), escapeRegex(raw)];
  if (val >= 1000 && val % 1000 === 0) {
    res.push(escapeRegex(String(val / 1000)) + '\\s*[kK]');
  } else if (val >= 1000) {
    res.push(escapeRegex((val / 1000).toFixed(1)) + '\\s*[kK]');
  }
  return res;
}

function periodFromKeyword(word) {
  const w = String(word || '').toLowerCase();
  if (/year|annual|annually|yearly|yr|p\.?a\.?/i.test(w)) return 'year';
  if (/month|monthly|mo/i.test(w)) return 'month';
  if (/week|weekly|wk/i.test(w)) return 'week';
  if (/day|daily/i.test(w)) return 'day';
  if (/hour|hourly|hr/i.test(w)) return 'hour';
  return undefined;
}

export function extractTiedPeriod(evidence, compensation) {
  if (!evidence || typeof evidence !== 'string') return undefined;
  if (!compensation || typeof compensation !== 'object') return undefined;

  const min = typeof compensation.min === 'number' && compensation.min > 0 ? compensation.min : undefined;
  const max = typeof compensation.max === 'number' && compensation.max > 0 ? compensation.max : undefined;
  if (min === undefined && max === undefined) return undefined;

  const minPatterns = min !== undefined ? formatAmountPatterns(min) : [];
  const maxPatterns = max !== undefined ? formatAmountPatterns(max) : [];

  let amountRegexStr;
  if (minPatterns.length > 0 && maxPatterns.length > 0 && min !== max) {
    amountRegexStr = '(?:' + minPatterns.join('|') + ')[^\\w\\d\\n\\r]{1,25}?(?:' + maxPatterns.join('|') + ')';
  } else if (minPatterns.length > 0) {
    amountRegexStr = '(?:' + minPatterns.join('|') + ')';
  } else {
    amountRegexStr = '(?:' + maxPatterns.join('|') + ')';
  }

  const periodWordPattern =
    '(?:year|annual|annually|yearly|yr|p\\.?a\\.?|month|monthly|mo|week|weekly|wk|day|daily|hour|hourly|hr)';

  // 1. Period directly following the matching amount:
  const postRegex = new RegExp(
    amountRegexStr +
      '(?:\\s*(?:[A-Za-z]{3}|[\\$£€]))*\\s*(?:(?:\\/|\\bper\\b|\\ba\\b)\\s*)?(\\b' +
      periodWordPattern +
      '\\b)',
    'i'
  );

  // 2. Period directly preceding the matching amount:
  const preRegex = new RegExp(
    '(?:\\bper\\s+|\\ba\\s+)?(\\b' +
      periodWordPattern +
      '\\b)\\s*(?:base\\s*)?(?:pay|salary|rate|range|compensation)?\\s*(?:of|:|is)?(?:\\s*(?:[A-Za-z]{3}|[\\$£€]))*\\s*' +
      amountRegexStr,
    'i'
  );

  const postMatch = evidence.match(postRegex);
  if (postMatch && postMatch[1]) {
    return periodFromKeyword(postMatch[1]);
  }

  const preMatch = evidence.match(preRegex);
  if (preMatch && preMatch[1]) {
    return periodFromKeyword(preMatch[1]);
  }

  return undefined;
}

function rangeMatchesSalary(r, comp) {
  if (!r || typeof r !== 'object') return false;
  if (typeof r.interval !== 'string' || !r.interval.trim()) return false;

  const hasMin = typeof comp.min === 'number' && comp.min > 0;
  const hasMax = typeof comp.max === 'number' && comp.max > 0;
  if (!hasMin && !hasMax) return false;

  if (hasMin && r.min !== comp.min) return false;
  if (hasMax && r.max !== comp.max) return false;
  if (r.min !== undefined && r.min !== comp.min) return false;
  if (r.max !== undefined && r.max !== comp.max) return false;

  const compCurr = String(comp.currency || '').trim().toUpperCase();
  const rangeCurr = String(r.currency || '').trim().toUpperCase();
  if (compCurr && rangeCurr && compCurr !== rangeCurr) return false;

  return true;
}

export function resolveMatchingSalaryInterval(compensation) {
  if (!compensation || typeof compensation !== 'object') return undefined;

  // 1. Direct top-level interval
  if (typeof compensation.interval === 'string' && compensation.interval.trim()) {
    return compensation.interval.trim();
  }

  // 2. Matching range from compensation.ranges (amounts and currency must match)
  // There is NO single-range fallback: the range must match the salary being marked up.
  if (Array.isArray(compensation.ranges) && compensation.ranges.length > 0) {
    const matchingRange = compensation.ranges.find((r) => rangeMatchesSalary(r, compensation));
    if (matchingRange && typeof matchingRange.interval === 'string') {
      return matchingRange.interval.trim();
    }
  }

  // 3. Conservative extraction from compensation.evidence
  // Omit salary markup unless the pay period is clearly and unambiguously tied to the matching amount.
  if (typeof compensation.evidence === 'string' && compensation.evidence.trim()) {
    if (/multiple ranges/i.test(String(compensation.compensationTierSummary || ''))) {
      return undefined;
    }
    const tied = extractTiedPeriod(compensation.evidence, compensation);
    if (tied) return tied;
  }

  return undefined;
}

export function buildBaseSalary(comp) {
  if (!comp || typeof comp !== 'object' || comp.validation) return undefined;

  if (Array.isArray(comp.summaryComponents) && comp.summaryComponents.length > 0) {
    for (const c of comp.summaryComponents) {
      if (!c || typeof c !== 'object') continue;
      const cType = String(c.compensationType || '');
      if (!/^(?:Salary|BaseSalary|Hourly|Wage)$/i.test(cType) && c.compensationType) continue;
      const currency = String(c.currencyCode || '').trim().toUpperCase();
      const unitText = mapSalaryUnit(String(c.interval || ''));
      const min = typeof c.minValue === 'number' && c.minValue > 0 ? c.minValue : undefined;
      const max = typeof c.maxValue === 'number' && c.maxValue > 0 ? c.maxValue : undefined;
      if (currency && unitText && (min !== undefined || max !== undefined)) {
        if (min !== undefined && max !== undefined && min > max) continue;
        return {
          '@type': 'MonetaryAmount',
          currency,
          value: {
            '@type': 'QuantitativeValue',
            ...(min !== undefined && max !== undefined && min === max
              ? { value: min }
              : {
                  ...(min !== undefined ? { minValue: min } : {}),
                  ...(max !== undefined ? { maxValue: max } : {})
                }),
            unitText
          }
        };
      }
    }
  }

  const min = typeof comp.min === 'number' && comp.min > 0 ? comp.min : undefined;
  const max = typeof comp.max === 'number' && comp.max > 0 ? comp.max : undefined;
  const currency = String(comp.currency || '').trim().toUpperCase();
  const rawInterval = resolveMatchingSalaryInterval(comp);
  const unitText = mapSalaryUnit(rawInterval);

  if (currency && unitText && (min !== undefined || max !== undefined)) {
    if (min !== undefined && max !== undefined && min > max) return undefined;
    return {
      '@type': 'MonetaryAmount',
      currency,
      value: {
        '@type': 'QuantitativeValue',
        ...(min !== undefined && max !== undefined && min === max
          ? { value: min }
          : {
              ...(min !== undefined ? { minValue: min } : {}),
              ...(max !== undefined ? { maxValue: max } : {})
            }),
        unitText
      }
    };
  }

  return undefined;
}

export function generateJobPostingLdJson(job, siteUrl = 'https://roleradar-jobs.vercel.app') {
  if (!job || !job.title || !job.company || !job.description || !job.posted_at) return null;
  const title = String(job.title).trim();
  const company = String(job.company).trim();
  const dateObj = new Date(job.posted_at);
  if (isNaN(dateObj.getTime())) return null;

  const hiringOrg = {
    '@type': 'Organization',
    name: company
  };
  if (job.company_website_url) hiringOrg.sameAs = job.company_website_url;
  if (job.company_logo_url) {
    hiringOrg.logo = job.company_logo_url.startsWith('http')
      ? job.company_logo_url
      : `${siteUrl}${job.company_logo_url}`;
  }

  const schema = {
    '@context': 'https://schema.org',
    '@type': 'JobPosting',
    title,
    description: job.description,
    datePosted: dateObj.toISOString(),
    hiringOrganization: hiringOrg,
    identifier: {
      '@type': 'PropertyValue',
      name: company,
      value: job.job_id
    }
  };

  const empType = mapEmploymentType(job.role_type);
  if (empType) schema.employmentType = empType;

  // Workplace / Remote eligibility:
  // Google requires applicantLocationRequirements whenever jobLocationType is TELECOMMUTE.
  // Omitting TELECOMMUTE must not make a remote-only job look office-based.
  // If the source doesn't establish applicant locations or a genuine office-work option,
  // omit the JobPosting markup rather than inventing details or misrepresenting the job.
  const workplace = (job.workplace_type || '').toLowerCase();
  const isRemoteOnly = workplace === 'remote';

  let verifiedApplicantCountries = null;
  if (Array.isArray(job.applicant_location_requirements) && job.applicant_location_requirements.length > 0) {
    const countries = job.applicant_location_requirements
      .map((c) => String(c).trim())
      .filter((c) => /^(?:Canada|United States|United Kingdom)$/i.test(c));
    if (countries.length > 0) {
      verifiedApplicantCountries = countries;
    }
  }

  if (isRemoteOnly) {
    if (verifiedApplicantCountries && verifiedApplicantCountries.length > 0) {
      schema.jobLocationType = 'TELECOMMUTE';
      schema.applicantLocationRequirements =
        verifiedApplicantCountries.length === 1
          ? { '@type': 'Country', name: verifiedApplicantCountries[0] }
          : verifiedApplicantCountries.map((c) => ({ '@type': 'Country', name: c }));
    } else {
      // Remote-only job with no verified applicant locations and no genuine office-work option.
      // Do not invent applicant locations, and do not emit a misleading office-based JobPosting.
      return null;
    }
  } else if (verifiedApplicantCountries && verifiedApplicantCountries.length > 0) {
    schema.jobLocationType = 'TELECOMMUTE';
    schema.applicantLocationRequirements =
      verifiedApplicantCountries.length === 1
        ? { '@type': 'Country', name: verifiedApplicantCountries[0] }
        : verifiedApplicantCountries.map((c) => ({ '@type': 'Country', name: c }));
  }

  // Job / office locations: mapped to jobLocation (where the employer's offices are).
  // Per Google Search Central guidelines for 100% remote jobs:
  // "Do not add the jobLocation property". Only on-site and hybrid jobs specify physical jobLocation.
  if (!isRemoteOnly) {
    if (Array.isArray(job.locations) && job.locations.length > 0) {
      const places = job.locations
        .filter((l) => l && (l.location || l.raw_location))
        .map((l) => buildSchemaPlace(l.location || l.raw_location, l.country || job.country || ''))
        .filter(Boolean);
      if (places.length === 1) schema.jobLocation = places[0];
      else if (places.length > 1) schema.jobLocation = places;
    } else if (job.location) {
      const place = buildSchemaPlace(job.location, job.country || '');
      if (place) schema.jobLocation = place;
    }

    // Non-remote jobs require at least one physical location
    if (!schema.jobLocation) {
      return null;
    }
  }

  const salary = buildBaseSalary(job.compensation);
  if (salary) schema.baseSalary = salary;

  return schema;
}

export function renderVisibleJobHtml(job) {
  const company = escapeHtml(job.company);
  const title = escapeHtml(job.title);
  const location = escapeHtml(job.location || job.country || 'Location unspecified');
  const validApply = validateApplyUrl(job.company_apply_url) || validateApplyUrl(job.source_url);
  const applyHref = validApply ? escapeHtml(validApply) : '#';
  const desc = sanitizeJobHtml(job.description);

  return `
    <div class="roleradar-server-job-detail" style="max-width: 900px; margin: 0 auto; padding: 24px; font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif;">
      <nav style="margin-bottom: 24px;">
        <a href="/jobs" style="color: #2563eb; text-decoration: none; font-size: 14px; font-weight: 500;">&larr; Back to all jobs</a>
      </nav>
      <header style="border-bottom: 1px solid rgba(255, 255, 255, 0.1); padding-bottom: 20px; margin-bottom: 24px;">
        <div style="font-size: 16px; color: #94a3b8; font-weight: 600; margin-bottom: 4px;">${company}</div>
        <h1 style="font-size: 28px; line-height: 1.25; margin: 0 0 12px 0;">${title}</h1>
        <div style="font-size: 14px; color: #64748b; margin-bottom: 16px;">
          <span>📍 ${location}</span>
          ${job.workplace_type ? `<span style="margin-left: 12px;">• ${escapeHtml(job.workplace_type)}</span>` : ''}
          ${job.role_type ? `<span style="margin-left: 12px;">• ${escapeHtml(job.role_type.replace('_', ' '))}</span>` : ''}
        </div>
        ${validApply
          ? `<a href="${applyHref}" target="_blank" rel="noopener noreferrer" style="display: inline-block; background-color: #2563eb; color: #ffffff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 15px;">Apply on company site &nearr;</a>`
          : ''}
      </header>
      <section class="job-description" style="line-height: 1.6; font-size: 15px;">
        ${desc}
      </section>
    </div>
  `;
}

export default async function handler(req, res) {
  const host = req.headers['host'] || 'roleradar-jobs.vercel.app';
  const protocol = req.headers['x-forwarded-proto'] || 'https';
  const siteUrl = `${protocol}://${host}`;

  const url = new URL(req.url, siteUrl);
  // Match /jobs/:jobId, ?job=:jobId, or ?jobId=:jobId (from Vercel rewrites)
  const matchedPath = req.headers['x-matched-path'] || url.pathname;
  const pathParts = matchedPath.split('/').filter(Boolean);
  const jobId =
    pathParts.length >= 2 && pathParts[0] === 'jobs'
      ? decodeURIComponent(pathParts.slice(1).join('/'))
      : (url.searchParams.get('jobId') || url.searchParams.get('job'));

  if (!jobId) {
    res.statusCode = 302;
    res.setHeader('Location', '/');
    res.end();
    return;
  }

  try {
    const { status, job } = await fetchJob(jobId);

    // 1. Distinction: Expired or nonexistent jobs (404/410, or is_active: false, status: closed, expired: true) -> true HTTP 404 + noindex
    if (
      status === 404 ||
      status === 410 ||
      job?.is_active === false ||
      job?.status === 'closed' ||
      job?.expired === true
    ) {
      res.statusCode = 404;
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
      res.setHeader('X-Robots-Tag', 'noindex, nofollow');
      res.end(`<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="robots" content="noindex, nofollow" />
  <title>Job No Longer Available — RoleRadar</title>
</head>
<body style="font-family: sans-serif; padding: 40px; text-align: center; background-color: #0f172a; color: #f8fafc;">
  <h1>Job No Longer Available</h1>
  <p>This position is closed or has expired.</p>
  <p><a href="/jobs" style="color: #38bdf8;">Browse current openings on RoleRadar &rarr;</a></p>
</body>
</html>`);
      return;
    }

    // 2. Distinction: Temporary upstream or internal server errors (5xx, etc.) -> 503 Service Unavailable, no noindex!
    if (status >= 500 || !job) {
      res.statusCode = 503;
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
      res.setHeader('Retry-After', '60');
      res.end(`<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Service Temporarily Unavailable — RoleRadar</title>
</head>
<body style="font-family: sans-serif; padding: 40px; text-align: center; background-color: #0f172a; color: #f8fafc;">
  <h1>Service Temporarily Unavailable</h1>
  <p>We are temporarily unable to retrieve this job posting. Please try again shortly.</p>
  <p><a href="/jobs" style="color: #38bdf8;">Return to jobs &rarr;</a></p>
</body>
</html>`);
      return;
    }

    // 3. Successful job fetch -> 200 OK with dynamic assets, visible body & safe JSON-LD
    const SCRIPT_ID = 'role-radar-job-posting-ld-json';
    const CANONICAL_ID = 'role-radar-canonical-link';

    const ldJson = generateJobPostingLdJson(job, siteUrl);
    const jsonLdScript = ldJson
      ? `<script id="${SCRIPT_ID}" type="application/ld+json">\n${safeJsonLdString(ldJson)}\n</script>`
      : '';

    const canonicalUrl = `${siteUrl}/jobs/${encodeURIComponent(job.job_id)}`;
    const pageTitle = `${escapeHtml(job.title)} at ${escapeHtml(job.company)} — RoleRadar`;
    const pageDesc = escapeHtml(
      `Apply for ${job.title} at ${job.company} in ${job.location || job.country || 'Remote'}. Find software and AI jobs on RoleRadar.`
    );

    const headInjections = `
    <title>${pageTitle}</title>
    <meta name="description" content="${pageDesc}" />
    <link id="${CANONICAL_ID}" rel="canonical" href="${canonicalUrl}" />
    <meta property="og:site_name" content="RoleRadar" />
    <meta property="og:title" content="${pageTitle}" />
    <meta property="og:description" content="${pageDesc}" />
    <meta property="og:url" content="${canonicalUrl}" />
    <meta property="og:type" content="website" />
    ${jsonLdScript}
    `;

    const visibleBody = renderVisibleJobHtml(job);

    const template = getHtmlShellTemplate();

    // Strip static shell title, meta description, and og tags to prevent duplicate meta tags
    const cleanTemplate = template
      .replace(/<title>.*?<\/title>/gis, '')
      .replace(/<meta\s+name=["']description["'][^>]*>/gis, '')
      .replace(/<meta\s+property=["']og:[^"']+["'][^>]*>/gis, '');

    let renderedHtml = '';
    if (cleanTemplate.includes('<!-- HEAD_INJECTIONS -->')) {
      renderedHtml = cleanTemplate
        .replace('<!-- HEAD_INJECTIONS -->', headInjections)
        .replace('<!-- BODY_INJECTIONS -->', visibleBody);
    } else {
      // If template is production dist/index.html with pre-existing asset tags:
      renderedHtml = cleanTemplate
        .replace('</head>', `${headInjections}</head>`)
        .replace('<div id="root"></div>', `<div id="root">${visibleBody}</div>`);
    }

    res.statusCode = 200;
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.setHeader('Cache-Control', 'public, max-age=3600, s-maxage=7200');
    res.end(renderedHtml);
  } catch (err) {
    console.error('Error rendering job detail page:', err);
    res.statusCode = 500;
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.end('Internal Server Error');
  }
}
