/**
 * Formatting utilities for job postings, locations, and dates.
 */

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

const plural = (count: number, unit: string) => `${count} ${unit}${count === 1 ? "" : "s"} ago`;

/**
 * True for a calendar date with no time of day: an explicit "date" precision, a bare YYYY-MM-DD, or the exact-midnight-UTC
 * placeholder date-only sources are stored as. Callers that do not know the precision (company page rows) still get the
 * employer's day instead of the previous day west of UTC.
 */
export function isDateOnly(iso: string, precision?: string | null): boolean {
  return precision === "date" || /^\d{4}-\d{2}-\d{2}$/.test(iso) || /T00:00:00(?:\.0+)?(?:Z|\+00:00)$/.test(iso);
}

/** Real timestamps use the viewer's calendar; date-only sources retain the employer's stated day. */
export function formatPostingDate(iso?: string | null, precision?: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    ...(isDateOnly(iso, precision) ? { timeZone: "UTC" } : {}),
  });
}

/**
 * Relative age of a posting from its real `posted_at` (never ingestion, sync or last-seen time):
 * "12 minutes ago", "2 hours ago", "23 hours ago", then, from 24 hours on, "1 day ago", "2 days ago", ...
 * Returns null when the timestamp is absent or invalid. `now` is injectable for tests.
 */
