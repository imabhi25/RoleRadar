export type AppView = "jobs" | "stats" | "logos" | "company" | "404";

export interface AppRoute {
  view: AppView;
  company: string | null;
}

// Both initial rendering and browser history use this parser. A malformed
// percent escape must lead to a recoverable page, never throw during rendering.
export function parseAppRoute(path: string, search: string, dev = false): AppRoute {
  if (path === "/company" || path.startsWith("/company/")) {
    if (path.startsWith("/company/")) {
      try {
        return { view: "company", company: decodeURIComponent(path.slice("/company/".length)).trim() || null };
      } catch {
        return { view: "404", company: null };
      }
    }
    return { view: "company", company: new URLSearchParams(search).get("company") };
  }
  if (path === "/stats") return { view: "stats", company: null };
  if (dev && (path === "/logos" || path === "/companies")) return { view: "logos", company: null };
  if (path === "/jobs" || path === "/") return { view: "jobs", company: null };
  return { view: "404", company: null };
}
