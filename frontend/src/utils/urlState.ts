import type { SelectedFilters } from "../components/JobFilters";

export interface ParsedUrlState {
  filters: SelectedFilters;
  page: number;
  jobId: string | null;
}

const CANONICAL_COUNTRIES: Record<string, string> = {
  "united states": "United States",
  "united_states": "United States",
  "usa": "United States",
  "us": "United States",
  "canada": "Canada",
  "ca": "Canada",
};

const CANONICAL_ROLES: Record<string, string> = {
  "full_time": "full_time",
  "full-time": "full_time",
  "fulltime": "full_time",
  "internship": "internship",
  "intern": "internship",
  "co_op": "co_op",
  "co-op": "co_op",
  "coop": "co_op",
  "new_grad": "new_grad",
  "new-grad": "new_grad",
  "newgrad": "new_grad",
  "entry_level": "entry_level",
  "entry-level": "entry_level",
  "entrylevel": "entry_level",
  "entry": "entry_level",
};

const CANONICAL_TERMS: Record<string, string> = {
  winter: "winter",
  summer: "summer",
  fall: "fall",
  autumn: "fall",
};

const CANONICAL_WORKPLACES: Record<string, string> = {
  "remote": "remote",
  "hybrid": "hybrid",
  "on_site": "on_site",
  "on-site": "on_site",
  "onsite": "on_site",
};

export const CANONICAL_SKILLS: Record<string, string> = {
  "python": "Python",
  "sql": "SQL",
  "aws": "AWS",
  "docker": "Docker",
  "postgresql": "PostgreSQL",
  "postgres": "PostgreSQL",
  "react": "React",
  "kubernetes": "Kubernetes",
  "k8s": "Kubernetes",
  "java": "Java",
  "typescript": "TypeScript",
  "javascript": "JavaScript",
  "linux": "Linux",
  "gcp": "GCP",
  "c++": "C++",
  "go": "Go",
  "golang": "Go",
  "terraform": "Terraform",
  "graphql": "GraphQL",
  "azure": "Azure",
  "pytorch": "PyTorch",
  "fastapi": "FastAPI",
  "rust": "Rust",
  "html": "HTML",
  "css": "CSS",
  "c#": "C#",
  "ruby": "Ruby",
  "kafka": "Kafka",
  "node.js": "Node.js",
  "nodejs": "Node.js",
  ".net": ".NET",
  "kotlin": "Kotlin",
  "scala": "Scala",
  "swift": "Swift",
  "redis": "Redis",
  "mongodb": "MongoDB",
  "spark": "Spark",
};

/**
 * Parses search query string into canonical SelectedFilters and page number.
 * Normalizes harmless aliases, rejects invalid values, and deduplicates.
 */
/** The API refuses offsets past 100,000; with 20 jobs a page that is page 5,001. Larger values in a URL are clamped. */
export const MAX_PAGE = 5000;

