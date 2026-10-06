import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  apiClient,
  ApiError,
  type JobSummary,
  type JobFilterOptions,
  type OverviewStats,
} from "../api/client";
import { JobCard } from "./JobCard";
import { SourceStatusNote } from "./SourceStatusNote";
import { JobFilters, NativeSelect, type SelectedFilters } from "./JobFilters";
import { JobDetailModal } from "./JobDetailModal";
import { JobDetailContent } from "./JobDetailContent";
import { useSplitView } from "../hooks/useMediaQuery";
import { resolveSkillFilter } from "../utils/skills";
import { SlowLoadHint } from "./SlowLoadHint";

const PAGE_SIZE = 20;
const SORT_OPTIONS = [
  { value: "recommended", label: "Recommended" },
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "company", label: "Company A–Z" },
  { value: "title", label: "Title A–Z" },
];
const PANE_EXIT_MS = 240;
const PANE_ENTER_MS = 260;
const PANE_STICKY_TOP = 76;

export interface JobExplorerProps {
  overview?: OverviewStats | null;
  /** Which country the overview numbers describe ("Canada", "All countries", ...). */
  countryLabel?: string;
  onViewStats?: () => void;
  filters: SelectedFilters;
  page: number;
  selectedJobId: string | null;
  /** Hidden Jobs stays mounted while other pages are open, without changing their URL. */
  active?: boolean;
  /** `replace` swaps the current history entry (used for keyboard browsing) instead of pushing one. */
  onSelectJob: (jobId: string | null, options?: { replace?: boolean; auto?: boolean }) => void;
  onFiltersChange: (filters: SelectedFilters, page: number, isDiscrete?: boolean) => void;
}

