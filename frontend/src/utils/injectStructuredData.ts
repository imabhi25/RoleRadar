import type { JobDetail } from "../api/client";
import { buildJobPostingSchema, safeJsonLdString } from "./jobPostingSchema";
import { isIndividualJobRoute } from "./appRoute";

const SCRIPT_ID = "role-radar-job-posting-ld-json";
const CANONICAL_ID = "role-radar-canonical-link";
const NOINDEX_ID = "role-radar-job-noindex";

/**
 * Injects or updates the Schema.org JobPosting JSON-LD script and canonical link in document.head.
 *
 * IMPORTANT: JobPosting markup and job-specific canonical links are strictly restricted
 * to dedicated individual-job URLs (e.g. /jobs/:jobId or /job/:jobId).
 * On the general listing page (/jobs, /, /jobs?job=...), even when split-view auto-selects a job,
 * no JobPosting schema or job-specific canonical URL is added.
 *
 * When the job is unavailable (404/410/expired) on an individual job URL, cleanly removes
 * structured data and injects a noindex meta tag.
 */
export function updateJobStructuredData(
  status: "loading" | "ready" | "unavailable" | "error",
  job: JobDetail | null,
  siteUrl = typeof window !== "undefined" ? window.location.origin : "https://roleradar-jobs.vercel.app",
  pathname = typeof window !== "undefined" ? window.location.pathname : ""
): () => void {
  if (typeof document === "undefined") return () => {};

  // If not a dedicated individual-job route (e.g. general /jobs listing, stats, company):
  // Clean up any stale job structured data, job canonical, or noindex, and return early.
  if (!isIndividualJobRoute(pathname)) {
    document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => s.remove());
    document.querySelectorAll('link[rel="canonical"]').forEach((l) => {
      if (l.id === CANONICAL_ID || l.getAttribute("href")?.includes("/jobs/")) {
        l.remove();
      }
    });
    document.getElementById(NOINDEX_ID)?.remove();
    return () => {};
  }

  const existingScript =
    document.getElementById(SCRIPT_ID) ||
    document.querySelector('script[type="application/ld+json"]');
  const existingCanonical =
    document.getElementById(CANONICAL_ID) ||
    document.querySelector('link[rel="canonical"]');
  const existingNoindex = document.getElementById(NOINDEX_ID);

  if (status === "unavailable") {
    // Expired or deleted job on dedicated individual-job URL: remove structured data, mark noindex
    document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => s.remove());
    document.querySelectorAll('link[rel="canonical"]').forEach((l) => {
      if (l.id === CANONICAL_ID || l.getAttribute("href")?.includes("/jobs/")) {
        l.remove();
      }
    });
    if (!existingNoindex) {
      const meta = document.createElement("meta");
      meta.id = NOINDEX_ID;
      meta.name = "robots";
      meta.content = "noindex, nofollow";
      document.head.appendChild(meta);
    }
    return () => {
      document.getElementById(NOINDEX_ID)?.remove();
    };
  }

  // Remove any stale noindex
  existingNoindex?.remove();

  if (status === "ready" && job) {
    const schema = buildJobPostingSchema(job, { siteUrl });
    const allScripts = document.querySelectorAll('script[type="application/ld+json"]');
    if (schema) {
      let script = (document.getElementById(SCRIPT_ID) || existingScript || allScripts[0]) as HTMLScriptElement | null;
      if (!script) {
        script = document.createElement("script");
        script.id = SCRIPT_ID;
        script.type = "application/ld+json";
        document.head.appendChild(script);
      } else {
        script.id = SCRIPT_ID;
      }
      script.textContent = safeJsonLdString(schema);

      // Clean up any extra duplicate LD-JSON scripts
      allScripts.forEach((s) => {
        if (s !== script) s.remove();
      });
    } else {
      allScripts.forEach((s) => s.remove());
    }

    // Set canonical link for individual job
    const allCanonicals = document.querySelectorAll('link[rel="canonical"]');
    let link = (document.getElementById(CANONICAL_ID) || existingCanonical || allCanonicals[0]) as HTMLLinkElement | null;
    if (!link) {
      link = document.createElement("link");
      link.id = CANONICAL_ID;
      link.rel = "canonical";
      document.head.appendChild(link);
    } else {
      link.id = CANONICAL_ID;
    }
    link.href = `${siteUrl}/jobs/${encodeURIComponent(job.job_id)}`;
    allCanonicals.forEach((l) => {
      if (l !== link) l.remove();
    });
  } else if (status === "loading" || status === "error") {
    // Clear previous structured data while next is loading or on error
    document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => s.remove());
    document.querySelectorAll('link[rel="canonical"]').forEach((l) => {
      if (l.id === CANONICAL_ID || l.getAttribute("href")?.includes("/jobs/")) {
        l.remove();
      }
    });
  }

  return () => {
    document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => s.remove());
    document.getElementById(CANONICAL_ID)?.remove();
    document.getElementById(NOINDEX_ID)?.remove();
  };
}