export function parseUrlSearch(search: string): ParsedUrlState {
  const params = new URLSearchParams(search);

  // Country: absent/invalid/"all"/both countries = no country filter (all countries); otherwise the single selected country.
  const rawCountry = params.get("country") || "";
  let countryList: string[] = [];
  rawCountry.split(",").forEach((item) => {
    const clean = item.trim().toLowerCase();
    const canonical = CANONICAL_COUNTRIES[clean];
    if (canonical && !countryList.includes(canonical)) {
      countryList.push(canonical);
    }
  });
  if (countryList.length > 1) countryList = [];

  // Role
  const rawRole = params.get("role") || "";
  const roleList: string[] = [];
  rawRole.split(",").forEach((item) => {
    const clean = item.trim().toLowerCase();
    const canonical = CANONICAL_ROLES[clean];
    if (canonical && !roleList.includes(canonical)) {
      roleList.push(canonical);
    }
  });

  // Term (academic season)
  const termList: string[] = [];
  (params.get("term") || "").split(",").forEach((item) => {
    const canonical = CANONICAL_TERMS[item.trim().toLowerCase()];
    if (canonical && !termList.includes(canonical)) {
      termList.push(canonical);
    }
  });

  // Workplace
  const rawWorkplace = params.get("workplace") || "";
  const workplaceList: string[] = [];
  rawWorkplace.split(",").forEach((item) => {
    const clean = item.trim().toLowerCase();
    const canonical = CANONICAL_WORKPLACES[clean];
    if (canonical && !workplaceList.includes(canonical)) {
      workplaceList.push(canonical);
    }
  });

  // Date / Freshness
  const rawDate = (params.get("date") || "").trim().toLowerCase();
  // The default (and any unknown/legacy value such as "all") is the public 30-day window ("30d" is that same window).
  const freshness: SelectedFilters["freshness"] =
    rawDate === "today" || rawDate === "week" || rawDate === "14d"
      ? rawDate
      : rawDate === "7d"
      ? "week"
      : "recent";

  // Page: must be an integer >= 1, otherwise defaults to 1
  const rawPage = params.get("page");
  let page = 1;
  if (rawPage) {
    const parsed = parseInt(rawPage, 10);
    if (/^\d+$/.test(rawPage) && Number.isSafeInteger(parsed) && parsed >= 1) {
      page = Math.min(parsed, MAX_PAGE);
    }
  }

  // Known skills have stable spelling; safe new API skills survive shared URLs.
  const rawSkill = (params.get("skill") || "").trim();
  let canonicalSkill = "";
  if (rawSkill) {
    const matched = CANONICAL_SKILLS[rawSkill.toLowerCase()];
    if (matched) {
      canonicalSkill = matched;
    } else if (rawSkill.length <= 80 && /^[\p{L}\p{N} .+#/-]+$/u.test(rawSkill)) {
      canonicalSkill = rawSkill;
    }
  }

  // Location: read repeated location parameters preserving commas
  const locationList: string[] = [];
  const rawLocations = params.getAll("location");
  for (const raw of rawLocations) {
    const clean = raw.trim();
    if (clean && !locationList.includes(clean)) {
      locationList.push(clean);
    }
  }

  // Experience level
  const rawExp = params.get("exp") || params.get("experience") || params.get("experience_level") || "";
  const expList: string[] = [];
  rawExp.split(",").forEach((item) => {
    const clean = item.trim().toLowerCase();
    if (["internship", "entry", "mid", "senior"].includes(clean) && !expList.includes(clean)) {
      expList.push(clean);
    }
  });

  // Min compensation & currency
  const rawMinComp = params.get("min_comp") || params.get("min_compensation") || "";
  let minCompensation: number | null = null;
  if (/^\d+$/.test(rawMinComp)) {
    const parsed = parseInt(rawMinComp, 10);
    if (parsed > 0) minCompensation = parsed;
  }
  const rawCurr = (params.get("currency") || params.get("compensation_currency") || "").trim().toUpperCase();
  const compensationCurrency = ["CAD", "USD"].includes(rawCurr) ? rawCurr : null;

  // Sponsorship
  const rawSponsorship = (params.get("sponsorship") || "").trim().toLowerCase();
  const sponsorship: SelectedFilters["sponsorship"] =
    rawSponsorship === "available" || rawSponsorship === "not_required" ? rawSponsorship : "all";

  const filters: SelectedFilters = {
    sort: (["recommended", "newest", "oldest", "company", "title"].includes(params.get("sort") || "") ? params.get("sort") : "recommended") as SelectedFilters["sort"],
    search: (params.get("q") || params.get("search") || "").trim(),
    country: countryList,
    location: locationList,
    company: (params.get("company") || "").trim(),
    skill: canonicalSkill,
    workplace_type: workplaceList,
    role_type: roleList,
    experience_level: expList,
    min_compensation: minCompensation,
    compensation_currency: compensationCurrency,
    sponsorship,
    term: termList,
    freshness,
  };

  return { filters, page, jobId: params.get("job")?.trim() || null };
}

/**
 * Serializes filters and page into a canonical URL search string.
 */
export function serializeUrlSearch(filters: SelectedFilters, page: number, jobId: string | null = null): string {
  const params = new URLSearchParams();
  if (jobId) params.set("job", jobId);
  if (filters.sort && filters.sort !== "recommended") params.set("sort", filters.sort);

  if (filters.search && filters.search.trim()) {
    params.set("q", filters.search.trim());
  }

  if (filters.role_type && filters.role_type.length > 0) {
    const canonicalRoles = Array.from(
      new Set(
        filters.role_type
          .map((r) => CANONICAL_ROLES[r.toLowerCase().trim()] || r)
          .filter(Boolean)
      )
    );
    if (canonicalRoles.length > 0) {
      params.set("role", canonicalRoles.join(","));
    }
  }

  if (filters.experience_level && filters.experience_level.length > 0) {
    const canonicalExp = Array.from(
      new Set(filters.experience_level.map((e) => e.trim().toLowerCase()).filter(Boolean))
    );
    if (canonicalExp.length > 0) {
      params.set("exp", canonicalExp.join(","));
    }
  }

  if (filters.location && filters.location.length > 0) {
    const canonicalLocations = Array.from(
      new Set(filters.location.map((l) => l.trim()).filter(Boolean))
    );
    for (const loc of canonicalLocations) {
      params.append("location", loc);
    }
  }

  if (typeof filters.min_compensation === "number" && filters.min_compensation > 0) {
    params.set("min_comp", filters.min_compensation.toString());
    if (filters.compensation_currency) {
      params.set("currency", filters.compensation_currency);
    }
  }

  if (filters.sponsorship && filters.sponsorship !== "all") {
    params.set("sponsorship", filters.sponsorship);
  }

  if (filters.term && filters.term.length > 0) {
    const canonicalTerms = Array.from(
      new Set(filters.term.map((t) => CANONICAL_TERMS[t.toLowerCase().trim()]).filter(Boolean))
    );
    if (canonicalTerms.length > 0) {
      params.set("term", canonicalTerms.join(","));
    }
  }

  if (filters.freshness && filters.freshness !== "recent") {
    params.set("date", filters.freshness);
  }

  // All countries is the default and stays out of the URL; only an explicit single country is serialized.
  const canonicalCountries = Array.from(
    new Set(
      (filters.country || [])
        .map((c) => CANONICAL_COUNTRIES[c.toLowerCase().trim()] || c)
        .filter((c) => c === "United States" || c === "Canada")
    )
  );
  if (canonicalCountries.length === 1) params.set("country", canonicalCountries[0]);

  if (filters.workplace_type && filters.workplace_type.length > 0) {
    const canonicalWorkplaces = Array.from(
      new Set(
        filters.workplace_type
          .map((w) => CANONICAL_WORKPLACES[w.toLowerCase().trim()] || w)
          .filter(Boolean)
      )
    );
    if (canonicalWorkplaces.length > 0) {
      params.set("workplace", canonicalWorkplaces.join(","));
    }
  }

  if (filters.company && filters.company.trim()) {
    params.set("company", filters.company.trim());
  }

  if (filters.skill && filters.skill.trim()) {
    params.set("skill", filters.skill.trim());
  }

  if (page > 1) {
    params.set("page", page.toString());
  }

  const qs = params.toString();
  return qs ? `?${qs}` : "";
}
