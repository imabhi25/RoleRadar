import type { JobDetail } from "../api/client";
import { parseAndSanitizeJobDescription } from "./sanitizeDescription";
import { formatPostalAddress } from "./locations";
import { periodOf } from "./compensation";

export interface SchemaPostalAddress {
  "@type": "PostalAddress";
  streetAddress?: string;
  addressLocality?: string;
  addressRegion?: string;
  postalCode?: string;
  addressCountry?: string;
}

export interface SchemaPlace {
  "@type": "Place";
  address: SchemaPostalAddress | string;
}

export interface SchemaMonetaryAmount {
  "@type": "MonetaryAmount";
  currency: string;
  value: {
    "@type": "QuantitativeValue";
    value?: number;
    minValue?: number;
    maxValue?: number;
    unitText: "HOUR" | "DAY" | "WEEK" | "MONTH" | "YEAR";
  };
}

export interface SchemaHiringOrganization {
  "@type": "Organization";
  name: string;
  sameAs?: string;
  logo?: string;
}

export interface SchemaJobPosting {
  "@context": "https://schema.org";
  "@type": "JobPosting";
  title: string;
  description: string;
  datePosted: string;
  validThrough?: string;
  employmentType?: string | string[];
  hiringOrganization: SchemaHiringOrganization;
  jobLocation?: SchemaPlace | SchemaPlace[];
  jobLocationType?: "TELECOMMUTE";
  applicantLocationRequirements?: {
    "@type": "Country" | "State" | "City";
    name: string;
  } | {
    "@type": "Country" | "State" | "City";
    name: string;
  }[];
  baseSalary?: SchemaMonetaryAmount;
  identifier?: {
    "@type": "PropertyValue";
    name: string;
    value: string;
  };
  directApply?: boolean;
}

/**
 * Escapes unsafe characters inside a JSON string intended for insertion into an HTML <script> tag.
 * Specifically prevents '</script' closing tag injection and HTML comment/script breakout.
 */
