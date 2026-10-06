/**
 * Centralized company logo resolution for RoleRadar.
 * Uses verified company domains for the favicons shown beside Google search results.
 * Stored official branding remains available as a fallback; absent logos use a generic icon.
 */

// Mapping of normalized company names/aliases to verified company domains
export const COMPANY_DOMAIN_MAP: Record<string, string> = {
  // Direct-source ATS companies
  "figma": "figma.com",
  "cloudflare": "cloudflare.com",
  "datadog": "datadoghq.com",
  "gitlab": "gitlab.com",
  "spotify": "spotify.com",
  "palantir": "palantir.com",
  "neon": "neon.tech",
  "metabase": "metabase.com",
  "linear": "linear.app",
  "ramp": "ramp.com",
  "supabase": "supabase.com",
  "anthropic": "anthropic.com",
  "stripe": "stripe.com",
  "databricks": "databricks.com",
  "robinhood": "robinhood.com",
  "scale ai": "scale.com",
  "scale": "scale.com",
  "reddit": "reddit.com",
  "coinbase": "coinbase.com",
  "pinterest": "pinterest.com",
  "brex": "brex.com",
  "chime": "chime.com",
  "duolingo": "duolingo.com",
  "faire": "faire.com",
  "rubrik": "rubrik.com",
  "flexport": "flexport.com",
  "samsara": "samsara.com",
  "toast": "toasttab.com",
  "stackadapt": "stackadapt.com",
  "vercel": "vercel.com",
  "openai": "openai.com",
  "notion": "notion.so",
  "plaid": "plaid.com",
  "cohere": "cohere.com",
  "wealthsimple": "wealthsimple.com",
  "1password": "1password.com",
  "waabi": "waabi.ai",
  "pointclickcare": "pointclickcare.com",
  "sentry": "sentry.io",
  "sourcegraph": "sourcegraph.com",
  "replit": "replit.com",
  "render": "render.com",
  "planetscale": "planetscale.com",
  "webflow": "webflow.com",
  "grafana labs": "grafana.com",
  "grafana": "grafana.com",
  "mistral ai": "mistral.ai",
  "mistral": "mistral.ai",
  "runway": "runwayml.com",
  "runwayml": "runwayml.com",
  "anyscale": "anyscale.com",
  "stability ai": "stability.ai",
  "stability": "stability.ai",
  "monzo": "monzo.com",
  "monzo bank": "monzo.com",
  "carta": "carta.com",
  "mercury": "mercury.com",

  // Broad-feed tech companies
  "microsoft": "microsoft.com",
  "google": "google.com",
  "amazon": "amazon.com",
  "spacex": "spacex.com",
  "meta": "meta.com",
  "facebook": "meta.com",
  "shopify": "shopify.com",
  "apple": "apple.com",
  "netflix": "netflix.com",
  "airbnb": "airbnb.com",
  "uber": "uber.com",
  "github": "github.com",
  "slack": "slack.com",
  "atlassian": "atlassian.com",
  "discord": "discord.com",
  "asana": "asana.com",
  "hashicorp": "hashicorp.com",
  "snowflake": "snowflake.com",
  "mongodb": "mongodb.com",
  "elastic": "elastic.co",
  "zoom": "zoom.us",
  "twitter": "x.com",
  "x": "x.com",
  "doordash": "doordash.com",
  "salesforce": "salesforce.com",
  "adobe": "adobe.com",
  "intel": "intel.com",
  "cisco": "cisco.com",
  "oracle": "oracle.com",
  "paypal": "paypal.com",
  "snap": "snap.com",
  "lyft": "lyft.com",
  "square": "squareup.com",
  "block": "block.xyz",
  "box": "box.com",
  "dropbox": "dropbox.com",
  "twilio": "twilio.com",
  "hubspot": "hubspot.com",
  "okta": "okta.com",
  "workday": "workday.com",
  "servicenow": "servicenow.com",
  "braze": "braze.com",
  "instacart": "instacart.com",
  "affirm": "affirm.com",
  "dialpad": "dialpad.com",

  // Canadian employers
  "bell": "bell.ca",
  "rogers": "rogers.com",
  "scotiabank": "scotiabank.com",
  "telus": "telus.com",
  "clio": "clio.com",
  "eq bank": "eqbank.ca",
  "rbc": "rbc.com",
  "royal bank of canada": "rbc.com",
  "td": "td.com",
  "bmo": "bmo.com",
  "cibc": "cibc.com",
  "manulife": "manulife.com",
  "sun life": "sunlife.com",
  "ontario teachers pension plan": "otpp.com",
  "thomson reuters": "thomsonreuters.com",
  "autodesk": "autodesk.com",
  "nvidia": "nvidia.com",
  "arctic wolf": "arcticwolf.com",
  "geotab": "geotab.com",
  "d2l": "d2l.com",
  "hootsuite": "hootsuite.com",
  "aws": "aws.amazon.com",
};