export const JobExplorer: React.FC<JobExplorerProps> = ({
  overview,
  countryLabel,
  onViewStats,
  filters,
  page,
  onFiltersChange,
  selectedJobId,
  onSelectJob,
  active = true,
}) => {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [draftSearch, setDraftSearch] = useState(filters.search);
  const searchPending = draftSearch.trim() !== filters.search.trim();
  const resultsPending = loading || searchPending;
  const [error, setError] = useState<string | null>(null);
  const [resultsFor, setResultsFor] = useState<{ filters: SelectedFilters; page: number } | null>(null);
  // The edge firewall (HTTP 403) rejected this search text: a search problem, not a connection problem.
  const [searchBlocked, setSearchBlocked] = useState<boolean>(false);

  // Active in-flight request controller to cancel stale requests and avoid race conditions
  const activeAbortControllerRef = useRef<AbortController | null>(null);

  const [filterOptions, setFilterOptions] = useState<JobFilterOptions>({
    countries: [],
    companies: [],
    skills: [],
    workplace_types: [],
  });
  // Skill filters from a shared URL are checked against the skills the API offers; "loading" holds the first request so
  // an unknown skill never flashes an empty result list.
  const [filterOptionsStatus, setFilterOptionsStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [ignoredSkill, setIgnoredSkill] = useState<string | null>(null);
  const ignoredSkillFilters = useRef<SelectedFilters | null>(null);
  // Hold the request until the skill is settled: still loading the offered skills, or known to need fixing/dropping (the
  // correction lands in the next render; requesting the unvalidated value in between would flash an empty list).
  const skillResolution = useMemo(
    () => (filters.skill && filterOptionsStatus === "ready" ? resolveSkillFilter(filters.skill, filterOptions.skills) : null),
    [filters.skill, filterOptionsStatus, filterOptions.skills]
  );
  const skillPending =
    Boolean(filters.skill) &&
    (filterOptionsStatus === "loading" || skillResolution?.status === "unknown" || skillResolution?.status === "canonicalized");



  const resultsHeaderRef = useRef<HTMLDivElement>(null);
  const isSplit = useSplitView();
  const showPane = isSplit && Boolean(selectedJobId);

  // Was the open job chosen by the app (desktop opens the first result) rather than by the reader? The marker is kept in
  // history.state by the app's selection handler, so reloads and Back/Forward keep the distinction.
  const [autoSelectedId, setAutoSelectedId] = useState<string | null>(null);
  useEffect(() => {
    setAutoSelectedId(selectedJobId && (window.history.state as { autoJob?: boolean } | null)?.autoJob ? selectedJobId : null);
  }, [selectedJobId]);
  const autoSelected = Boolean(selectedJobId) && autoSelectedId === selectedJobId;
  // Narrow screens have no split pane, so an auto-selected job must not turn into a modal the reader never opened
  // (e.g. resizing a desktop window, rotating a tablet): drop the automatic selection; explicit choices and links stay.
  useEffect(() => {
    if (!isSplit && autoSelected) onSelectJob(null, { replace: true });
  }, [isSplit, autoSelected, onSelectJob]);

  // The pane stays mounted briefly after the selection is cleared so it can animate out.
  const [paneJobId, setPaneJobId] = useState<string | null>(null);
  const [paneClosing, setPaneClosing] = useState<boolean>(false);
  const [paneSettled, setPaneSettled] = useState<boolean>(false);
  const paneRef = useRef<HTMLElement>(null);
  const rightColumnRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (showPane && selectedJobId) {
      setPaneJobId(selectedJobId);
      setPaneClosing(false);
      return;
    }
    if (!paneJobId) return;
    if (!isSplit || window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) {
      setPaneJobId(null);
      setPaneClosing(false);
      return;
    }
    setPaneClosing(true);
    const timer = window.setTimeout(() => {
      setPaneJobId(null);
      setPaneClosing(false);
    }, PANE_EXIT_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showPane, selectedJobId, isSplit]);

  // Content fades only apply once the pane has finished opening (never on the first open).
  const paneOpen = Boolean(paneJobId);
  useEffect(() => {
    if (!paneOpen) {
      setPaneSettled(false);
      return;
    }
    const timer = window.setTimeout(() => setPaneSettled(true), PANE_ENTER_MS + 40);
    return () => window.clearTimeout(timer);
  }, [paneOpen]);

  // Size the sticky pane to the visible viewport without moving the page: it starts below the
  // filters and grows to full height as the page scrolls.
  useEffect(() => {
    if (!paneJobId) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const column = rightColumnRef.current;
      const pane = paneRef.current;
      if (!column || !pane) return;
      const top = Math.max(PANE_STICKY_TOP, column.getBoundingClientRect().top);
      pane.style.setProperty("--pane-height", `${Math.max(320, window.innerHeight - top - 16)}px`);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [paneJobId]);

  const handleCloseModal = useCallback(() => {
    const closedJobId = selectedJobId;
    onSelectJob(null);
    if (!closedJobId) return;
    // Same path for the × button, Esc and the mobile overlay: put visible focus back on the card that was open.
    // The card may not be mounted for a moment (list refresh) or at all (deep link), so retry briefly and then give up quietly.
    let attempts = 0;
    const restore = () => {
      const cardEl = document.getElementById(`job-title-btn-${closedJobId}`);
      cardEl?.focus({ preventScroll: true });
      if (cardEl && document.activeElement === cardEl) return;
      attempts += 1;
      if (attempts < 12) requestAnimationFrame(restore);
    };
    setTimeout(restore, 0);
  }, [selectedJobId, onSelectJob]);

  // Load filter options on mount
  useEffect(() => {
    let isMounted = true;
    async function loadFilterOptions() {
      try {
        const options = await apiClient.getJobFilters();
        if (isMounted) {
          setFilterOptions(options);
          setFilterOptionsStatus("ready");
        }
      } catch (err) {
        console.warn("Failed to load job filter metadata:", err);
        if (isMounted) setFilterOptionsStatus("failed");
      }
    }
    void loadFilterOptions();
    return () => {
      isMounted = false;
    };
  }, []);

  const offset = Math.max(0, (page - 1) * PAGE_SIZE);

  // Fetch jobs based on current filters and pagination offset
  const fetchJobs = useCallback(async () => {
    // 1. Cancel previous in-flight jobs request before initiating a new one
    if (activeAbortControllerRef.current) {
      activeAbortControllerRef.current.abort();
    }
    const controller = new AbortController();
    activeAbortControllerRef.current = controller;

    setLoading(true);
    setError(null);
    setSearchBlocked(false);
    try {
      const response = await apiClient.getJobs(
        {
          limit: PAGE_SIZE,
          sort: filters.sort || "recommended",
          offset,
          search: filters.search.trim() || undefined,
          country: filters.country.length > 0 ? filters.country : undefined,
          location: filters.location && filters.location.length > 0 ? filters.location : undefined,
          company: filters.company || undefined,
          skill: filters.skill || undefined,
          workplace_type: filters.workplace_type.length > 0 ? filters.workplace_type : undefined,
          role_type: filters.role_type.length > 0 ? filters.role_type : undefined,
          experience_level: filters.experience_level && filters.experience_level.length > 0 ? filters.experience_level : undefined,
          min_compensation: filters.min_compensation || undefined,
          compensation_currency: filters.min_compensation
            ? filters.compensation_currency ||
              (filters.country.length === 1 && filters.country[0] === "Canada"
                ? "CAD"
                : filters.country.length === 1 && filters.country[0] === "United States"
                ? "USD"
                : "CAD")
            : undefined,
          sponsorship: filters.sponsorship && filters.sponsorship !== "all" ? filters.sponsorship : undefined,
          term: filters.term.length > 0 ? filters.term : undefined,
          freshness: filters.freshness !== "recent" ? filters.freshness : undefined,
        },

        controller.signal
      );
      // 2. Only the newest non-aborted request may update state
      if (!controller.signal.aborted) {
        setJobs(response.jobs);
        setTotal(response.total);
        setResultsFor({ filters, page });
        setLoading(false);

        // Clamp page if loaded total indicates requested page is out of bounds
        const availablePages = Math.max(1, Math.ceil(response.total / PAGE_SIZE));
        if (page > availablePages && response.total > 0) {
          onFiltersChange(filters, availablePages, false);
        }
      }
    } catch (err: unknown) {
      // 3. Aborted requests must NOT display an error message or modify state
      const isAbort =
        (err instanceof DOMException && err.name === "AbortError") ||
        (err as { name?: string })?.name === "AbortError" ||
        controller.signal.aborted;

      if (isAbort) {
        return;
      }
      // Only evidence that this exact request was rejected counts: a readable 403 (the client retries a cross-origin network
      // failure through the same-origin proxy, where the firewall's status is readable). Anything else is a connection
      // problem the user can retry; guessing "your search was blocked" from circumstantial signals would mislead.
      const rejectedSearch = Boolean(filters.search.trim()) && err instanceof ApiError && err.status === 403;
      if (rejectedSearch) {
        setJobs([]);
        setTotal(0);
        setSearchBlocked(true);
        setLoading(false);
        return;
      }
      console.error("Failed to fetch jobs:", err);
      // The requested query failed: never leave the previous query's cards and count on screen as if they answered it.
      setJobs([]);
      setTotal(0);
      setError(
        "Unable to load job postings. Please check your connection and try again."
      );
      setLoading(false);
    }
  }, [offset, page, filters, onFiltersChange]);

  // Normalise or drop a skill filter once the offered skills are known (replaces the URL entry; no history step).
  useEffect(() => {
    const resolution = skillResolution;
    if (!resolution) return;
    if (resolution.status === "canonicalized") {
      onFiltersChange({ ...filters, skill: resolution.skill }, page, false);
    } else if (resolution.status === "unknown") {
      const next = { ...filters, skill: "" };
      ignoredSkillFilters.current = next;
      setIgnoredSkill(resolution.skill);
      onFiltersChange(next, 1, false);
    }
  }, [skillResolution, filters, page, onFiltersChange]);

  // The notice belongs to the filters it explained; any later change to them clears it.
  useEffect(() => {
    if (ignoredSkill && ignoredSkillFilters.current !== filters) {
      setIgnoredSkill(null);
      ignoredSkillFilters.current = null;
    }
  }, [filters, ignoredSkill]);

  useEffect(() => {
    if (skillPending) return;
    void fetchJobs();
    return () => {
      // Clean up in-flight requests on unmount
      if (activeAbortControllerRef.current) {
        activeAbortControllerRef.current.abort();
      }
    };
  }, [fetchJobs, skillPending]);

  // A fresh desktop visit or new query opens its first result without adding a history step.
  // Wait for THIS query's response and for the user to finish entering a new search.
  useEffect(() => {
    if (active && isSplit && !selectedJobId && !resultsPending && !error && !searchBlocked
      && resultsFor?.filters === filters && resultsFor.page === page && jobs.length > 0) {
      onSelectJob(jobs[0].job_id, { replace: true, auto: true });
    }
  }, [active, isSplit, selectedJobId, resultsPending, error, searchBlocked, resultsFor, filters, page, jobs, onSelectJob]);

  // Desktop keyboard browsing: ↑/↓ or J/K move through jobs. The split pane stays open.
  // Never fires while typing or while focus is on another interactive control.
  useEffect(() => {
    if (!isSplit || !active || resultsPending) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (e.key === "Escape") return;
      // A focused card title is the list itself, so J/K and the arrows keep working from it.
      const onCardButton = Boolean(target?.closest?.(".job-title-btn"));
      if (
        !onCardButton &&
        target &&
        target !== document.body &&
        target.closest?.(
          'input, textarea, select, button, a, summary, [contenteditable=""], [contenteditable="true"], [role="combobox"], [role="listbox"], [role="option"], [role="dialog"], [role="menu"]'
        )
      ) {
        return;
      }
      const forward = e.key === "ArrowDown" || e.key === "j" || e.key === "J";
      const backward = e.key === "ArrowUp" || e.key === "k" || e.key === "K";
      if ((!forward && !backward) || jobs.length === 0) return;
      e.preventDefault();
      const index = jobs.findIndex((job) => job.job_id === selectedJobId);
      const nextIndex = index === -1 ? (forward ? 0 : jobs.length - 1) : Math.min(jobs.length - 1, Math.max(0, index + (forward ? 1 : -1)));
      if (nextIndex !== index) {
        const nextId = jobs[nextIndex].job_id;
        onSelectJob(nextId, { replace: true });
        // Keep keyboard focus on the list row that is now selected.
        if (onCardButton) document.getElementById(`job-title-btn-${nextId}`)?.focus({ preventScroll: true });
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [active, isSplit, resultsPending, jobs, selectedJobId, onSelectJob]);

  // Keep the selected card visible in the list while browsing.
  useEffect(() => {
    if (!isSplit || !selectedJobId) return;
    document.getElementById(`job-card-${selectedJobId}`)?.scrollIntoView?.({ block: "nearest" });
  }, [isSplit, selectedJobId]);

  const previousPageRef = useRef(page);

  const scrollToResultsTop = useCallback(() => {
    if (resultsHeaderRef.current) {
      const navbar = document.querySelector(".roleradar-navbar");
      const navHeight = navbar ? navbar.getBoundingClientRect().height : 60;
      const navOffset = navHeight + 16;
      const elementPosition = resultsHeaderRef.current.getBoundingClientRect().top;
      const offsetPosition = elementPosition + window.pageYOffset - navOffset;

      window.scrollTo({
        top: Math.max(0, offsetPosition),
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
      });
      resultsHeaderRef.current.focus();
    }
  }, []);

  useEffect(() => {
    if (previousPageRef.current === page) return;
    previousPageRef.current = page;
    requestAnimationFrame(() => {
      scrollToResultsTop();
    });
  }, [page, scrollToResultsTop]);

  const handleFilterChange = (newFilters: SelectedFilters, isDiscrete = true) => {
    onFiltersChange(newFilters, 1, isDiscrete);
  };

  const handleResetFilters = () => {
    const emptyFilters: SelectedFilters = {
      search: "",
      country: [],
      location: [],
      company: "",
      skill: "",
      workplace_type: [],
      role_type: [],
      experience_level: [],
      min_compensation: null,
      sponsorship: "all",
      term: [],
      freshness: "recent",
    };
    onFiltersChange(emptyFilters, 1, true);
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const startItem = total === 0 ? 0 : offset + 1;
  const endItem = Math.min(offset + PAGE_SIZE, total);

  const handlePrevPage = () => {
    const prevPage = Math.max(1, currentPage - 1);
    onFiltersChange(filters, prevPage, true);
  };

  const handleNextPage = () => {
    if (offset + PAGE_SIZE < total) {
      const nextPage = currentPage + 1;
      onFiltersChange(filters, nextPage, true);
    }
  };

  return (
    <div className={`job-explorer-container${isSplit ? " split-capable" : ""}${showPane ? " is-split" : ""}`}>
      {/* Filter Panel (Search + Compact Dropdown Toolbar + Active Chips) */}
      <JobFilters
        filterOptions={filterOptions}
        selectedFilters={filters}
        onFilterChange={handleFilterChange}
        onReset={handleResetFilters}
        onSearchInputChange={setDraftSearch}
      />

      {/* Two-Column Explorer Layout (Left: Jobs Stream, Right: Visual Sidebar) */}
      <div className={`job-explorer-layout${isSplit ? " split-capable" : ""}${showPane ? " is-split" : ""}`}>
        {/* Left Column (~72% desktop) */}
        <section className="job-explorer-main" aria-label="Job listings stream">
          {showPane && (
            <a
              href="#job-detail-pane"
              className="skip-link"
              onClick={(event) => {
                event.preventDefault();
                paneRef.current?.focus();
              }}
            >
              Skip to job details
            </a>
          )}
          <h2 className="visually-hidden">Job listings</h2>
          {/* Results Header Bar */}
          <div className="results-header-bar" ref={resultsHeaderRef} tabIndex={-1}>
            <div className="results-count-group">
              <span className="results-count-number">
                {(error && jobs.length === 0) || searchBlocked
                  ? "—"
                  : resultsPending
                  ? "..."
                  : total.toLocaleString()}
              </span>
              <span className="results-count-label">
                {total === 1 ? "job" : "jobs"}
              </span>
            </div>

            <div className="results-sort-group" title="Recommended lists Canadian roles first, then newest">
              <NativeSelect
                label="Sort jobs"
                value={filters.sort || "recommended"}
                onChange={(value) => onFiltersChange({ ...filters, sort: value as SelectedFilters["sort"] }, 1, true)}
              >
                {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </NativeSelect>
            </div>
          </div>

          {ignoredSkill && (
            <p className="filter-notice" role="status" data-testid="ignored-skill-notice">
              “{ignoredSkill}” isn’t a skill we can filter by, so it was ignored.
              <button type="button" className="filter-notice-dismiss" aria-label="Dismiss" onClick={() => setIgnoredSkill(null)}>✕</button>
            </p>
          )}

          {/* Accessible Live Result Summary */}
          <div className="visually-hidden" aria-live="polite" aria-atomic="true">
            {resultsPending
              ? "Updating jobs..."
              : searchBlocked
              ? "That search could not be processed"
              : error
              ? "Unable to load jobs"
              : total === 0
              ? "No jobs found"
              : `${total} ${total === 1 ? "job" : "jobs"} found`}
          </div>

          {/* Job List Container */}
          <div className="job-list-container" aria-busy={resultsPending} style={{ position: 'relative' }}>
            {resultsPending && (
              <div className="state-container loading-state" style={{ minHeight: '300px' }}>
                <div className="spinner" />
                <p>Loading jobs...</p>
                <SlowLoadHint />
              </div>
            )}

            {!resultsPending && error && jobs.length > 0 && (
              <div className="state-container error-state" role="alert" style={{ marginBottom: '16px' }}>
                <p className="error-message">{error}</p>
                <button onClick={fetchJobs} className="retry-button">
                  Retry
                </button>
              </div>
            )}

            {!resultsPending && error && jobs.length === 0 && (
              <div className="state-container error-state" role="alert">
                <h3 className="error-title">Unable to load jobs</h3>
                <p className="error-message">{error}</p>
                <button onClick={fetchJobs} className="retry-button">
                  Retry
                </button>
              </div>
            )}

            {searchBlocked && !resultsPending && (
              <div className="state-container error-state" role="alert" data-testid="search-blocked">
                <p className="error-message">That search could not be processed. Try a different search term.</p>
                <button
                  type="button"
                  className="retry-button"
                  onClick={() => onFiltersChange({ ...filters, search: "" }, 1, true)}
                >
                  Clear search
                </button>
              </div>
            )}

            {!error && !searchBlocked && !resultsPending && jobs.length === 0 && (
              <div className="state-container empty-state" role="status">
                <h3 className="empty-title">No jobs match your current filters</h3>
                <p className="empty-message">
                  Try adjusting your search terms, removing filters, or resetting to browse all openings.
                </p>
                <button onClick={handleResetFilters} className="retry-button">
                  Reset filters
                </button>
              </div>
            )}

            {!resultsPending && jobs.length > 0 && (
              <>
                <div className="jobs-grid">
                  {jobs.map((job) => (
                    <JobCard
                      key={job.job_id}
                      job={job}
                      onClick={(id) => {
                        // Clicking the job that is already open does nothing (it never toggles the pane closed)
                        if (id !== selectedJobId) onSelectJob(id);
                        // Clicking the job the app auto-opened makes it the reader's own choice.
                        else if (autoSelected) {
                          setAutoSelectedId(null);
                          onSelectJob(id, { replace: true });
                        }
                      }}
                      selected={showPane && job.job_id === selectedJobId}
                      preferredCountries={filters.country}
                    />
                  ))}
                </div>

                {/* Pagination Controls - only render when multiple pages exist */}
                {totalPages > 1 && (
                  <div className="pagination-bar">
                    <span className="pagination-info">
                      Showing {startItem.toLocaleString()}–{endItem.toLocaleString()} of {total.toLocaleString()} jobs
                    </span>
                    <div className="pagination-actions">
                      <button
                        type="button"
                        onClick={handlePrevPage}
                        disabled={currentPage <= 1 || loading}
                        className="pagination-btn"
                        aria-label="Previous page"
                      >
                        ← Previous
                      </button>
                      <span className="pagination-page-indicator">
                        Page {currentPage} of {totalPages}
                      </span>
                      <button
                        type="button"
                        onClick={handleNextPage}
                        disabled={offset + PAGE_SIZE >= total || loading}
                        className="pagination-btn"
                        aria-label="Next page"
                      >
                        Next →
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* Right column: the market sidebar and (desktop) the selected job's detail pane share one
            stable column, so opening or closing a job only animates its width. */}
        <div className="job-explorer-right" ref={rightColumnRef}>
        {paneJobId && (
          <aside
            ref={paneRef}
            id="job-detail-pane"
            tabIndex={-1}
            className={`job-detail-pane ${paneClosing ? "pane-exit" : "pane-enter"}${paneSettled ? " pane-settled" : ""}`}
            aria-label="Selected job details"
          >
            <JobDetailContent
              jobId={paneJobId}
              variant="pane"
              preview={jobs.find((job) => job.job_id === paneJobId) ?? null}
              onClose={handleCloseModal}
            />
          </aside>
        )}

        <aside className="job-explorer-sidebar" aria-label="Market overview and sources" aria-hidden={showPane ? true : undefined}>
          {/* Card A: Market Overview */}
          <div className="sidebar-card insights-card">
            <div className="sidebar-card-header">
              <div className="sidebar-card-title-group">
                <svg
                  className="sidebar-title-icon"
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M3 3v18h18" />
                  <path d="M18 17V9" />
                  <path d="M13 17V5" />
                  <path d="M8 17v-3" />
                </svg>
                <h2 className="sidebar-card-title">Market overview</h2>
              </div>
              <div className="sidebar-card-actions">
                {onViewStats && (
                  <button
                    type="button"
                    onClick={onViewStats}
                    className="sidebar-arrow-btn"
                    title="View full market charts"
                    aria-label="View full market charts"
                  >
                    →
                  </button>
                )}
              </div>
            </div>

            {countryLabel && <p className="sidebar-scope">{countryLabel === "All countries" ? countryLabel : `Country: ${countryLabel}`}</p>}

            <div className="insights-stats-grid">
              <div className="insight-stat-box box-postings">
                <div className="insight-number text-blue">
                  {overview ? overview.total_postings.toLocaleString() : "—"}
                </div>
                <div className="insight-label">Total Postings</div>
              </div>

              <div className="insight-stat-box box-companies">
                <div className="insight-number text-indigo">
                  {overview ? overview.total_companies.toLocaleString() : "—"}
                </div>
                <div className="insight-label">Active Companies</div>
              </div>

              <div className="insight-stat-box box-locations">
                <div className="insight-number text-emerald">
                  {overview ? overview.total_locations.toLocaleString() : "—"}
                </div>
                <div className="insight-label">Locations</div>
              </div>

              <div className="insight-stat-box box-skills">
                <div className="insight-number text-amber">
                  {overview ? overview.total_skills.toLocaleString() : "—"}
                </div>
                <div className="insight-label">Unique Skills</div>
              </div>
            </div>
          </div>

          {/* Card B: Official Company Sources */}
          <div className="sidebar-card sources-card">
            <div className="sidebar-card-header">
              <div className="sidebar-card-title-group">
                <svg
                  className="sidebar-title-icon shield-icon"
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  <path d="m9 12 2 2 4-4" />
                </svg>
                <h2 className="sidebar-card-title">Official company sources</h2>
              </div>
            </div>
            <p className="sources-card-body">
              Jobs are collected from company career pages and supported public job sources.
            </p>
            <SourceStatusNote />
          </div>
        </aside>
        </div>
      </div>

      {/* Single-column job detail overlay (narrow screens only) */}
      <JobDetailModal
        jobId={isSplit || autoSelected ? null : selectedJobId}
        onClose={handleCloseModal}
      />
    </div>
  );
};
