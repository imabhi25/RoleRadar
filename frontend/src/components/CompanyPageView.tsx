import React, { useEffect, useState, useMemo } from "react";
import { apiClient, type CompanyInfo, type JobSummary } from "../api/client";
import { CompanyLogo } from "./CompanyLogo";
import { StatePanel } from "./StatePanel";
import { CompanyLinks, CompanyDetails } from "./CompanyInfo";
import { useCompanyBackground } from "../hooks/useCompanyBackground";
import { getCompanyProfile } from "../utils/companyProfiles";
import { getJobCardCompensation } from "../utils/compensation";
import { formatAbsoluteDate } from "../utils/jobFacts";

interface CompanyPageViewProps {
  initialCompany?: string | null;
  onBackToJobs: () => void;
  onSelectJob: (jobId: string) => void;
  onCompanyChange?: (company: string | null) => void;
}

export const CompanyPageView: React.FC<CompanyPageViewProps> = ({
  initialCompany,
  onBackToJobs,
  onSelectJob,
  onCompanyChange,
}) => {
  const [selectedCompany, setSelectedCompany] = useState<string | null>(initialCompany || null);
  const [companies, setCompanies] = useState<CompanyInfo[]>([]);
  const [directoryLoading, setDirectoryLoading] = useState<boolean>(true);
  // True only once the directory actually loaded: a failed request must never be reported as "company not found".
  const [directoryLoaded, setDirectoryLoaded] = useState<boolean>(false);
  const [searchFilter, setSearchFilter] = useState<string>("");

  // Jobs state for selected company
  const [companyJobs, setCompanyJobs] = useState<JobSummary[]>([]);
  const [jobsLoading, setJobsLoading] = useState<boolean>(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState<number>(0);

  // Sync with prop when URL changes
  useEffect(() => {
    setSelectedCompany(initialCompany || null);
  }, [initialCompany]);

  // Load companies directory
  useEffect(() => {
    const controller = new AbortController();
    setDirectoryLoading(true);
    apiClient
      .getCompanies(controller.signal)
      .then((data) => {
        setCompanies(Array.isArray(data) ? data : []);
        setDirectoryLoaded(true);
        setDirectoryLoading(false);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          console.warn("Failed to load companies:", err);
          setDirectoryLoading(false);
        }
      });
    return () => controller.abort();
  }, []);

  // Fetch jobs when a company is selected or retry is clicked
  useEffect(() => {
    if (!selectedCompany) {
      setCompanyJobs([]);
      return;
    }
    const controller = new AbortController();
    setJobsLoading(true);
    setJobsError(null);

    apiClient
      .getJobs({ company: selectedCompany, limit: 50 }, controller.signal)
      .then((res) => {
        setCompanyJobs(res.jobs || []);
        setJobsLoading(false);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          console.error("Failed to load jobs for company:", err);
          setJobsError("Unable to load jobs for this company. Please try again.");
          setJobsLoading(false);
        }
      });

    return () => controller.abort();
  }, [selectedCompany, retryNonce]);

  const selectCompany = (companyName: string | null) => {
    setSelectedCompany(companyName);
    onCompanyChange?.(companyName);
  };

  const filteredCompanies = useMemo(() => {
    const q = searchFilter.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter((c) => c.name.toLowerCase().includes(q));
  }, [companies, searchFilter]);

  const currentCompanyInfo = useMemo(() => {
    if (!selectedCompany) return null;
    return companies.find((c) => c.name.toLowerCase() === selectedCompany.toLowerCase()) || null;
  }, [companies, selectedCompany]);

  // The URL may spell the name in any case; show the directory's spelling ("GitLab", not "gitlab").
  const baseProfile = useMemo(() => {
    if (!selectedCompany) return null;
    return getCompanyProfile(currentCompanyInfo?.name ?? selectedCompany, currentCompanyInfo?.website_url);
  }, [selectedCompany, currentCompanyInfo]);
  const companyNotFound = Boolean(selectedCompany) && directoryLoaded && !currentCompanyInfo;
  const profile = useCompanyBackground(baseProfile);

  return (
    <div className="company-page-view" data-testid="company-page-view">
      <div className="company-page-nav-bar">
        {selectedCompany ? (
          <div className="company-page-breadcrumbs">
            <button
              type="button"
              className="company-nav-back-btn secondary-button"
              onClick={onBackToJobs}
            >
              ← Back to jobs
            </button>
            <button
              type="button"
              className="company-nav-all-btn secondary-button"
              onClick={() => selectCompany(null)}
            >
              All companies
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="company-nav-back-btn secondary-button"
            onClick={onBackToJobs}
          >
            ← Back to jobs
          </button>
        )}
      </div>

      {companyNotFound ? (
        <StatePanel
          variant="unavailable"
          title="Company not found"
          testId="company-not-found"
          actions={[{ label: "Browse all companies", onClick: () => selectCompany(null), kind: "secondary" }]}
        >
          We don’t list a company with that name. Check the spelling or browse the companies that are hiring.
        </StatePanel>
      ) : selectedCompany && profile ? (
        <div className="company-profile-container">
          {/* Company Profile Header Card */}
          <header className="company-profile-card">
            <div className="company-profile-header-main">
              <CompanyLogo company={profile.name} logoUrl={currentCompanyInfo?.logo_url} websiteUrl={profile.website} size="lg" />
              <div className="company-profile-header-text">
                <h1 className="company-profile-name">{profile.name}</h1>
                <CompanyLinks profile={profile} className="company-profile-links" />
              </div>
            </div>

            {/* Sourced facts & description */}
            <div className="company-profile-body">
              <CompanyDetails profile={profile} />
            </div>
          </header>

          {/* Active Postings Section */}
          <section className="company-jobs-section" aria-label={`Open jobs at ${profile.name}`}>
            <div className="company-jobs-header">
              <h2 className="company-jobs-title">
                Active Roles at {profile.name}
              </h2>
              <span className="company-jobs-count-badge">
                {companyJobs.length} active {companyJobs.length === 1 ? "role" : "roles"}
              </span>
            </div>

            {jobsLoading && (
              <div className="company-jobs-loading">
                <div className="spinner" />
                <p>Loading open roles…</p>
              </div>
            )}

            {jobsError && (
              <div className="company-jobs-error" role="alert">
                <p>{jobsError}</p>
                <button
                  type="button"
                  className="retry-button"
                  onClick={() => setRetryNonce((n) => n + 1)}
                >
                  Retry
                </button>
              </div>
            )}

            {!jobsLoading && !jobsError && companyJobs.length === 0 && (
              <div className="company-jobs-empty">
                <p>No active software engineering roles currently indexed for {profile.name}.</p>
                {profile.website && (
                  <a
                    href={profile.website}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="company-careers-external-link"
                  >
                    Check {profile.name} official careers page ↗
                  </a>
                )}
              </div>
            )}

            {!jobsLoading && companyJobs.length > 0 && (
              <div className="company-jobs-list">
                {companyJobs.map((job) => {
                  const comp = getJobCardCompensation(job.compensation);
                  const exactDate = formatAbsoluteDate(job.posted_at);
                  const applyUrl = job.company_apply_url || job.source_url;

                  return (
                    <article key={job.job_id} className="company-job-card">
                      <div className="company-job-main">
                        <h3 className="company-job-title">
                          <button
                            type="button"
                            className="company-job-title-btn"
                            onClick={() => onSelectJob(job.job_id)}
                          >
                            {job.title}
                          </button>
                        </h3>

                        <div className="company-job-meta">
                          {job.location && (
                            <span className="company-job-meta-item meta-location">
                              {job.location}
                            </span>
                          )}
                          {job.workplace_type && (
                            <span className="company-job-meta-item meta-workplace">
                              {job.workplace_type}
                            </span>
                          )}
                          {comp && (
                            <span className="company-job-meta-item meta-compensation">
                              {comp}
                            </span>
                          )}
                          {job.posted_at && (
                            <time
                              dateTime={job.posted_at}
                              title={exactDate || undefined}
                              className="company-job-meta-item meta-date"
                            >
                              {exactDate || "Recently posted"}
                            </time>
                          )}
                        </div>
                      </div>

                      <div className="company-job-actions">
                        <button
                          type="button"
                          className="secondary-button company-job-view-btn"
                          onClick={() => onSelectJob(job.job_id)}
                        >
                          View Details
                        </button>
                        {applyUrl ? (
                          <a
                            href={applyUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="job-detail-apply-link company-job-apply-link"
                            aria-label={`Apply for ${job.title} at ${job.company} (opens in a new tab)`}
                          >
                            Apply ↗
                          </a>
                        ) : null}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      ) : (
        /* Company Directory View */
        <div className="companies-directory-container">
          <header className="companies-directory-header">
            <h1 className="companies-directory-title">Companies Hiring on RoleRadar</h1>
            <p className="companies-directory-subtitle">
              Browse verified tech employers offering software engineering roles across Canada and the US.
            </p>

            <div className="companies-search-wrap">
              <input
                type="search"
                className="companies-search-input"
                placeholder="Search companies by name…"
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                aria-label="Filter companies"
              />
              <span className="companies-count-indicator">
                {filteredCompanies.length} {filteredCompanies.length === 1 ? "company" : "companies"}
              </span>
            </div>
          </header>

          {directoryLoading && (
            <div className="companies-directory-loading">
              <div className="spinner" />
              <p>Loading company catalog…</p>
            </div>
          )}

          {!directoryLoading && (
            <div className="companies-directory-grid">
              {filteredCompanies.map((c) => (
                <article key={c.name} className="company-directory-card">
                  <div className="company-directory-card-top">
                    <CompanyLogo company={c.name} logoUrl={c.logo_url} websiteUrl={c.website_url} size="md" />
                    <div className="company-directory-info">
                      <h2 className="company-directory-name">{c.name}</h2>
                      {c.website_url && (
                        <a
                          href={c.website_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="company-directory-website"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {new URL(c.website_url).hostname.replace(/^www\./, "")} ↗
                        </a>
                      )}
                    </div>
                  </div>

                  <div className="company-directory-card-bottom">
                    <span className="company-directory-jobs-badge">
                      {c.active_jobs_count} active {c.active_jobs_count === 1 ? "job" : "jobs"}
                    </span>
                    <button
                      type="button"
                      className="secondary-button company-directory-view-btn"
                      onClick={() => selectCompany(c.name)}
                    >
                      View Profile &amp; Jobs →
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default CompanyPageView;
