import COMPANY_BACKGROUNDS from "./companyBackgrounds.json";
import { COMPANY_DOMAIN_MAP, normalizeCompanyName, ownObject, ownString } from "./companyLogos";

/**
 * Verified company LinkedIn pages.
 *
 * Every URL below was read from the company's own official website (the site's social/footer links);
 * none is constructed from a company name. Companies whose site exposes no unambiguous LinkedIn
 * company link (e.g. Palantir, Linear, Notion, Manulife, BMO) are intentionally absent: the UI
 * omits the link rather than guessing.
 */
export const COMPANY_LINKEDIN_URLS: Record<string, string> = {
  "1password": "https://www.linkedin.com/company/1password",
  "amazon": "https://www.linkedin.com/company/amazon",
  "anthropic": "https://www.linkedin.com/company/anthropicresearch",
  "anyscale": "https://www.linkedin.com/company/joinanyscale",
  "arctic wolf": "https://www.linkedin.com/company/arctic-wolf-networks",
  "brex": "https://www.linkedin.com/company/brexhq",
  "carta": "https://www.linkedin.com/company/carta--",
  "cibc": "https://www.linkedin.com/company/cibc",
  "cloudflare": "https://www.linkedin.com/company/cloudflare",
  "cohere": "https://www.linkedin.com/company/cohere-ai",
  "coinbase": "https://www.linkedin.com/company/coinbase",
  "d2l": "https://www.linkedin.com/company/d2l",
  "databricks": "https://www.linkedin.com/company/databricks",
  "datadog": "https://www.linkedin.com/company/datadog",
  "doordash": "https://www.linkedin.com/company/doordash",
  "duolingo": "https://www.linkedin.com/company/duolingo",
  "figma": "https://www.linkedin.com/company/figma",
  "flexport": "https://www.linkedin.com/company/flexport",
  "geotab": "https://www.linkedin.com/company/geotab",
  "gitlab": "https://www.linkedin.com/company/gitlab-com",
  "grafana": "https://www.linkedin.com/company/grafana-labs",
  "hootsuite": "https://www.linkedin.com/company/hootsuite",
  "mercury": "https://www.linkedin.com/company/mercuryhq",
  "metabase": "https://www.linkedin.com/company/metabase",
  "mistral ai": "https://www.linkedin.com/company/mistralai",
  "monzo": "https://www.linkedin.com/company/monzo-bank",
  "neon": "https://www.linkedin.com/company/neondatabase",
  "nvidia": "https://www.linkedin.com/company/nvidia",
  "openai": "https://www.linkedin.com/company/openai",
  "pinterest": "https://www.linkedin.com/company/pinterest",
  "plaid": "https://www.linkedin.com/company/plaid-",
  "planetscale": "https://www.linkedin.com/company/planetscale",
  "pointclickcare": "https://www.linkedin.com/company/pointclickcare",
  "ramp": "https://www.linkedin.com/company/ramp",
  "rbc": "https://www.linkedin.com/company/rbc",
  "reddit": "https://www.linkedin.com/company/reddit-com",
  "render": "https://www.linkedin.com/company/renderco",
  "replit": "https://www.linkedin.com/company/repl-it",
  "robinhood": "https://www.linkedin.com/company/robinhood",
  "runway": "https://www.linkedin.com/company/runwayml",
  "samsara": "https://www.linkedin.com/company/samsara",
  "scale ai": "https://www.linkedin.com/company/scaleai",
  "sentry": "https://www.linkedin.com/company/getsentry",
  "sourcegraph": "https://www.linkedin.com/company/4803356",
  "spotify": "https://www.linkedin.com/company/spotify",
  "stability ai": "https://www.linkedin.com/company/stability-ai",
  "stackadapt": "https://www.linkedin.com/company/stackadapt",
  "spacex": "https://www.linkedin.com/company/spacex",
  "stripe": "https://www.linkedin.com/company/stripe",
  "sun life": "https://www.linkedin.com/company/sun-life-financial",
  "supabase": "https://www.linkedin.com/company/supabase",
  "td": "https://www.linkedin.com/company/td",
  "thomson reuters": "https://www.linkedin.com/company/thomson-reuters",
  "toast": "https://www.linkedin.com/company/toast-inc",
  "vercel": "https://www.linkedin.com/company/vercel",
  "waabi": "https://www.linkedin.com/company/waabi",
  "wealthsimple": "https://www.linkedin.com/company/wealthsimple",
  "webflow": "https://www.linkedin.com/company/webflow-inc-",
};

