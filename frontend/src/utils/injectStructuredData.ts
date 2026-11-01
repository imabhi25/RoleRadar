import type { JobDetail } from "../api/client";
import { buildJobPostingSchema, safeJsonLdString } from "./jobPostingSchema";

const SCRIPT_ID = "role-radar-job-posting-ld-json";
const CANONICAL_ID = "role-radar-canonical-link";
const NOINDEX_ID = "role-radar-job-noindex";

/**
 * Injects or updates the Schema.org JobPosting JSON-LD script and canonical link in document.head.
 * When the job is unavailable (404/410/expired), cleanly removes structured data and injects a noindex meta tag.
 */
export function updateJobStructuredData(
  status: "loading" | "ready" | "unavailable" | "error",
  job: JobDetail | null,
  siteUrl = typeof window !== "undefined" ? window.location.origin : "https://roleradar-jobs.vercel.app"
): () => void {
  if (typeof document === "undefined") return () => {};

  const existingScript =
    document.getElementById(SCRIPT_ID) ||
    document.querySelector('script[type="application/ld+json"]');
  const existingCanonical =
    document.getElementById(CANONICAL_ID) ||
    document.querySelector('link[rel="canonical"]');
  const existingNoindex = document.getElementById(NOINDEX_ID);

  if (status === "unavailable") {
    // Expired or deleted job: remove structured data, mark noindex
    document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => s.remove());
    document.querySelectorAll('link[rel="canonical"]').forEach((l) => l.remove());
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
    document.querySelectorAll('link[rel="canonical"]').forEach((l) => l.remove());
  }

  return () => {
    document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => s.remove());
    document.getElementById(CANONICAL_ID)?.remove();
    document.getElementById(NOINDEX_ID)?.remove();
  };
}