/**
 * Normalizes a company name for dictionary lookup by removing legal entity suffixes,
 * punctuation, and excessive whitespace.
 */
/**
 * Own-property lookup for the curated tables. A company called "Constructor", "toString" or "__proto__" must
 * never resolve to something inherited from Object.prototype, and only string values are ever returned.
 */
export function ownString(table: Record<string, unknown>, key: string): string | undefined {
  if (!key || !Object.prototype.hasOwnProperty.call(table, key)) return undefined;
  const value = table[key];
  return typeof value === "string" && value ? value : undefined;
}

/** Own-property lookup for object-valued tables (social handles, profile details). */
export function ownObject<T extends object>(table: Record<string, T>, key: string): T | undefined {
  if (!key || !Object.prototype.hasOwnProperty.call(table, key)) return undefined;
  const value = table[key];
  return value && typeof value === "object" ? value : undefined;
}

/** A logo URL is only used when it is a string that points at an http(s) URL or a same-origin path. */
function usableLogoUrl(url: unknown): string | null {
  if (typeof url !== "string") return null;
  const trimmed = url.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("/") && !trimmed.startsWith("//")) return trimmed;
  try {
    const parsed = new URL(trimmed);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? trimmed : null;
  } catch {
    return null;
  }
}

export function normalizeCompanyName(name: string): string {
  if (typeof name !== "string" || !name) return "";
  let clean = name.toLowerCase().trim();

  // Remove parentheticals like "(formerly ...)" or "(US)"
  clean = clean.replace(/\s*\([^)]*\)/g, "");

  // Remove common corporate suffixes
  clean = clean.replace(
    /[,.]?\s+(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|technologies|tech|labs|pbc)\b/gi,
    ""
  );

  // Clean trailing punctuation and collapse spaces
  clean = clean.replace(/[^\w\s-]/g, "").replace(/\s+/g, " ").trim();

  return clean;
}

/**
 * Explicit, deterministic local logo assets for verified tech companies.
 * Stored in /logos/ as durable fallbacks when a favicon or API image is unavailable.
 * Original artwork is retained at its native aspect ratio.
 *
 * SVG sources: Simple Icons (https://simpleicons.org/) — verified open-source brand marks.
 * PNG sources: Official employer apple-touch-icons, ATS career page logos, or brand kits.
 */
