/**
 * Utility for resolving and deduplicating multi-route job application links.
 * 
 * Priorities:
 * 1. Primary CTA: Official company or ATS application URL
 *    - Label is strictly "Apply ↗" (the URL is the employer's official job-specific posting, which may live on its ATS)
 *    - Never exposes ATS vendor names (Greenhouse, Lever, Ashby, Workday, etc.)
 * 2. Secondary Routes:
 *    - LinkedIn: "LinkedIn ↗"
 *    - Simplify: "Simplify ↗"
 *    - Strictly suppresses duplicates of the primary route
 *    - Strictly suppresses Indeed URLs
 */

export interface SecondaryApplyRoute {
  name: "LinkedIn" | "Simplify";
  label: string;
  url: string;
}

export interface ResolvedApplyRoutes {
  primaryUrl: string | null;
  primaryLabel: string;
  hasOfficialCompanyRoute: boolean;
  secondaryRoutes: SecondaryApplyRoute[];
}

export function isValidHttpUrl(url: string | null | undefined): boolean {
  if (!url || typeof url !== "string") return false;
  const trimmed = url.trim();
  if (trimmed.length < 10) return false;
  if (/[\s\r\n\t]/.test(trimmed)) return false;

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return false;
    }
    if (!parsed.hostname || !parsed.hostname.includes(".")) {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

export function isLinkedInJobUrl(url: string | null | undefined): boolean {
  if (!isValidHttpUrl(url)) return false;
  try {
    const parsed = new URL(url!.trim());
    const host = parsed.hostname.toLowerCase();
    if (!host.includes("linkedin.com")) return false;
    const path = parsed.pathname.toLowerCase();
    // Must be job-specific, not general company page or feed
    if (path.includes("/company/") || path.includes("/school/") || path.includes("/feed") || path.includes("/in/")) {
      return false;
    }
    return path.includes("/jobs/") || path.includes("/job/");
  } catch {
    return false;
  }
}

export function isSimplifyJobUrl(url: string | null | undefined): boolean {
  if (!isValidHttpUrl(url)) return false;
  try {
    const parsed = new URL(url!.trim());
    const host = parsed.hostname.toLowerCase();
    if (!host.includes("simplify.jobs")) return false;
    const path = parsed.pathname.toLowerCase();
    return (
      path.includes("/p/") ||
      path.includes("/c/") ||
      path.includes("/job/") ||
      path.includes("/jobs/")
    );
  } catch {
    return false;
  }
}

export function isIndeedUrl(url: string | null | undefined): boolean {
  if (!url || typeof url !== "string") return false;
  return url.toLowerCase().includes("indeed.com");
}

export function canonicalizeApplyUrl(url: string | null | undefined): string {
  if (!isValidHttpUrl(url)) return "";
  try {
    const parsed = new URL(url!.trim());
    parsed.hash = ""; // strip fragments like #apply

    // Remove tracking/marketing query parameters
    const trackingParams = new Set([
      "utm_source",
      "utm_medium",
      "utm_campaign",
      "utm_term",
      "utm_content",
      "ref",
      "source",
      "gh_src",
      "lever-source",
      "fbclid",
      "gclid",
      "_ga",
      "_gl",
      "trk",
      "trackingid",
      "tracking_id",
      "position",
      "pagenum",
    ]);

    const cleanParams = new URLSearchParams();
    parsed.searchParams.forEach((val, key) => {
      if (!trackingParams.has(key.toLowerCase())) {
        cleanParams.append(key, val);
      }
    });

    const queryStr = cleanParams.toString();
    const cleanPath = parsed.pathname.replace(/\/+$/, "");
    return `${parsed.protocol.toLowerCase()}//${parsed.host.toLowerCase()}${cleanPath}${
      queryStr ? `?${queryStr}` : ""
    }`;
  } catch {
    return (url || "").trim().toLowerCase().replace(/\/+$/, "");
  }
}

function normalizeApplicationUrl(url: string | null | undefined): string | null {
  if (!isValidHttpUrl(url)) return null;
  const parsed = new URL(url!.trim());
  const httpsHosts = ["greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "linkedin.com", "simplify.jobs"];
  if (parsed.protocol === "http:" && httpsHosts.some(host => parsed.hostname === host || parsed.hostname.endsWith(`.${host}`))) {
    parsed.protocol = "https:";
    return parsed.toString();
  }
  return url!.trim();
}

export function resolveApplyRoutes(job: {
  company_apply_url?: string | null;
  linkedin_url?: string | null;
  simplify_url?: string | null;
  source_url?: string | null;
}): ResolvedApplyRoutes {
  const cApply = normalizeApplicationUrl(job.company_apply_url);
  const cLinkedIn = normalizeApplicationUrl(job.linkedin_url);
  const cSimplify = normalizeApplicationUrl(job.simplify_url);
  const cSource = normalizeApplicationUrl(job.source_url);

  // Filter out forbidden Indeed targets
  const safeCompany = cApply && !isIndeedUrl(cApply) ? cApply : null;
  const safeLinkedIn = cLinkedIn && isLinkedInJobUrl(cLinkedIn) && !isIndeedUrl(cLinkedIn) ? cLinkedIn : null;
  const safeSimplify = cSimplify && isSimplifyJobUrl(cSimplify) && !isIndeedUrl(cSimplify) ? cSimplify : null;
  const safeSource = cSource && !isIndeedUrl(cSource) ? cSource : null;

  // Determine Primary CTA route
  // Priority: company_apply_url -> official source_url (if not LinkedIn/Simplify) -> linkedin_url -> simplify_url -> source_url
  let primaryUrl: string | null = null;
  let hasOfficialCompanyRoute = false;

  if (safeCompany) {
    primaryUrl = safeCompany;
    hasOfficialCompanyRoute = true;
  } else if (safeSource && !isLinkedInJobUrl(safeSource) && !isSimplifyJobUrl(safeSource)) {
    // Legacy or official ATS discovery URL
    primaryUrl = safeSource;
    hasOfficialCompanyRoute = true;
  } else if (safeLinkedIn) {
    primaryUrl = safeLinkedIn;
  } else if (safeSimplify) {
    primaryUrl = safeSimplify;
  } else if (safeSource) {
    primaryUrl = safeSource;
  }

  const primaryCanon = canonicalizeApplyUrl(primaryUrl);
  const secondaryRoutes: SecondaryApplyRoute[] = [];

  // Check LinkedIn route
  const resolvedLinkedIn = safeLinkedIn || (safeSource && isLinkedInJobUrl(safeSource) ? safeSource : null);
  if (resolvedLinkedIn) {
    const linkedInCanon = canonicalizeApplyUrl(resolvedLinkedIn);
    if (linkedInCanon && linkedInCanon !== primaryCanon) {
      secondaryRoutes.push({
        name: "LinkedIn",
        label: "LinkedIn ↗",
        url: resolvedLinkedIn,
      });
    }
  }

  // Check Simplify route
  const resolvedSimplify = safeSimplify || (safeSource && isSimplifyJobUrl(safeSource) ? safeSource : null);
  if (resolvedSimplify) {
    const simplifyCanon = canonicalizeApplyUrl(resolvedSimplify);
    const isDuplicateOfPrimary = simplifyCanon === primaryCanon;
    const isDuplicateOfLinkedIn = secondaryRoutes.some(
      (r) => canonicalizeApplyUrl(r.url) === simplifyCanon
    );

    if (simplifyCanon && !isDuplicateOfPrimary && !isDuplicateOfLinkedIn) {
      secondaryRoutes.push({
        name: "Simplify",
        label: "Simplify ↗",
        url: resolvedSimplify,
      });
    }
  }

  return {
    primaryUrl,
    primaryLabel: "Apply ↗",
    hasOfficialCompanyRoute,
    secondaryRoutes,
  };
}