const LINKEDIN_COMPANY_URL = /^https:\/\/www\.linkedin\.com\/company\/[A-Za-z0-9_.%-]+$/;

export function getCompanyLinkedIn(company?: string | null): string | null {
  if (!company) return null;
  const url = ownString(COMPANY_LINKEDIN_URLS, normalizeCompanyName(company));
  return url && LINKEDIN_COMPANY_URL.test(url) ? url : null;
}

/**
 * Verified official social accounts beyond LinkedIn: X, GitHub (organisation) and YouTube (channel).
 * Same rule as above: each handle was read from the company's own official website (a link in its pages);
 * nothing is guessed from a company name. Where a site exposes several different accounts for one network
 * (e.g. Spotify's X accounts) or none, that network is intentionally omitted for the company.
 * X handles are stored bare, GitHub as the organisation login, YouTube as its channel path.
 */
export const COMPANY_SOCIAL_HANDLES: Record<string, { x?: string; github?: string; youtube?: string }> = {
  "1password": { x: "1Password", github: "1Password" },
  "amazon": { x: "amazonnews" },
  "anthropic": { x: "AnthropicAI", youtube: "@anthropic-ai" },
  "anyscale": { github: "anyscale" },
  "arctic wolf": { x: "AWNetworks", youtube: "c/ArcticWolfNetworks" },
  "brex": { x: "brexHQ", youtube: "channel/UCQQB8ThG8aBLvp50R0OcscA" },
  "carta": { x: "cartainc" },
  "cibc": { youtube: "user/CIBCVideos" },
  "cohere": { x: "cohere", youtube: "@CohereAI" },
  "coinbase": { x: "coinbase" },
  "d2l": { x: "D2L", youtube: "user/desire2learninc" },
  "databricks": { x: "databricks", youtube: "@Databricks" },
  "doordash": { x: "doordash", youtube: "channel/UCXQ7Gzszfuw84cEWGpKlFiQ" },
  "duolingo": { x: "duolingo", youtube: "user/duolingo" },
  "faire": { x: "faire_wholesale" },
  "figma": { x: "figma" },
  "flexport": { x: "flexport", youtube: "@Flexport" },
  "geotab": { x: "geotab", youtube: "user/MyGeotab" },
  "gitlab": { x: "gitlab", youtube: "channel/UCnMGQ8QHMAnVIsI3xJrihhg" },
  "grafana": { x: "grafana", github: "grafana", youtube: "channel/UCYCwgQAMm9sTJv0rgwQLCxw" },
  "hootsuite": { x: "hootsuite", youtube: "user/hootsuite" },
  "linear": { x: "linear", github: "linear", youtube: "@linear" },
  "mercury": { x: "mercury", youtube: "@Mercuryfi" },
  "metabase": { x: "metabase", github: "metabase", youtube: "channel/UCvg53nhM-xPUiFGqDJDhjaw" },
  "mistral ai": { x: "mistralai", youtube: "@MistralAIOfficial" },
  "neon": { x: "neondatabase", github: "neondatabase", youtube: "channel/UCoMzQTJSIr7-RU1QbomQI2w" },
  "nvidia": { x: "nvidia", youtube: "user/nvidia" },
  "ontario teachers pension plan": { youtube: "user/otppinfo" },
  "openai": { x: "OpenAI", github: "openai" },
  "pinterest": { x: "pinterest" },
  "plaid": { x: "plaid", github: "plaid" },
  "planetscale": { x: "planetscale", github: "planetscale" },
  "pointclickcare": { x: "pointclickcare" },
  "ramp": { x: "tryramp" },
  "rbc": { x: "RBCCareers" },
  "reddit": { x: "reddit", youtube: "c/reddit" },
  "render": { x: "render", github: "render-oss", youtube: "@render-inc" },
  "replit": { x: "replit", youtube: "@replit" },
  "robinhood": { x: "RobinhoodApp", youtube: "channel/UCY55VHsy1umgvR35gl5bmUw" },
  "runway": { x: "runwayml" },
  "samsara": { x: "Samsara", youtube: "c/SamsaraHQ" },
  "scale ai": { x: "scale_ai" },
  "sentry": { x: "sentry", github: "getsentry" },
  "sourcegraph": { x: "Sourcegraph", github: "sourcegraph", youtube: "c/Sourcegraph" },
  "stability ai": { x: "StabilityAI", youtube: "@Stability_AI" },
  "stackadapt": { x: "StackAdapt", youtube: "@StackAdaptPlatform" },
  "stripe": { github: "stripe" },
  "supabase": { x: "supabase", github: "supabase", youtube: "c/supabase" },
  "td": { x: "td_canada" },
  "thomson reuters": { x: "thomsonreuters" },
  "toast": { youtube: "@Toasttab" },
  "vercel": { x: "vercel", github: "vercel", youtube: "@VercelHQ" },
  "waabi": { x: "waabi_ai", youtube: "channel/UCNJWh6U6vfTz77SJCeWZloQ" },
  "wealthsimple": { x: "Wealthsimple", youtube: "c/wealthsimple" },
  "webflow": { x: "webflow" },
};