export const COMPANY_LOGOS: Record<string, string> = {
  "google": "/logos/google.png",
  "shopify": "/logos/shopify.svg",
  "bell": "/logos/bell.png",
  "rogers": "/logos/rogers.png",
  "scotiabank": "/logos/scotiabank.png",
  "telus": "/logos/telus.jpg",
  "clio": "/logos/clio.png",
  "eq bank": "/logos/eq-bank.svg",
  // Direct-source ATS & target companies
  "openai": "/logos/openai.svg",
  "replit": "/logos/replit.svg",
  "palantir": "/logos/palantir.svg",
  "notion": "/logos/notion.svg",
  "stripe": "/logos/stripe.svg",
  "spacex": "/logos/spacex.svg",
  "figma": "/logos/figma.svg",
  "datadog": "/logos/datadog.svg",
  "cohere": "/logos/cohere.png",       // multicolor logo — PNG preserves brand colors
  "mercury": "/logos/mercury.svg",
  "linear": "/logos/linear.svg",
  "render": "/logos/render.svg",
  "sentry": "/logos/sentry.svg",
  "sourcegraph": "/logos/sourcegraph.png",
  "webflow": "/logos/webflow.svg",
  "grafana labs": "/logos/grafana.svg",
  "grafana": "/logos/grafana.svg",
  "mistral ai": "/logos/mistralai.svg",
  "mistral": "/logos/mistralai.svg",
  "runway": "/logos/runway.svg",
  "runwayml": "/logos/runway.svg",
  "anyscale": "/logos/anyscale.svg",
  "stability ai": "/logos/stabilityai.png",
  "stability": "/logos/stabilityai.png",
  "carta": "/logos/carta.png",          // official apple-touch-icon from carta.com
  "brex": "/logos/brex.svg",
  "cloudflare": "/logos/cloudflare.svg",
  "spotify": "/logos/spotify.svg",
  "samsara": "/logos/samsara.png",
  "planetscale": "/logos/planetscale.svg",
  "toast": "/logos/toast.png",
  "anthropic": "/logos/anthropic.svg",
  "coinbase": "/logos/coinbase.svg",
  "databricks": "/logos/databricks.svg",
  "duolingo": "/logos/duolingo.svg",
  "gitlab": "/logos/gitlab.svg",
  "monzo": "/logos/monzo.svg",
  "monzo bank": "/logos/monzo.svg",
  "pinterest": "/logos/pinterest.svg",
  "reddit": "/logos/reddit.svg",
  "robinhood": "/logos/robinhood.svg",
  "supabase": "/logos/supabase.svg",
  "vercel": "/logos/vercel.svg",
  "1password": "/logos/1password.svg",
  "metabase": "/logos/metabase.svg",
  "neon": "/logos/neon.svg",
  "scale ai": "/logos/scaleai.svg",
  "scale": "/logos/scaleai.svg",
  "wealthsimple": "/logos/wealthsimple.svg",
  "flexport": "/logos/flexport.svg",
  "plaid": "/logos/plaid.png",          // multicolor logo — PNG preserves brand colors
  "ramp": "/logos/ramp.svg",
  "chime": "/logos/chime.png",
  "rubrik": "/logos/rubrik.png",
  "stackadapt": "/logos/stackadapt.png",
  "waabi": "/logos/waabi.png",          // official wordmark from Lever career page
  "pointclickcare": "/logos/pointclickcare.png",  // official apple-touch-icon
  "faire": "/logos/faire.png",

  // Canadian employers & new registry companies (official site assets, or Wikimedia Commons brand files)
  "amazon": "/logos/amazon.svg",
  "rbc": "/logos/rbc.svg",
  "td": "/logos/td.svg",
  "bmo": "/logos/bmo.svg",
  "cibc": "/logos/cibc.png",
  "manulife": "/logos/manulife.svg",
  "sun life": "/logos/sunlife.png",
  "ontario teachers pension plan": "/logos/otpp.png",
  "thomson reuters": "/logos/thomsonreuters.png",
  "autodesk": "/logos/autodesk.svg",
  "nvidia": "/logos/nvidia.svg",
  "arctic wolf": "/logos/arcticwolf.png",
  "geotab": "/logos/geotab.png",
  "d2l": "/logos/d2l.svg",
  "hootsuite": "/logos/hootsuite.png",
  "doordash": "/logos/doordash.svg",
  "okta": "/logos/okta.svg",
  "lyft": "/logos/lyft.svg",
  "aws": "/logos/amazon.svg",
  "amazon web services": "/logos/amazon.svg",
  "royal bank of canada": "/logos/rbc.svg",
  "ontario teachers": "/logos/otpp.png",
};

export const KNOWN_BLURRY_COMPANIES = new Set<string>();

/**
 * Companies whose brand marks are dark/black monochrome.
 * In dark mode, these marks are placed on a neutral subtle backplate
 * so they remain completely visible and crisp without pixel inversion.
 */
export const DARK_MONOCHROME_COMPANIES = new Set([
  "eq bank",
  "google",
  "telus",
  "clio",
  "notion",
  "palantir",
  "vercel",
  "planetscale",
  "anyscale",
  "runway",
  "runwayml",
  "mercury",
  "carta",
  "samsara",
  "faire",
  "waabi",
  "render",
  "pointclickcare",
  "point click care",
  "scale ai",
  "scale",
  "plaid",
  "github",
  "wealthsimple",
  "flexport",
  "sentry",
  "amazon",
  "aws",
  "autodesk",
  "nvidia",
  "manulife",
  "geotab",
  "sun life",
  "datadog",
  "spacex",
]);