export function formatPostedDate(
  postedAt?: string | null,
  now: number = Date.now(),
  precision?: string | null
): string | null {
  if (!postedAt) return null;
  const posted = new Date(postedAt);
  const postedMs = posted.getTime();
  if (isNaN(postedMs)) return null;

  // Date-only sources (Workday, Amazon) know the day, not the hour: say "today"/"yesterday"/"N days ago" at day
  // granularity instead of inventing "5 hours ago" from a midnight placeholder.
  if (precision === "date" || /^\d{4}-\d{2}-\d{2}$/.test(postedAt)) {
    const current = new Date(now);
    const currentDay = Date.UTC(current.getFullYear(), current.getMonth(), current.getDate());
    const sourceDay = Date.UTC(posted.getUTCFullYear(), posted.getUTCMonth(), posted.getUTCDate());
    const days = Math.round((currentDay - sourceDay) / DAY_MS);
    if (days < 0) return null; // a date in the future is not an age
    if (days === 0) return "today";
    if (days === 1) return "yesterday";
    return plural(days, "day");
  }

  const diff = now - postedMs;
  // Small clock skew between the source and the browser reads as "just now"; a date further ahead is not an age.
  if (diff < 0) return diff >= -HOUR_MS ? "just now" : null;
  if (diff < MINUTE_MS) return "just now";
  if (diff < HOUR_MS) return plural(Math.floor(diff / MINUTE_MS), "minute");
  if (diff < DAY_MS) return plural(Math.floor(diff / HOUR_MS), "hour");

  const days = Math.floor(diff / DAY_MS);
  if (days < 60) return plural(days, "day");
  if (days < 365) return plural(Math.floor(days / 30), "month");
  return posted.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/**
 * Normalizes a single location segment with its country context.
 */
function normalizeLocationSegment(loc: string, country?: string): string {
  const cleanLoc = (loc || "").trim().replace(/\s+/g, " ");
  const cleanCountry = (country || "").trim();

  const isLocVague =
    !cleanLoc ||
    cleanLoc.toLowerCase() === "unknown" ||
    cleanLoc.toLowerCase() === "unspecified";
  const isCountryVague =
    !cleanCountry ||
    cleanCountry.toLowerCase() === "unknown" ||
    cleanCountry.toLowerCase() === "unspecified";

  if (isLocVague && isCountryVague) return "";
  if (isCountryVague) return cleanLoc;
  if (isLocVague) return cleanCountry;

  const locLower = cleanLoc.toLowerCase();
  const countryLower = cleanCountry.toLowerCase();

  if (locLower === countryLower) return cleanCountry;
  if (locLower.endsWith(countryLower)) return cleanLoc;
  if (
    countryLower === "united kingdom" &&
    (locLower.endsWith(", uk") || locLower.endsWith(" uk"))
  ) {
    return cleanLoc;
  }
  if (
    countryLower === "united states" &&
    (locLower.endsWith(", usa") || locLower.endsWith(", us"))
  ) {
    return cleanLoc;
  }
  if (countryLower === "united states") return cleanLoc;
  if (countryLower === "canada" && !locLower.includes("canada")) {
    return `${cleanLoc}, Canada`;
  }
  if (
    countryLower === "united kingdom" &&
    !locLower.includes("uk") &&
    !locLower.includes("united kingdom")
  ) {
    return `${cleanLoc}, UK`;
  }
  return cleanLoc;
}

/**
 * Formats location and country for display.
 * Avoids displaying country="Unknown" or repeating city/country.
 */
export function formatLocation(location: string, country: string): string {
  return cleanLocationDisplay(location, country, false).full;
}

/**
 * Display formatting utility for raw location strings that may contain:
 * - mixed delimiters (;, |)
 * - duplicate identical location segments
 * - excessively long multi-city lists (up to 200+ characters)
 *
 * Does NOT destructively alter stored data.
 * Returns both a full cleaned string and a compact card-optimized string.
 */
export function cleanLocationDisplay(
  rawLocation: string,
  country?: string,
  isCardView: boolean = false
): { display: string; full: string } {
  if (!rawLocation && !country) {
    return { display: "", full: "" };
  }

  // Split on delimiters: semicolons, pipes, or newlines
  const rawSegments = (rawLocation || "")
    .split(/[;|]+|\r?\n/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  if (rawSegments.length === 0) {
    const fallback = normalizeLocationSegment("", country);
    return { display: fallback, full: fallback };
  }

  // Deduplicate case-insensitively while preserving original order and capitalization
  const seen = new Set<string>();
  const uniqueSegments: string[] = [];
  for (const seg of rawSegments) {
    const normalized = normalizeLocationSegment(seg, country);
    if (!normalized) continue;
    const lowerKey = normalized.toLowerCase();
    if (!seen.has(lowerKey)) {
      seen.add(lowerKey);
      uniqueSegments.push(normalized);
    }
  }

  if (uniqueSegments.length === 0) {
    const fallback = normalizeLocationSegment("", country);
    return { display: fallback, full: fallback };
  }

  const full = uniqueSegments.join(" • ");

  if (!isCardView || uniqueSegments.length <= 1) {
    return { display: full, full };
  }

  if (uniqueSegments.length === 2) {
    if (uniqueSegments[0].length + uniqueSegments[1].length < 45) {
      return { display: `${uniqueSegments[0]} • ${uniqueSegments[1]}`, full };
    }
    return { display: `${uniqueSegments[0]} +1 more`, full };
  }

  if (uniqueSegments[0].length + uniqueSegments[1].length < 40) {
    const remaining = uniqueSegments.length - 2;
    return {
      display: `${uniqueSegments[0]} • ${uniqueSegments[1]} +${remaining} more`,
      full,
    };
  }

  const remaining = uniqueSegments.length - 1;
  return {
    display: `${uniqueSegments[0]} +${remaining} more`,
    full,
  };
}

/**
 * Returns a clean display name for the ATS source.
 */
export function formatSource(sourceName: string): string {
  if (!sourceName) return "";
  const lower = sourceName.toLowerCase();
  if (lower === "ashby") return "Ashby";
  if (lower === "greenhouse") return "Greenhouse";
  if (lower === "lever") return "Lever";
  return sourceName.charAt(0).toUpperCase() + sourceName.slice(1);
}

/**
 * Formats workplace type for display badges and stats.
 */
export function formatWorkplaceType(type?: string): string {
  if (!type || type.toLowerCase() === "unspecified") return "Unspecified";
  const lower = type.toLowerCase().trim();
  if (lower === "remote") return "Remote";
  if (lower === "hybrid") return "Hybrid";
  if (lower === "onsite" || lower === "on-site") return "On-site";
  return type.charAt(0).toUpperCase() + type.slice(1).toLowerCase();
}

/**
 * Formats role type for display badges, filters, and stats.
 * Strictly maps:
 * - full_time -> Full-time
 * - co_op -> Co-op
 * - new_grad -> New Grad
 * - entry_level -> Entry Level
 * - internship -> Internship
 */
export function formatRoleType(type?: string): string {
  if (!type || type.toLowerCase() === "unspecified" || type.toLowerCase() === "unknown") return "Unspecified";
  const lower = type.toLowerCase().trim().replace(/_/g, " ");
  if (lower === "co op" || lower === "co-op" || lower === "coop") return "Co-op";
  if (lower === "new grad" || lower === "new-grad") return "New Grad";
  if (lower === "entry level" || lower === "entry-level") return "Entry Level";
  if (lower === "full time" || lower === "full-time") return "Full-time";
  if (lower === "internship" || lower === "intern") return "Internship";
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

/** Display-only title separators; the employer title and original posting stay intact. */
export function formatJobTitle(title: string): string {
  return title.replace(/\s*,\s*/g, " – ");
}