export function safeJsonLdString(obj: unknown): string {
  return JSON.stringify(obj, null, 2)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

/**
 * Maps internal role_type to Google-accepted Schema.org employmentType strings:
 * FULL_TIME, PART_TIME, CONTRACTOR, TEMPORARY, INTERN, VOLUNTEER, PER_DIEM, OTHER.
 * Only values explicitly defined in the job data are mapped; unstated types are omitted.
 */
export function mapEmploymentType(roleType?: string | null): string | undefined {
  if (!roleType) return undefined;
  const normalized = roleType.trim().toLowerCase();
  switch (normalized) {
    case "full_time":
      return "FULL_TIME";
    case "part_time":
      return "PART_TIME";
    case "contract":
    case "contractor":
      return "CONTRACTOR";
    case "temporary":
      return "TEMPORARY";
    case "internship":
    case "co_op":
      return "INTERN";
    default:
      return undefined;
  }
}

/**
 * Maps unit strings to Google-accepted Schema.org unitText values:
 * HOUR, DAY, WEEK, MONTH, YEAR.
 */
function mapSalaryUnit(interval?: string | null): "HOUR" | "DAY" | "WEEK" | "MONTH" | "YEAR" | undefined {
  if (!interval) return undefined;
  const norm = interval.trim().toLowerCase();
  if (/(?:yr|year|annual|annually|p\.?a\.?)/.test(norm)) return "YEAR";
  if (/(?:mo|month|monthly)/.test(norm)) return "MONTH";
  if (/(?:wk|week|weekly)/.test(norm)) return "WEEK";
  if (/(?:day|daily)/.test(norm)) return "DAY";
  if (/(?:hr|hour|hourly)/.test(norm)) return "HOUR";
  return undefined;
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function formatAmountPatterns(val: number): string[] {
  if (typeof val !== "number" || isNaN(val) || val <= 0) return [];
  const raw = String(val);
  const withCommas = raw.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const res = [escapeRegex(withCommas), escapeRegex(raw)];
  if (val >= 1000 && val % 1000 === 0) {
    res.push(escapeRegex(String(val / 1000)) + "\\s*[kK]");
  } else if (val >= 1000) {
    res.push(escapeRegex((val / 1000).toFixed(1)) + "\\s*[kK]");
  }
  return res;
}

export function extractTiedPeriod(
  evidence: string,
  compensation: NonNullable<JobDetail["compensation"]>
): string | undefined {
  if (!evidence || typeof evidence !== "string") return undefined;
  if (!compensation || typeof compensation !== "object") return undefined;

  const min = typeof compensation.min === "number" && compensation.min > 0 ? compensation.min : undefined;
  const max = typeof compensation.max === "number" && compensation.max > 0 ? compensation.max : undefined;
  if (min === undefined && max === undefined) return undefined;

  const minPatterns = min !== undefined ? formatAmountPatterns(min) : [];
  const maxPatterns = max !== undefined ? formatAmountPatterns(max) : [];

  let amountRegexStr: string;
  if (minPatterns.length > 0 && maxPatterns.length > 0 && min !== max) {
    amountRegexStr = "(?:" + minPatterns.join("|") + ")[^\\w\\d\\n\\r]{1,25}?(?:" + maxPatterns.join("|") + ")";
  } else if (minPatterns.length > 0) {
    amountRegexStr = "(?:" + minPatterns.join("|") + ")";
  } else {
    amountRegexStr = "(?:" + maxPatterns.join("|") + ")";
  }

  const periodWordPattern =
    "(?:year|annual|annually|yearly|yr|p\\.?a\\.?|month|monthly|mo|week|weekly|wk|day|daily|hour|hourly|hr)";

  // 1. Period directly following the matching amount:
  // e.g. '$100,000 - $150,000 / yr' or '$100,000 - 150,000 CAD per year' or '100,000 - 150,000 annually'
  const postRegex = new RegExp(
    amountRegexStr +
      "(?:\\s*(?:[A-Za-z]{3}|[\\$£€]))*\\s*(?:(?:\\/|\\bper\\b|\\ba\\b)\\s*)?(\\b" +
      periodWordPattern +
      "\\b)",
    "i"
  );

  // 2. Period directly preceding the matching amount:
  // e.g. 'annual salary: $100,000 - $150,000' or 'hourly rate: 45 - 65' or 'per year: CAD $133,000 - $183,000'
  const preRegex = new RegExp(
    "(?:\\bper\\s+|\\ba\\s+)?(\\b" +
      periodWordPattern +
      "\\b)\\s*(?:base\\s*)?(?:pay|salary|rate|range|compensation)?\\s*(?:of|:|is)?(?:\\s*(?:[A-Za-z]{3}|[\\$£€]))*\\s*" +
      amountRegexStr,
    "i"
  );

  const postMatch = evidence.match(postRegex);
  if (postMatch && postMatch[1]) {
    const p = periodOf(postMatch[1]);
    if (p) return p;
  }

  const preMatch = evidence.match(preRegex);
  if (preMatch && preMatch[1]) {
    const p = periodOf(preMatch[1]);
    if (p) return p;
  }

  return undefined;
}

interface CandidateSalaryRange {
  min?: number;
  max?: number;
  currency?: string;
  interval?: string;
}

function rangeMatchesSalary(
  r: CandidateSalaryRange | null | undefined,
  comp: NonNullable<JobDetail["compensation"]>
): boolean {
  if (!r || typeof r !== "object") return false;
  if (typeof r.interval !== "string" || !r.interval.trim()) return false;

  const hasMin = typeof comp.min === "number" && comp.min > 0;
  const hasMax = typeof comp.max === "number" && comp.max > 0;
  if (!hasMin && !hasMax) return false;

  if (hasMin && r.min !== comp.min) return false;
  if (hasMax && r.max !== comp.max) return false;
  if (r.min !== undefined && r.min !== comp.min) return false;
  if (r.max !== undefined && r.max !== comp.max) return false;

  const compCurr = String(comp.currency || "").trim().toUpperCase();
  const rangeCurr = String(r.currency || "").trim().toUpperCase();
  if (compCurr && rangeCurr && compCurr !== rangeCurr) return false;

  return true;
}

/**
 * Safely resolves the salary pay period (e.g. "year", "hour") strictly associated with
 * the job's stated compensation range.
 * Ensures a pay period from an unrelated salary range (e.g. from multiple ranges or
 * different job levels) is NOT mistakenly applied to the job's salary.
 */
export function resolveMatchingSalaryInterval(
  compensation: NonNullable<JobDetail["compensation"]>
): string | undefined {
  if (!compensation || typeof compensation !== "object") return undefined;

  // 1. Direct top-level interval explicitly assigned to this compensation
  if (typeof compensation.interval === "string" && compensation.interval.trim()) {
    return compensation.interval.trim();
  }

  // 2. Matching range from compensation.ranges (amounts and currency must match)
  // There is NO single-range fallback: the range must match the salary being marked up.
  if (Array.isArray(compensation.ranges) && compensation.ranges.length > 0) {
    const matchingRange = compensation.ranges.find((r) => rangeMatchesSalary(r, compensation));
    if (matchingRange && typeof matchingRange.interval === "string") {
      return matchingRange.interval.trim();
    }
  }

  // 3. Conservative extraction from compensation.evidence
  // Omit salary markup unless the pay period is clearly and unambiguously tied to the matching amount.
  if (typeof compensation.evidence === "string" && compensation.evidence.trim()) {
    if (/multiple ranges/i.test(String(compensation.compensationTierSummary || ""))) {
      return undefined;
    }
    const tied = extractTiedPeriod(compensation.evidence, compensation);
    if (tied) return tied;
  }

  return undefined;
}

/**
 * Extracts structured baseSalary from real job compensation data.
 * Validates positive finite numbers, reasonable min <= max, and standard currency codes.
 * Returns undefined if no verified structured pay data exists. Never invents figures.
 */
export function buildSchemaBaseSalary(compensation?: JobDetail["compensation"]): SchemaMonetaryAmount | undefined {
  if (!compensation || typeof compensation !== "object") return undefined;
  if (compensation.validation) return undefined;

  // 1. Ashby summaryComponents
  if (Array.isArray(compensation.summaryComponents) && compensation.summaryComponents.length > 0) {
    for (const comp of compensation.summaryComponents) {
      if (!comp || typeof comp !== "object") continue;
      const cType = String(comp.compensationType || "");
      if (!/^(?:Salary|BaseSalary|Hourly|Wage)$/i.test(cType) && comp.compensationType) continue;

      const currency = String(comp.currencyCode || "").trim().toUpperCase();
      const unitText = mapSalaryUnit(String(comp.interval || ""));
      const min = typeof comp.minValue === "number" && comp.minValue > 0 ? comp.minValue : undefined;
      const max = typeof comp.maxValue === "number" && comp.maxValue > 0 ? comp.maxValue : undefined;

      if (currency && unitText && (min !== undefined || max !== undefined)) {
        if (min !== undefined && max !== undefined && min > max) continue;
        return {
          "@type": "MonetaryAmount",
          currency,
          value: {
            "@type": "QuantitativeValue",
            ...(min !== undefined && max !== undefined && min === max
              ? { value: min }
              : {
                  ...(min !== undefined ? { minValue: min } : {}),
                  ...(max !== undefined ? { maxValue: max } : {}),
                }),
            unitText,
          },
        };
      }
    }
  }

  // 2. Direct min, max, currency, interval (Greenhouse, Lever, Workday)
  const min = typeof compensation.min === "number" && compensation.min > 0 ? compensation.min : undefined;
  const max = typeof compensation.max === "number" && compensation.max > 0 ? compensation.max : undefined;
  const currency = String(compensation.currency || "").trim().toUpperCase();
  const rawInterval = resolveMatchingSalaryInterval(compensation);
  const unitText = mapSalaryUnit(rawInterval);

  if (currency && unitText && (min !== undefined || max !== undefined)) {
    if (min !== undefined && max !== undefined && min > max) return undefined;
    return {
      "@type": "MonetaryAmount",
      currency,
      value: {
        "@type": "QuantitativeValue",
        ...(min !== undefined && max !== undefined && min === max
          ? { value: min }
          : {
              ...(min !== undefined ? { minValue: min } : {}),
              ...(max !== undefined ? { maxValue: max } : {}),
            }),
        unitText,
      },
    };
  }

  return undefined;
}

/**
 * Builds Schema.org Place object from location strings.
 * Parses city, region, country, and postal/street parts when available without inventing missing segments.
 */
export function buildSchemaPlace(locStr: string, defaultCountry = ""): SchemaPlace {
  const clean = locStr.replace(/\s+/g, " ").trim();
  const parts = clean.split(/[,·]/).map((p) => p.trim()).filter(Boolean);

  const postal = formatPostalAddress(clean);
  const address: SchemaPostalAddress = {
    "@type": "PostalAddress",
  };

  if (parts.length === 1) {
    if (/^(?:Canada|United States|United Kingdom)$/i.test(parts[0])) {
      address.addressCountry = parts[0];
    } else {
      address.addressLocality = parts[0];
      if (defaultCountry) address.addressCountry = defaultCountry;
    }
  } else if (parts.length === 2) {
    address.addressLocality = parts[0];
    if (/^(?:Canada|United States|United Kingdom)$/i.test(parts[1])) {
      address.addressCountry = parts[1];
    } else {
      address.addressRegion = parts[1];
      if (defaultCountry) address.addressCountry = defaultCountry;
    }
  } else if (parts.length === 3) {
    address.addressLocality = parts[0];
    address.addressRegion = parts[1];
    address.addressCountry = parts[2];
  } else if (parts.length >= 4) {
    address.streetAddress = parts.slice(0, parts.length - 3).join(", ");
    address.addressLocality = parts[parts.length - 3];
    address.addressRegion = parts[parts.length - 2];
    address.addressCountry = parts[parts.length - 1];
  }

  if (postal.full && postal.full !== clean) {
    address.streetAddress = postal.full;
  }

  return {
    "@type": "Place",
    address,
  };
}

/**
 * Resolves verified remote applicant locations strictly when the source explicitly supports it.
 * Does NOT treat office or job-location countries (such as job.locations or job.country)
 * as proof of remote applicant eligibility.
 */
export function resolveApplicantLocationRequirements(
  job: JobDetail
): { "@type": "Country"; name: string }[] | undefined {
  if ((job.workplace_type || "").toLowerCase() !== "remote") {
    return undefined;
  }

  // Only include remote eligibility when the source explicitly supports it
  const explicitApplicantCountries = (job as unknown as { applicant_location_requirements?: string[] })
    .applicant_location_requirements;

  if (Array.isArray(explicitApplicantCountries) && explicitApplicantCountries.length > 0) {
    const verified = explicitApplicantCountries
      .map((c) => String(c).trim())
      .filter((c) => /^(?:Canada|United States|United Kingdom)$/i.test(c));
    if (verified.length > 0) {
      return verified.map((c) => ({ "@type": "Country", name: c }));
    }
  }

  // Do not treat office or job-location countries (job.locations or job.country) as proof of remote applicant eligibility
  return undefined;
}

/**
 * Assembles Schema.org JobPosting object adhering strictly to Google Search Central requirements.
 * Returns null if required data (title, description, hiringOrganization, valid posted_at) is missing.
 */
export function buildJobPostingSchema(
  job: JobDetail,
  options: {
    siteUrl?: string;
  } = {}
): SchemaJobPosting | null {
  if (!job || typeof job !== "object") return null;

  // Title: required
  const title = (job.title || "").trim();
  if (!title) return null;

  // Hiring Organization: required (Google rejects postings without hiringOrganization.name)
  const companyName = (job.company || "").trim();
  if (!companyName) return null;

  // Description: required and must contain HTML text (Google rejects bare or empty descriptions)
  const parsed = parseAndSanitizeJobDescription(job.description || "", companyName);
  const rawHtml = parsed.html || "";
  const textCheck = rawHtml.replace(/<[^>]*>/g, "").trim();
  if (!textCheck || textCheck.length < 20) return null;

  // datePosted: required ISO date
  if (!job.posted_at) return null;
  const postedDate = new Date(job.posted_at);
  if (isNaN(postedDate.getTime())) return null;
  const datePosted = postedDate.toISOString();

  // Hiring organization details
  const siteUrl = options.siteUrl || "https://roleradar-jobs.vercel.app";
  const hiringOrg: SchemaHiringOrganization = {
    "@type": "Organization",
    name: companyName,
  };
  if (job.company_website_url) {
    hiringOrg.sameAs = job.company_website_url;
  }
  if (job.company_logo_url) {
    hiringOrg.logo = job.company_logo_url.startsWith("http")
      ? job.company_logo_url
      : `${siteUrl}${job.company_logo_url}`;
  }

  const schema: SchemaJobPosting = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title,
    description: rawHtml,
    datePosted,
    hiringOrganization: hiringOrg,
    identifier: {
      "@type": "PropertyValue",
      name: companyName,
      value: job.job_id,
    },
  };

  // Employment Type
  const empType = mapEmploymentType(job.role_type);
  if (empType) {
    schema.employmentType = empType;
  }

  // Workplace / Remote eligibility:
  // Google requires applicantLocationRequirements whenever jobLocationType is TELECOMMUTE.
  // Omitting TELECOMMUTE must not make a remote-only job look office-based.
  // If the source doesn't establish applicant locations or a genuine office-work option,
  // omit the JobPosting markup rather than inventing details or misrepresenting the job.
  const workplace = (job.workplace_type || "").toLowerCase();
  const isRemoteOnly = workplace === "remote";
  const applicantRequirements = resolveApplicantLocationRequirements(job);

  if (isRemoteOnly) {
    if (applicantRequirements && applicantRequirements.length > 0) {
      schema.jobLocationType = "TELECOMMUTE";
      schema.applicantLocationRequirements =
        applicantRequirements.length === 1 ? applicantRequirements[0] : applicantRequirements;
    } else {
      // Remote-only job with no verified applicant locations and no genuine office-work option.
      // Do not invent applicant locations, and do not emit a misleading office-based JobPosting.
      return null;
    }
  } else if (applicantRequirements && applicantRequirements.length > 0) {
    // Hybrid role with explicit remote applicant eligibility
    schema.jobLocationType = "TELECOMMUTE";
    schema.applicantLocationRequirements =
      applicantRequirements.length === 1 ? applicantRequirements[0] : applicantRequirements;
  }

  // Physical Location(s) (for on-site or hybrid jobs)
  // Per Google Search Central guidelines for 100% remote jobs:
  // "Do not add the jobLocation property". Only on-site and hybrid jobs specify physical jobLocation.
  if (!isRemoteOnly) {
    if (Array.isArray(job.locations) && job.locations.length > 0) {
      const places = job.locations
        .filter((loc) => Boolean(loc && loc.location))
        .map((loc) => buildSchemaPlace(loc.location, loc.country || job.country || ""));
      if (places.length === 1) {
        schema.jobLocation = places[0];
      } else if (places.length > 1) {
        schema.jobLocation = places;
      }
    } else if (job.location) {
      schema.jobLocation = buildSchemaPlace(job.location, job.country || "");
    }

    // A non-remote job MUST have at least one physical location for Google JobPosting
    if (!schema.jobLocation) {
      return null;
    }
  }

  // Base Salary
  const salary = buildSchemaBaseSalary(job.compensation);
  if (salary) {
    schema.baseSalary = salary;
  }

  return schema;
}