const X_HANDLE = /^[A-Za-z0-9_]{1,15}$/;
const GITHUB_ORG = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/;
const YOUTUBE_PATH = /^(?:@[\w.-]+|channel\/[\w-]+|c\/[\w.-]+|user\/[\w.-]+)$/;

export function getCompanySocials(company?: string | null): { x: string | null; github: string | null; youtube: string | null } {
  const entry = company ? ownObject(COMPANY_SOCIAL_HANDLES, normalizeCompanyName(company)) : undefined;
  return {
    x: entry?.x && X_HANDLE.test(entry.x) ? `https://x.com/${entry.x}` : null,
    github: entry?.github && GITHUB_ORG.test(entry.github) ? `https://github.com/${entry.github}` : null,
    youtube: entry?.youtube && YOUTUBE_PATH.test(entry.youtube) ? `https://www.youtube.com/${entry.youtube}` : null,
  };
}

export interface CompanyProfile {
  name: string;
  website: string | null;
  linkedin: string | null;
  x?: string | null;
  github?: string | null;
  youtube?: string | null;
  tagline?: string;
  description?: string;
  headquarters?: string;
  size?: string;
  founded?: string;
  industry?: string;
  benefits?: string[];
  sourceUrl?: string | null;
  verifiedDate?: string | null;
}

/**
 * Optional verified extras (description, headquarters, size, founded year, industry, benefits, sourceUrl, verifiedDate).
 * Only citeable, verified facts directly from official company information are included.
 * Missing fields are intentionally omitted (never fabricated).
 */
