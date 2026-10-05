export interface OverviewStats {
  total_postings: number;
  total_companies: number;
  total_locations: number;
  total_skills: number;
  recently_posted_postings?: number;
  last_refreshed_at?: string | null;
}

export interface CountryStats {
  country: string;
  postings: number;
  share_pct: number;
}

export interface SkillStats {
  rank: number;
  skill: string;
  mentions: number;
  frequency_pct: number;
}

export interface JobSummary {
  job_id: string;
  title: string;
  company: string;
  company_logo_url?: string | null;
  company_logo_status?: string | null;
  location: string;
  country: string;
  workplace_type: string;
  role_type?: string;
  experience_level?: string | null;
  source_name: string;
  source_url?: string | null;
  company_apply_url?: string | null;
  linkedin_url?: string | null;
  simplify_url?: string | null;
  term_season?: string | null;
  term_year?: number | null;
  academic_term?: string | null;
  posted_at?: string | null;
  /** "date" when the source only publishes a day (no time of day); otherwise a full timestamp. */
  posted_at_precision?: "date" | "timestamp" | string | null;
  created_at?: string | null;
  freshness_status?: "recently_posted" | "recently_discovered" | "stale" | "inactive" | string;
  skills: string[];
  locations?: { location: string; country: string; source_location?: string }[];
  compensation?: { compensationTierSummary?: string; scrapeableCompensationSalarySummary?: string; [key: string]: unknown } | null;
}

export interface JobListResponse {
  total: number;
  limit: number;
  offset: number;
  jobs: JobSummary[];
}

export interface JobFilterOptions {
  countries: string[];
  companies: string[];
  skills: string[];
  workplace_types: string[];
  role_types?: string[];
  locations?: string[];
  experience_levels?: string[];
}

export interface CompanyInfo {
  id?: number;
  name: string;
  logo_url?: string | null;
  logo_source_url?: string | null;
  logo_status: "verified" | "unresolved" | string;
  website_url?: string | null;
  active_jobs_count: number;
}

export interface JobDetail {
  job_id: string;
  title: string;
  company: string;
  company_logo_url?: string | null;
  company_logo_status?: string | null;
  company_website_url?: string | null;
  location: string;
  country: string;
  workplace_type: string;
  role_type?: string;
  experience_level?: string | null;
  source_name: string;
  source_url?: string | null;
  company_apply_url?: string | null;
  linkedin_url?: string | null;
  simplify_url?: string | null;
  term_season?: string | null;
  term_year?: number | null;
  academic_term?: string | null;
  posted_at?: string | null;
  /** "date" when the source only publishes a day (no time of day); otherwise a full timestamp. */
  posted_at_precision?: "date" | "timestamp" | string | null;
  created_at?: string | null;
  freshness_status?: "recently_posted" | "recently_discovered" | "stale" | "inactive" | string;
  description?: string | null;
  skills: string[];
  locations?: { location: string; country: string; source_location?: string }[];
  compensation?: { compensationTierSummary?: string; scrapeableCompensationSalarySummary?: string; [key: string]: unknown } | null;
}

export interface BreakdownItem {
  category: string;
  count: number;
  share_pct: number;
}

export interface JobQueryParams {
  sort?: "recommended" | "newest" | "oldest" | "company" | "title";
  limit?: number;
  offset?: number;
  search?: string;
  q?: string;
  country?: string | string[];
  location?: string | string[];
  company?: string;
  skill?: string;
  workplace_type?: string | string[];
  role_type?: string | string[];
  experience_level?: string | string[];
  min_compensation?: number | null;
  compensation_currency?: string | null;
  sponsorship?: "all" | "available" | "not_required" | string;
  term?: string | string[];
  freshness?: "recent" | "today" | "week" | "14d" | string;
}


const configuredBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
export const API_BASE_URL = (configuredBase || (import.meta.env.DEV ? "http://127.0.0.1:8000" : "")).replace(/\/+$/, "");
if (import.meta.env.PROD && API_BASE_URL && !API_BASE_URL.startsWith("https://")) {
  throw new Error("Production VITE_API_BASE_URL must use HTTPS");
}

export function resolveApiAsset(url: string): string {
  return url.startsWith("/api/") ? `${API_BASE_URL}${url}` : url;
}

/** A non-2xx API response. Carries the status only; response bodies (e.g. a WAF block page) are never surfaced. */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, endpoint: string) {
    super(`API error: ${status} from ${endpoint}`);
    this.name = "ApiError";
    this.status = status;
  }
}

/** True when API requests go to another origin than the page (production calls the API host directly). */
function isCrossOrigin(base: string): boolean {
  if (!base || typeof window === "undefined") return false;
  try {
    return new URL(base, window.location.href).origin !== window.location.origin;
  } catch {
    return false;
  }
}

/**
 * GET with one same-origin retry. A cross-origin response that carries no CORS headers (an edge firewall's block page, a
 * proxy error) is invisible to the browser: it surfaces as a bare network failure with no status. The same request through
 * the site's own /api proxy is same-origin, so the real status is readable, and a transient cross-origin failure heals.
 * Aborts and failures of the retry itself are surfaced unchanged.
 */
async function fetchWithProxyFallback(endpoint: string, signal?: AbortSignal): Promise<Response> {
  try {
    return await fetch(`${API_BASE_URL}${endpoint}`, { signal });
  } catch (err) {
    if (signal?.aborted || !(err instanceof TypeError) || !isCrossOrigin(API_BASE_URL)) throw err;
    return fetch(endpoint, { signal });
  }
}

