import { lazy, Suspense, useEffect, useState, useCallback, useRef } from "react";
import { apiClient, type OverviewStats } from "./api/client";
import { JobExplorer } from "./components/JobExplorer";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ExternalArrow } from "./components/ExternalArrow";
import type { SelectedFilters } from "./components/JobFilters";
import { parseUrlSearch, serializeUrlSearch, type ParsedUrlState } from "./utils/urlState";
import { parseAppRoute, type AppView } from "./utils/appRoute";

// Analytics and the dev-only logo sheet are optional: they load on demand and can fail without touching Jobs.
const StatsView = lazy(() => import("./components/StatsView"));
const CompanyPageView = lazy(() => import("./components/CompanyPageView"));
const CompanyContactSheet = import.meta.env.DEV
  ? lazy(() => import("./components/CompanyContactSheet").then((m) => ({ default: m.CompanyContactSheet })))
  : null;

function isPlainClick(event: React.MouseEvent): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

const THEME_STORAGE_KEY = "roleradar-theme";

export function App() {
  // Totals for the selected country (header count, Market overview). Optional: Jobs never waits on this.
  const [scopedOverview, setScopedOverview] = useState<OverviewStats | null>(null);

  const [initialRoute] = useState(() => parseAppRoute(window.location.pathname, window.location.search, import.meta.env.DEV));
  const [selectedCompany, setSelectedCompany] = useState<string | null>(initialRoute.company);
  const [activeView, setActiveView] = useState<AppView>(initialRoute.view);

  // Light by default; a saved choice wins, otherwise the system setting. The toggle in the navbar changes and saves it.
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    try {
      const saved = localStorage.getItem(THEME_STORAGE_KEY);
      if (saved === "light" || saved === "dark") return saved;
    } catch { /* storage may be disabled */ }
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch { /* storage may be disabled */ }
  };

  // Synchronized URL state (canonical filters and page number)
  const [urlState, setUrlState] = useState<ParsedUrlState>(() =>
    parseUrlSearch(window.location.search)
  );

  const savedJobsQueryRef = useRef<string>(window.location.search || "");
  const prevSearchQueryRef = useRef<string>(urlState.filters.search);
  const isSearchSessionActiveRef = useRef<boolean>(false);

  useEffect(() => {
    if (window.location.pathname === "/") {
      window.history.replaceState(null, "", "/jobs" + window.location.search);
    }

    // Canonicalize initial URL search params if needed
    if (window.location.pathname === "/jobs" || window.location.pathname === "/") {
      const parsed = parseUrlSearch(window.location.search);
      const canonicalSearch = serializeUrlSearch(parsed.filters, parsed.page, parsed.jobId);
      if (window.location.search !== canonicalSearch) {
        window.history.replaceState(null, "", `/jobs${canonicalSearch}`);
        savedJobsQueryRef.current = canonicalSearch;
        setUrlState(parsed);
      }
    }

    const handlePopState = () => {
      const route = parseAppRoute(window.location.pathname, window.location.search, import.meta.env.DEV);
      setActiveView(route.view);
      if (route.view === "company" || route.view === "404") {
        setSelectedCompany(route.company);
      } else if (route.view === "jobs") {
        const parsed = parseUrlSearch(window.location.search);
        setUrlState(parsed);
        savedJobsQueryRef.current = window.location.search;
        isSearchSessionActiveRef.current = false;
        prevSearchQueryRef.current = parsed.filters.search;
      }
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (activeView === "jobs") {
      document.title = "RoleRadar — Software Jobs";
    } else if (activeView === "stats") {
      document.title = "Market Analytics — RoleRadar";
    } else if (activeView === "company") {
      document.title = selectedCompany
        ? `${selectedCompany} — Company Profile & Jobs — RoleRadar`
        : "Hiring Companies — RoleRadar";
    } else if (activeView === "logos") {
      document.title = "Company Logos & Branding — RoleRadar";
    } else if (activeView === "404") {
      document.title = "Page not found — RoleRadar";
    }
  }, [activeView, selectedCompany]);

  // An unknown address is served the app shell (the host cannot return a 404 for SPA routes), so tell crawlers not to index it.
  useEffect(() => {
    if (activeView !== "404") return;
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, [activeView]);

  const navigateTo = (view: "jobs" | "stats" | "logos", search = "", isPush = true) => {
    setActiveView(view);
    const targetUrl = `/${view}${search}`;
    if (isPush) {
      window.history.pushState(null, "", targetUrl);
    } else {
      window.history.replaceState(null, "", targetUrl);
    }
  };

  const handleNavJobsClick = () => {
    const search = savedJobsQueryRef.current || "";
    const parsed = parseUrlSearch(search);
    setUrlState(parsed);
    navigateTo("jobs", search, true);
  };

  const handleBackToJobsClick = () => {
    const search = savedJobsQueryRef.current || "";
    const parsed = parseUrlSearch(search);
    setUrlState(parsed);
    navigateTo("jobs", search, true);
  };

  const handleSelectJobFromCompany = (jobId: string) => {
    const next = { ...parseUrlSearch(""), jobId };
    setUrlState(next);
    const search = serializeUrlSearch(next.filters, 1, jobId);
    savedJobsQueryRef.current = search;
    setActiveView("jobs");
    window.history.pushState(null, "", `/jobs${search}`);
  };

  const handleCompanyChange = (company: string | null) => {
    setSelectedCompany(company);
    const search = company ? `?company=${encodeURIComponent(company)}` : "";
    window.history.pushState(null, "", `/company${search}`);
  };

  const handleBrandClick = () => {
    const defaultState = parseUrlSearch("");
    savedJobsQueryRef.current = "";
    isSearchSessionActiveRef.current = false;
    prevSearchQueryRef.current = "";
    setUrlState(defaultState);
    navigateTo("jobs", "", true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // Stable identity: the explorer refetches its list when this changes, and selecting a job must not.
  const handleFiltersChange = useCallback((filters: SelectedFilters, page: number, isDiscrete = false) => {
    setUrlState({ filters, page, jobId: null });
    const newSearch = serializeUrlSearch(filters, page);
    savedJobsQueryRef.current = newSearch;

    if (isDiscrete) {
      isSearchSessionActiveRef.current = false;
      prevSearchQueryRef.current = filters.search;
      window.history.pushState(null, "", `/jobs${newSearch}`);
    } else {
      // Non-discrete update: debounced search or automated adjustment (e.g. page clamping)
      const searchChanged = filters.search !== prevSearchQueryRef.current;
      if (searchChanged) {
        if (!isSearchSessionActiveRef.current) {
          // First transition into an active search edit creates a new history entry
          window.history.pushState(null, "", `/jobs${newSearch}`);
          isSearchSessionActiveRef.current = Boolean(filters.search.trim());
        } else {
          // Subsequent keystrokes within the same active search session replace the entry
          window.history.replaceState(null, "", `/jobs${newSearch}`);
          if (!filters.search.trim()) {
            isSearchSessionActiveRef.current = false;
          }
        }
        prevSearchQueryRef.current = filters.search;
      } else {
        // Search did not change (e.g. out-of-bounds page clamping normalization)
        window.history.replaceState(null, "", `/jobs${newSearch}`);
      }
    }
  }, []);

  const handleSkillClick = (skill: string) => {
    const parsed = parseUrlSearch(`?skill=${encodeURIComponent(skill)}`);
    setUrlState(parsed);
    const search = serializeUrlSearch(parsed.filters, 1);
    savedJobsQueryRef.current = search;
    isSearchSessionActiveRef.current = false;
    prevSearchQueryRef.current = "";
    navigateTo("jobs", search, true);
  };

  // The selected country controls every job total on the Jobs page, so the header count and Market overview are
  // fetched for that country (the same scoping rule as the list); no selection means all-country totals. This is
  // independent of the job list: if it fails the Market overview card simply shows placeholders.
  const countryKey = urlState.filters.country.join(",");
  useEffect(() => {
    let cancelled = false;
    setScopedOverview(null); // never show the previous country's count next to the new country's list
    apiClient
      .getOverview(countryKey ? countryKey.split(",") : undefined)
      .then((data) => {
        if (!cancelled) setScopedOverview(data);
      })
      .catch((err) => {
        console.warn("Failed to load country totals:", err);
      });
    return () => {
      cancelled = true;
    };
  }, [countryKey]);

  return (
    <div className="roleradar-app">
      <a
        href="#content"
        className="skip-link"
        onClick={(event) => {
          // Focus the landmark directly: a hash change would fire popstate and re-run the app's URL routing.
          event.preventDefault();
          const main = document.getElementById("content");
          main?.focus({ preventScroll: true });
          main?.scrollIntoView({ block: "start" });
        }}
      >
        Skip to content
      </a>
      <header className="roleradar-navbar">
        <div className="navbar-inner">
          <div className="navbar-left">
            <button
              type="button"
              className="navbar-brand-btn"
              onClick={handleBrandClick}
              aria-label="RoleRadar homepage - Return to jobs"
            >
              <div className="brand-logo-mark" aria-hidden="true">
                <svg width="22" height="22" viewBox="0 0 28 28" fill="none">
                  <rect width="28" height="28" rx="8" fill="url(#brandGradient)" />
                  <path
                    d="M10 8.5H19V11.5H15V19.5H10.5V8.5Z"
                    fill="#ffffff"
                    fillRule="evenodd"
                  />
                  <circle cx="19" cy="18" r="2" fill="#93c5fd" />
                  <defs>
                    <linearGradient
                      id="brandGradient"
                      x1="0"
                      y1="0"
                      x2="28"
                      y2="28"
                      gradientUnits="userSpaceOnUse"
                    >
                      <stop stopColor="#2563eb" />
                      <stop offset="1" stopColor="#4f46e5" />
                    </linearGradient>
                  </defs>
                </svg>
              </div>
              <span className="brand-name">RoleRadar</span>
            </button>

            <nav className="navbar-nav" aria-label="Main navigation">
              <a
                href={`/jobs${savedJobsQueryRef.current || ""}`}
                id="nav-jobs"
                aria-current={activeView === "jobs" ? "page" : undefined}
                className={`nav-item ${activeView === "jobs" ? "active" : ""}`}
                onClick={(event) => {
                  if (isPlainClick(event)) {
                    event.preventDefault();
                    handleNavJobsClick();
                  }
                }}
              >
                Jobs
              </a>
              <a
                href="/stats"
                id="nav-stats"
                aria-current={activeView === "stats" ? "page" : undefined}
                className={`nav-item ${activeView === "stats" ? "active" : ""}`}
                onClick={(event) => {
                  if (isPlainClick(event)) {
                    event.preventDefault();
                    navigateTo("stats", "", true);
                  }
                }}
              >
                Stats
              </a>
              <a
                href="https://github.com/imabhi25/Jobber"
                target="_blank"
                rel="noopener noreferrer"
                className="nav-link"
              >
                GitHub <ExternalArrow className="external-link-arrow" size={12} />
              </a>
            </nav>
          </div>

          <button
            type="button"
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
              </svg>
            )}
          </button>
        </div>
      </header>

      <main id="content" tabIndex={-1} className="roleradar-main">
        {activeView === "404" ? (
          <div className="state-container">
            <h1>Page not found</h1>
            <p>The page you are looking for does not exist.</p>
            <button onClick={handleBrandClick} className="secondary-button">Return to jobs</button>
          </div>
        ) : (
          <>
            {/* Jobs stay mounted (hidden) while another page is open so search, scroll and the open job survive. */}
            <div className="tab-panel-jobs" hidden={activeView !== "jobs"} style={{ display: activeView === "jobs" ? "block" : "none" }}>
              <h1 className="visually-hidden">RoleRadar: software engineering jobs from company career pages</h1>
              <JobExplorer
                active={activeView === "jobs"}
                selectedJobId={urlState.jobId}
                onSelectJob={(jobId, options) => {
                  const next = { ...urlState, jobId };
                  setUrlState(next);
                  const search = serializeUrlSearch(next.filters, next.page, jobId);
                  savedJobsQueryRef.current = search;
                  if (options?.replace) {
                    // `auto` marks a job the app chose (desktop opens the first result) as opposed to one the reader
                    // picked. It lives in history.state so it survives reloads and Back/Forward.
                    window.history.replaceState(options.auto ? { autoJob: true } : null, "", `/jobs${search}`);
                  } else {
                    window.history.pushState(null, "", `/jobs${search}`);
                  }
                }}
                overview={scopedOverview}
                countryLabel={urlState.filters.country.length === 0 ? "All countries" : urlState.filters.country.join(", ")}
                onViewStats={() => navigateTo("stats", "", true)}
                filters={urlState.filters}
                page={urlState.page}
                onFiltersChange={handleFiltersChange}
              />
            </div>

            {activeView === "stats" && (
              <ErrorBoundary
                fallback={(reset) => (
                  <div className="state-container error-state" role="alert">
                    <h1 className="error-title">Stats are unavailable</h1>
                    <p className="error-message">The analytics page failed to load. Job search is unaffected.</p>
                    <button type="button" className="retry-button" onClick={reset}>Retry</button>
                    <button type="button" className="secondary-button" onClick={handleBackToJobsClick}>Back to Job Search</button>
                  </div>
                )}
              >
                <Suspense fallback={<div className="state-container loading-state"><div className="spinner" /><p>Loading market data…</p></div>}>
                  <StatsView onBackToJobs={handleBackToJobsClick} onSkillClick={handleSkillClick} />
                </Suspense>
              </ErrorBoundary>
            )}

            {activeView === "company" && (
              <ErrorBoundary
                fallback={(reset) => (
                  <div className="state-container error-state" role="alert">
                    <h1 className="error-title">Company profile unavailable</h1>
                    <p className="error-message">Failed to load company details. Job search is unaffected.</p>
                    <button type="button" className="retry-button" onClick={reset}>Retry</button>
                    <button type="button" className="secondary-button" onClick={handleBackToJobsClick}>Back to Job Search</button>
                  </div>
                )}
              >
                <Suspense fallback={<div className="state-container loading-state"><div className="spinner" /><p>Loading company profile…</p></div>}>
                  <CompanyPageView
                    initialCompany={selectedCompany}
                    onBackToJobs={handleBackToJobsClick}
                    onSelectJob={handleSelectJobFromCompany}
                    onCompanyChange={handleCompanyChange}
                  />
                </Suspense>
              </ErrorBoundary>
            )}

            {activeView === "logos" && CompanyContactSheet && (
              <ErrorBoundary fallback={() => <div className="state-container" role="alert"><p>The logo sheet failed to render.</p></div>}>
                <Suspense fallback={null}>
                  <CompanyContactSheet />
                </Suspense>
              </ErrorBoundary>
            )}
          </>
        )}
      </main>

    </div>
  );
}

export default App;