/**
 * Companies whose brand marks are white monochrome.
 * In light mode, these marks are placed on a neutral dark backplate
 * so they remain completely visible without pixel distortion.
 */
export const LIGHT_MONOCHROME_COMPANIES = new Set([
  "shopify",
  "rogers",
  "stability ai",
  "stability",
]);

export function isDarkMonochromeLogo(company: string): boolean {
  if (!company) return false;
  return DARK_MONOCHROME_COMPANIES.has(normalizeCompanyName(company));
}

export function isLightMonochromeLogo(company: string): boolean {
  if (!company) return false;
  return LIGHT_MONOCHROME_COMPANIES.has(normalizeCompanyName(company));
}

/**
 * Resolves a company name to a verified, high-resolution logo URL following strict fallback hierarchy:
 * 1. Company-level database asset URL (from API)
 * 2. Verified deterministic local logo (/logos/...)
 * 3. Null (triggers the generic company icon)
 */
export function getCompanyLogoUrl(company: string, apiLogoUrl?: string | null): string | null {
  const fromApi = trustedCompanyLogoUrl(company, apiLogoUrl);
  if (fromApi) return fromApi;
  if (!company) return null;
  return ownString(COMPANY_LOGOS, normalizeCompanyName(company)) ?? null;
}

function trustedCompanyLogoUrl(company: string, url?: string | null): string | null {
  const usable = usableLogoUrl(url);
  // The retired Braze file and unversioned database cache contain Delivery Hero artwork.
  // Prefer the official-domain favicon until a replacement asset has its own distinct URL.
  if (normalizeCompanyName(company) === "braze" && usable) {
    try {
      const asset = new URL(usable, "https://roleradar.invalid");
      if (asset.pathname === "/logos/braze.svg"
        || (/^\/api\/company-logos\/\d+\/?$/.test(asset.pathname) && !asset.search)) return null;
    } catch {
      return null;
    }
  }
  return usable;
}

/** Google serves the site's own favicon. Never guess a domain from an employer name or an ATS job URL. */
export function getCompanyFaviconUrl(company: string, websiteUrl?: string | null): string | null {
  let domain = ownString(COMPANY_DOMAIN_MAP, normalizeCompanyName(company));
  if (!domain && typeof websiteUrl === "string") {
    try {
      const website = new URL(websiteUrl);
      const host = website.hostname;
      if (website.protocol === "https:" && !website.username && !website.password && !website.port
        && /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/i.test(host)
        && !/(?:^|\.)(?:localhost|local|internal|test|invalid)$/.test(host)
        && !/(?:^|\.)(?:ashbyhq\.com|greenhouse\.io|myworkdayjobs\.com|lever\.co|workable\.com|smartrecruiters\.com)$/.test(host)) {
        domain = host;
      }
    } catch { /* An unverified website does not create a guessed icon. */ }
  }
  return domain ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=128` : null;
}

/** One source order for every surface, with no duplicate requests or retries after a failure. */
export function getCompanyLogoSources(company: string, apiLogoUrl?: string | null, websiteUrl?: string | null): string[] {
  return Array.from(new Set([
    getCompanyFaviconUrl(company, websiteUrl),
    trustedCompanyLogoUrl(company, apiLogoUrl),
    ownString(COMPANY_LOGOS, normalizeCompanyName(company)),
  ].filter((url): url is string => Boolean(url))));
}

/**
 * Extracts a clean, single-letter fallback initial from a company name.
 */
export function getCompanyInitial(company: string): string {
  if (!company) return "?";
  const trimmed = company.trim();
  const firstLetter = trimmed.replace(/^[^a-zA-Z0-9]+/, "").charAt(0);
  return firstLetter ? firstLetter.toUpperCase() : "?";
}

export interface CompanyWebsite {
  url: string;
  domain: string;
}

/**
 * Returns a verified company website URL and clean domain label,
 * or null if no verified domain exists in the curated mapping.
 * Strictly avoids guessing or fabricating domains.
 */
export function getCompanyWebsite(company?: string | null): CompanyWebsite | null {
  if (!company) return null;
  const normalized = normalizeCompanyName(company);
  const domain = ownString(COMPANY_DOMAIN_MAP, normalized);
  if (!domain) return null;
  return {
    url: `https://${domain}`,
    domain,
  };
}