export const COMPANY_PROFILE_DETAILS: Record<string, Pick<CompanyProfile, "tagline" | "description" | "headquarters" | "size" | "founded" | "industry" | "benefits" | "sourceUrl" | "verifiedDate">> = {
  "wealthsimple": {
    tagline: "Digital investing and financial services",
    sourceUrl: "https://www.wealthsimple.com/",
  },
  "1password": {
    tagline: "Password and credential management for people and businesses",
    description: "1Password develops password and credential management solutions for individuals, developers, and enterprise teams.",
    headquarters: "Toronto, Ontario, Canada",
    size: "1,400+ employees",
    industry: "Cybersecurity & Software",
    founded: "2005",
    benefits: ["Competitive and comprehensive health benefits", "Remote-first workplace flexibility", "Generous PTO and quarterly wellness days", "Parental leave support"],
    sourceUrl: "https://1password.com/careers/",
    verifiedDate: "2026-10-02",
  },
  "amazon": {
    tagline: "Global online marketplace and cloud services",
    description: "Amazon is a global technology company specializing in cloud infrastructure (AWS), e-commerce, digital streaming, and artificial intelligence.",
    headquarters: "Seattle, Washington, United States",
    size: "10,000+ employees",
    industry: "Cloud Infrastructure & Software",
    benefits: ["Comprehensive medical, dental, and vision coverage", "401(k) plan with company match", "Paid parental leave", "Prepaid college tuition assistance"],
    sourceUrl: "https://www.aboutamazon.com/workplace/employee-benefits",
    verifiedDate: "2026-10-02",
  },
  "cohere": {
    tagline: "Enterprise AI and large language models",
    description: "Cohere is an enterprise AI company that builds state-of-the-art large language models and natural language processing systems.",
    headquarters: "Toronto, Ontario, Canada",
    founded: "2019",
    industry: "Artificial Intelligence",
    benefits: ["Six weeks of paid vacation", "Equity / stock options", "Coverage for medical, health insurance, vision, and mental health", "Monthly fitness and wellness allowance", "$2,000 annual education benefit for professional development", "Monthly co-working benefit for remote team members"],
    sourceUrl: "https://cohere.com/careers",
    verifiedDate: "2026-10-02",
  },
  "d2l": {
    tagline: "Cloud learning software and the Brightspace platform",
    description: "D2L transforms learning through cloud education software, including the Brightspace learning management system.",
    headquarters: "Kitchener, Ontario, Canada",
    size: "1,000+ employees",
    industry: "Education Technology",
    founded: "1999",
    benefits: ["Professional development and career growth", "Collaborative work environment", "Employee wellbeing support"],
    sourceUrl: "https://www.d2l.com/careers/",
    verifiedDate: "2026-10-02",
  },
  "databricks": {
    tagline: "Data intelligence, analytics, and AI platforms",
    description: "Databricks provides a unified data intelligence platform combining data warehousing, engineering, and generative AI built on open lakehouse architectures.",
    headquarters: "San Francisco, California, United States",
    size: "10,000+ employees",
    industry: "Data Platforms & AI",
    founded: "2013",
    benefits: ["Flexible hybrid ways of working", "Employee health and well-being programs"],
    sourceUrl: "https://www.databricks.com/company/careers",
    verifiedDate: "2026-10-02",
  },
  "geotab": {
    tagline: "Connected vehicle technology and fleet analytics",
    description: "Geotab is a global telematics leader connecting commercial vehicles to the cloud and delivering fleet management analytics.",
    headquarters: "Oakville, Ontario, Canada",
    size: "2,700+ employees",
    industry: "IoT & Telematics",
    founded: "2000",
    benefits: ["Flexible hybrid approach (in-office and remote)"],
    sourceUrl: "https://www.geotab.com/about/",
    verifiedDate: "2026-10-02",
  },
  "shopify": {
    tagline: "Commerce infrastructure for businesses worldwide",
    description: "Shopify provides essential internet infrastructure for global commerce, powering millions of businesses across the world.",
    headquarters: "Ottawa, Ontario, Canada",
    industry: "E-Commerce Platforms",
    benefits: ["Digital by Design remote-first work culture"],
    sourceUrl: "https://www.shopify.com/careers",
    verifiedDate: "2026-10-02",
  },
};

function safeHttpUrl(url?: string | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url.trim());
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

/** Company-level profile assembled only from verified data. Missing fields are null/undefined, never placeholders. */
export function getCompanyProfile(company: string, apiWebsiteUrl?: string | null): CompanyProfile {
  const key = normalizeCompanyName(company);
  const mappedDomain = ownString(COMPANY_DOMAIN_MAP, key);
  return {
    name: company,
    website: safeHttpUrl(apiWebsiteUrl) ?? (mappedDomain ? `https://${mappedDomain}/` : null),
    linkedin: getCompanyLinkedIn(company),
    ...getCompanySocials(company),
    ...(mappedDomain ? ownObject(COMPANY_BACKGROUNDS, mappedDomain) ?? {} : {}),
    ...(ownObject(COMPANY_PROFILE_DETAILS, key) ?? {}),
  };
}

/**
 * True only when there is real content the header does not already show. Website and LinkedIn live in the
 * header, so a profile with just those (or just a name) gets no separate "About" block.
 */
export function hasCompanyProfileContent(profile: CompanyProfile): boolean {
  return Boolean(
    profile.description ||
    profile.headquarters ||
    profile.size ||
    profile.founded ||
    profile.industry ||
    (profile.benefits && profile.benefits.length > 0)
  );
}