async function fetchJson<T>(endpoint: string, signal?: AbortSignal): Promise<T> {
  const response = await fetchWithProxyFallback(endpoint, signal);
  if (!response.ok) throw new ApiError(response.status, endpoint);
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("text/html")) {
    throw new ApiError(response.status, endpoint);
  }
  return response.json() as Promise<T>;
}

export interface SourceStatus {
  source_name: string;
  status: "healthy" | "degraded" | "unknown";
  companies_tracked: number;
  companies_ok: number;
  companies_degraded: number;
  active_jobs: number;
  last_success_at: string | null;
  last_attempt_at: string | null;
}

export const apiClient = {
  /** Per-source refresh health; optional, never required to browse jobs. */
  getSourceStatus: (signal?: AbortSignal): Promise<SourceStatus[]> =>
    fetchJson<SourceStatus[]>("/api/sources/status", signal),
  /** `country` scopes every figure the same way /api/jobs does; omit it for the all-country totals. */
  getOverview: (country?: string[]): Promise<OverviewStats> => {
    const query = country && country.length > 0 ? `?country=${encodeURIComponent(country.join(","))}` : "";
    return fetchJson<OverviewStats>(`/api/stats/overview${query}`);
  },
  getCountries: (): Promise<CountryStats[]> =>
    fetchJson<CountryStats[]>("/api/stats/countries"),
  getSkills: (): Promise<SkillStats[]> =>
    fetchJson<SkillStats[]>("/api/stats/skills"),
  getRoleStats: (): Promise<BreakdownItem[]> =>
    fetchJson<BreakdownItem[]>("/api/stats/roles"),
  getWorkplaceStats: (): Promise<BreakdownItem[]> =>
    fetchJson<BreakdownItem[]>("/api/stats/workplace"),
  getCompanyStats: (): Promise<BreakdownItem[]> =>
    fetchJson<BreakdownItem[]>("/api/stats/companies"),
  getJobs: (params?: JobQueryParams, signal?: AbortSignal): Promise<JobListResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.sort) searchParams.set("sort", params.sort);
    if (params?.limit !== undefined) {
      searchParams.set("limit", params.limit.toString());
    }
    if (params?.offset !== undefined) {
      searchParams.set("offset", params.offset.toString());
    }
    const rawSearch = (params?.q || params?.search || "").trim();
    if (rawSearch) {
      searchParams.set("q", rawSearch);
    }
    if (params?.country) {
      const val = Array.isArray(params.country)
        ? params.country.map((c) => c.trim()).filter(Boolean).join(",")
        : params.country.trim();
      if (val) {
        searchParams.set("country", val);
      }
    }
    if (params?.location) {
      const locs = Array.isArray(params.location) ? params.location : [params.location];
      for (const loc of locs) {
        const trimmed = loc.trim();
        if (trimmed) {
          searchParams.append("location", trimmed);
        }
      }
    }
    if (params?.company && params.company.trim()) {
      searchParams.set("company", params.company.trim());
    }
    if (params?.skill && params.skill.trim()) {
      searchParams.set("skill", params.skill.trim());
    }
    if (params?.workplace_type) {
      const val = Array.isArray(params.workplace_type)
        ? params.workplace_type.map((w) => w.trim()).filter(Boolean).join(",")
        : params.workplace_type.trim();
      if (val) {
        searchParams.set("workplace_type", val);
      }
    }
    if (params?.role_type) {
      const val = Array.isArray(params.role_type)
        ? params.role_type.map((r) => r.trim()).filter(Boolean).join(",")
        : params.role_type.trim();
      if (val) {
        searchParams.set("role_type", val);
      }
    }
    if (params?.experience_level) {
      const val = Array.isArray(params.experience_level)
        ? params.experience_level.map((e) => e.trim()).filter(Boolean).join(",")
        : params.experience_level.trim();
      if (val) {
        searchParams.set("experience_level", val);
      }
    }
    if (typeof params?.min_compensation === "number" && params.min_compensation > 0) {
      searchParams.set("min_compensation", params.min_compensation.toString());
    }
    if (params?.compensation_currency && params.compensation_currency.trim()) {
      searchParams.set("compensation_currency", params.compensation_currency.trim());
    }
    if (params?.sponsorship && params.sponsorship !== "all") {
      searchParams.set("sponsorship", params.sponsorship.trim());
    }
    if (params?.term) {
      const val = Array.isArray(params.term)
        ? params.term.map((t) => t.trim()).filter(Boolean).join(",")
        : params.term.trim();
      if (val) {
        searchParams.set("term", val);
      }
    }
    if (params?.freshness && params.freshness.trim() && params.freshness !== "recent") {
      searchParams.set("freshness", params.freshness.trim());
    }
    const queryString = searchParams.toString();
    const endpoint = queryString ? `/api/jobs?${queryString}` : "/api/jobs";
    return fetchJson<JobListResponse>(endpoint, signal);
  },
  getJobFilters: (): Promise<JobFilterOptions> =>
    fetchJson<JobFilterOptions>("/api/jobs/filters"),
  getJob: (jobId: string, signal?: AbortSignal): Promise<JobDetail> =>
    fetchJson<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}`, signal),
  getCompanies: (signal?: AbortSignal): Promise<CompanyInfo[]> =>
    fetchJson<CompanyInfo[]>("/api/companies", signal),
  getCompany: (companyName: string, signal?: AbortSignal): Promise<CompanyInfo> =>
    fetchJson<CompanyInfo>(`/api/companies/${encodeURIComponent(companyName)}`, signal),
};
