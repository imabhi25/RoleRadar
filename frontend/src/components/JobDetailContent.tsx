import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiClient, ApiError, type JobDetail, type JobSummary } from "../api/client";
import { useCompanyBackground } from "../hooks/useCompanyBackground";
import { formatJobTitle } from "../utils/formatters";
import { formatExtraLocations, formatPostalAddress, summarizeLocations } from "../utils/locations";
import { renderDescription } from "../utils/descriptionPipeline";
import { analyzeLanguage, type DescriptionView } from "../utils/descriptionLanguage";
import { summarizePosting } from "../utils/postingSummary";
import { presentHeadings, structureDescription } from "../utils/descriptionSections";
import { parseAndSanitizeJobDescription } from "../utils/sanitizeDescription";
import { buildJobFacts } from "../utils/jobFacts";
import { postingHighlights } from "../utils/postingHighlights";
import { CompanyLogo } from "./CompanyLogo";
import { StatePanel } from "./StatePanel";
import { PostingBody } from "./PostingBody";
import { ExternalArrow } from "./ExternalArrow";
import { CompanyDetails, CompanyLinks } from "./CompanyInfo";
import { getCompanyProfile } from "../utils/companyProfiles";
import { resolveApplyRoutes, type ResolvedApplyRoutes } from "../utils/applyUrls";

export interface JobDetailContentProps {
  jobId: string;
  /** "pane" is the desktop split-view column; "modal" is the mobile overlay body. */
  variant: "pane" | "modal";
  onClose: () => void;
  /** List summary of this job: lets the header render instantly (and stay put) while the detail loads. */
  preview?: JobSummary | null;
  closeButtonRef?: React.Ref<HTMLButtonElement>;
}

const EMPTY_ROUTES: ResolvedApplyRoutes = {
  primaryUrl: null,
  primaryLabel: "Apply ↗",
  hasOfficialCompanyRoute: false,
  secondaryRoutes: [],
};

/**
 * Job detail content shared by the desktop split-view pane and the mobile overlay:
 * company header and Apply link, readable facts, role description, and company background.
 */
export const JobDetailContent: React.FC<JobDetailContentProps> = ({
  jobId,
  variant,
  onClose,
  preview,
  closeButtonRef,
}) => {
  // Everything that describes "the job on screen" is tagged with the id it was fetched for. A render for a newly
  // selected id therefore can never pick up the previous job's facts, description or Apply URL, even for one frame,
  // and a late response for an earlier selection is ignored.
  type FetchState =
    | { id: string; status: "loading" }
    | { id: string; status: "ready"; job: JobDetail }
    | { id: string; status: "error" }
    | { id: string; status: "unavailable" };
  const [fetched, setFetched] = useState<FetchState>({ id: jobId, status: "loading" });
  const state: FetchState = fetched.id === jobId ? fetched : { id: jobId, status: "loading" };
  const job = state.status === "ready" ? state.job : null;
  const loading = state.status === "loading";
  const error = state.status === "error" ? "Unable to load job details. Please try again." : null;
  // The job id does not exist (removed, expired or a bad link): a final answer, so no Retry is offered.
  const unavailable = state.status === "unavailable";
  // Per-job UI choices carry the id they were made for, so they reset on their own when another job is selected.
  const [locationsOpenFor, setLocationsOpenFor] = useState<string | null>(null);
  const [viewChoice, setViewChoice] = useState<{ id: string; view: DescriptionView } | null>(null);
  const [fullPostingFor, setFullPostingFor] = useState<string | null>(null);
  const locationsOpen = locationsOpenFor === jobId;
  const chosenView = viewChoice?.id === jobId ? viewChoice.view : undefined;
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const latestRequest = useRef(0);

  const fetchDetail = useCallback(async (id: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const request = (latestRequest.current += 1);
    const stale = () => controller.signal.aborted || request !== latestRequest.current;
    setFetched({ id, status: "loading" });
    try {
      const data = await apiClient.getJob(id, controller.signal);
      if (!stale()) setFetched({ id, status: "ready", job: data });
    } catch (err) {
      if (stale()) return;
      if (err instanceof ApiError && (err.status === 404 || err.status === 410)) {
        setFetched({ id, status: "unavailable" });
        return;
      }
      console.error("Failed to load job details:", err);
      setFetched({ id, status: "error" });
    }
  }, []);

  useEffect(() => {
    void fetchDetail(jobId);
    // The id-tagged state above already hides the previous job's choices; clearing them also stops them coming back
    // if the reader returns to that job later.
    setLocationsOpenFor(null);
    setViewChoice(null);
    setFullPostingFor(null);
    scrollRef.current?.scrollTo?.({ top: 0 });
    return () => abortRef.current?.abort();
  }, [jobId, fetchDetail]);

  const description = useMemo(
    () => renderDescription(job?.description, job?.company ?? "", job?.title ?? "", chosenView),
    [job?.description, job?.company, job?.title, chosenView]
  );

  // Header shows the loaded job, or the list summary while the detail request is in flight.
  const head = job ?? (preview && preview.job_id === jobId ? preview : null);

  const baseCompanyProfile = useMemo(
    () => (head?.company ? getCompanyProfile(head.company, job?.company_website_url) : null),
    [head?.company, job?.company_website_url]
  );
  const companyProfile = useCompanyBackground(baseCompanyProfile);
  const applyRoutes = useMemo(() => (job ? resolveApplyRoutes(job) : EMPTY_ROUTES), [job]);

  const { primary: primaryLocation, all: allLocations } = useMemo(
    () => (head ? summarizeLocations(head) : { primary: "", all: [] as string[] }),
    [head]
  );
  const facts = useMemo(
    () => {
      if (!head) return [];
      const metadata = buildJobFacts(head, { primaryLocation, ...description.meta });
      const highlights = postingHighlights(head.title, description.mainHtml, head.experience_level);
      return [
        ...metadata.filter((fact) => fact.key === "compensation"),
        ...metadata.filter((fact) => fact.key === "role"),
        ...metadata.filter((fact) => fact.key === "posted"),
        ...highlights.filter((fact) => fact.key === "experience"),
        ...highlights.filter((fact) => fact.key !== "experience"),
        ...metadata.filter((fact) => !["compensation", "role", "posted"].includes(fact.key)),
      ];
    },
    [head, primaryLocation, description.meta, description.mainHtml]
  );
  const address = description.meta.address;
  const postalAddress = address ? formatPostalAddress(address, primaryLocation) : null;
  const additionalLocations = allLocations.slice(1);
  const extraLocations = additionalLocations.length;
  const locationListId = `job-locations-${jobId.replace(/[^a-zA-Z0-9_-]/g, "-")}`;

  const originalHtml = useMemo(
    () => job?.description ? parseAndSanitizeJobDescription(job.description, job.company).html : "",
    [job?.description, job?.company]
  );
  const summaryHtml = useMemo(() => summarizePosting(description.teamHtml + description.mainHtml, description.language), [description.teamHtml, description.mainHtml, description.language]);
  const fullHtml = useMemo(() => presentHeadings(structureDescription(analyzeLanguage(originalHtml).html[description.view] || originalHtml, job?.company)), [originalHtml, description.view, job?.company]);
  // An indivisible source paragraph can exceed the summary budget. Show the full
  // posting in that case instead of an empty excerpt or a misleading truncation.
  const summaryUnavailable = !summaryHtml && Boolean(originalHtml);
  const showFullPosting = fullPostingFor === jobId || summaryUnavailable;
  // Compact business labels are curated from the existing official company sources.
  const tagline = companyProfile?.tagline;

  return (
    <div className={`job-detail ${variant === "pane" ? "job-detail-inpane" : "job-detail-modal"}`} data-testid="job-detail">
      <header className="job-detail-header">
        <div className={`jd-grid${job && applyRoutes.secondaryRoutes.length > 0 ? " has-secondary-apply" : ""}`}>
          {head ? (
            <div className="jd-company">
              <CompanyLogo company={head.company} logoUrl={head.company_logo_url} websiteUrl={job?.company_website_url} size="detail" />
              <div className="jd-company-copy" key={`company-${jobId}`}>
                <div className="jd-company-name-row">
                  <span className="jd-company-name jd-swap">{head.company}</span>
                  {companyProfile && <CompanyLinks profile={companyProfile} />}
                </div>
                {tagline && <p className="jd-company-tagline">{tagline}</p>}
              </div>
            </div>
          ) : (
            <span className="jd-company-pending" />
          )}

          <div className="jd-apply">
            {job ? (
              applyRoutes.primaryUrl ? (
                <a
                  href={applyRoutes.primaryUrl}
                  aria-label={`Apply for ${job.title} at ${job.company} (opens in a new tab)`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="job-detail-apply-link"
                >
                  Apply <ExternalArrow />
                </a>
              ) : (
                <span className="job-detail-apply-link job-detail-apply-unavailable" aria-disabled="true" title="Application link unavailable">
                  Application link unavailable
                </span>
              )
            ) : head ? (
              // Same place, same size, but not a link: the official destination of THIS job is not known yet, and the
              // previous job's URL must never be reachable from here.
              <span
                className="job-detail-apply-link is-pending"
                role="link"
                aria-disabled="true"
                aria-label={`Apply for ${head.title} at ${head.company} (loading the application link)`}
                title="Loading the application link…"
              >
                Apply <ExternalArrow />
              </span>
            ) : null}
          </div>

          {variant === "modal" && <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            className="modal-close-btn job-detail-close-btn jd-close"
            aria-label="Close job details modal"
          >
            ✕
          </button>}

          <h2 id="modal-job-title" className="job-detail-title jd-title jd-swap" key={`title-${jobId}`}>
            {head ? formatJobTitle(head.title) : unavailable ? "Job unavailable" : error ? "Job details unavailable" : "Loading job details..."}
          </h2>

          {head && (primaryLocation || postalAddress) && (
            <div className="job-detail-location jd-location jd-swap" key={`location-${jobId}`}>
              {primaryLocation && <div className="job-detail-location-row">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                  <circle cx="12" cy="10" r="3" />
                </svg>
                <span className="job-detail-location-primary">{primaryLocation}</span>
                {extraLocations > 0 && (
                  <button
                    type="button"
                    className="job-detail-location-toggle"
                    aria-expanded={locationsOpen}
                    aria-controls={locationListId}
                    onClick={() => setLocationsOpenFor(locationsOpen ? null : jobId)}
                  >
                    {locationsOpen ? "Hide locations" : formatExtraLocations(extraLocations)}
                  </button>
                )}
              </div>}
              {locationsOpen && extraLocations > 0 && (
                <ul id={locationListId} className="job-detail-location-list" aria-label="Additional locations">
                  {additionalLocations.map((label) => (
                    <li key={label}>{label}</li>
                  ))}
                </ul>
              )}
              {postalAddress && (
                <div className="job-detail-address" role="group" aria-label="Employer address">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 7h1m4 0h1M9 11h1m4 0h1M10 21v-6h4v6" />
                  </svg>
                  <div className="job-detail-address-copy">
                    <span className="job-detail-address-label">Employer address</span>
                    <a className="job-detail-address-link" href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([postalAddress.full, primaryLocation].filter(Boolean).join(", "))}`} target="_blank" rel="noopener noreferrer" title={`View ${postalAddress.full} on Google Maps (opens in a new tab)`}>
                      <span className="job-detail-address-value">{postalAddress.label}</span>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" /></svg>
                    </a>
                    {head.workplace_type === "remote" && <p className="job-detail-address-note">Employer-listed address; this role is remote.</p>}
                  </div>
                </div>
              )}
            </div>
          )}

          {job && applyRoutes.secondaryRoutes.length > 0 && (
            <div className="job-detail-secondary-apply jd-more">
              <span className="modal-secondary-apply-label">Other ways to apply</span>
              {applyRoutes.secondaryRoutes.map((route) => (
                <a
                  key={route.name}
                  href={route.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="modal-secondary-apply-link"
                  title={`Apply via ${route.name}`}
                >
                  {route.label}
                </a>
              ))}
            </div>
          )}
        </div>
      </header>

      <div className="job-detail-scroll" ref={scrollRef} tabIndex={0} role="region" aria-label="Job description" aria-busy={loading || undefined}>
        {facts.length > 0 && (
          <dl className="job-facts jd-facts jd-swap" aria-label="Job facts" key={`facts-${jobId}`}>
            {facts.map((fact) => (
              <div key={fact.key} className={`job-fact job-fact-${fact.key}`}>
                <dt><FactIcon kind={fact.key} />{fact.label}</dt>{" "}
                <dd>{fact.value}</dd>{" "}
              </div>
            ))}
          </dl>
        )}

        {loading && (
          <div className="modal-loading-state">
            <div className="spinner" />
            <p>Fetching full job posting details...</p>
          </div>
        )}

        {unavailable && (
          <StatePanel
            variant="unavailable"
            title="This job is no longer available"
            testId="job-unavailable"
            actions={[{ label: "Back to jobs", onClick: onClose, kind: "secondary" }]}
          >
            {preview?.title ? `“${preview.title}” has` : "This posting has"} been removed or has expired, or the link is out of date.
          </StatePanel>
        )}

        {error && (
          <StatePanel
            variant="error"
            actions={[
              { label: "Retry", onClick: () => void fetchDetail(jobId) },
              { label: "Close", onClick: onClose, kind: "secondary" },
            ]}
          >
            {error}
          </StatePanel>
        )}

        {job && (
          <div className="job-detail-body jd-swap" key={job.job_id}>

            {description.views.length > 1 && (
              <div className="job-language-toggle" role="group" aria-label="Description language">
                {description.views.map((view) => (
                  <button
                    key={view}
                    type="button"
                    className="job-language-option"
                    aria-pressed={description.view === view}
                    lang={view === "fr" ? "fr" : undefined}
                    onClick={() => setViewChoice({ id: jobId, view })}
                  >
                    {view === "en" ? "English" : view === "fr" ? "Français" : "Original (both)"}
                  </button>
                ))}
              </div>
            )}
            {description.views.length === 0 && description.language === "fr" && (
              <p className="job-language-note">Written in French by the employer; shown as published.</p>
            )}


            <section className="job-part job-part-job" aria-labelledby="about-job-heading">
              <div className="job-part-title-row">
                <h3 id="about-job-heading" className="job-part-heading">About the job</h3>
                <div className={`job-language-toggle job-posting-toggle${showFullPosting ? " is-full" : ""}`} role="group" aria-label="Posting view">
                  <button type="button" className="job-language-option" aria-pressed={!showFullPosting} disabled={summaryUnavailable} title={summaryUnavailable ? "This posting cannot be shortened without losing important details." : undefined} onClick={() => setFullPostingFor(null)}>Summary</button>
                  <button type="button" className="job-language-option" aria-pressed={showFullPosting} onClick={() => setFullPostingFor(jobId)}>Full Posting</button>
                </div>
              </div>
              <PostingBody key={jobId} html={showFullPosting ? fullHtml : summaryHtml} summary={!showFullPosting} language={description.language} hasOriginal={Boolean(originalHtml)} />
            </section>

            {job.skills && job.skills.length > 0 && (
              <section className="modal-skills-section job-detail-skills" aria-label="Skills and technologies">
                <h3 className="modal-skills-heading">Skills & Technologies</h3>
                <div className="modal-skills-chips">
                  {job.skills.map((skill) => (
                    <span key={skill} className="skill-chip">{skill}</span>
                  ))}
                </div>
              </section>
            )}

            {!showFullPosting && description.meta.compensationNotesHtml && (
              <details className="job-policies job-compensation-notes">
                <summary>Compensation details</summary>
                <div className="job-description-prose job-policies-body"
                  dangerouslySetInnerHTML={{ __html: description.meta.compensationNotesHtml }} />
              </details>
            )}
            {!showFullPosting && description.policiesHtml && (
              <details className="job-policies">
                <summary>Company policies &amp; disclosures</summary>
                <div
                  lang={description.language ?? undefined}
                  className="job-description-prose job-policies-body"
                  dangerouslySetInnerHTML={{ __html: description.policiesHtml }}
                />
              </details>
            )}
            {companyProfile && (
              <section className="job-part job-part-company" aria-labelledby="about-company-heading">
                <h3 id="about-company-heading" className="job-part-heading">About the company</h3>
                <div className="job-company-footer-identity">
                  <CompanyLogo company={job.company} logoUrl={job.company_logo_url} websiteUrl={job.company_website_url} size="detail" />
                  <strong>{job.company}</strong>
                </div>
                {!companyProfile.description && description.companyHtml && (
                  <div
                    lang={description.language ?? undefined}
                    className="modal-description job-description-prose"
                    dangerouslySetInnerHTML={{ __html: description.companyHtml }}
                  />
                )}
                <CompanyDetails profile={companyProfile} />
                {head?.company && (
                  <div className="job-company-page-nav">
                    <a
                      href={`/company?company=${encodeURIComponent(head.company)}`}
                      className="job-company-page-link"
                    >
                      View company profile &amp; all open roles →
                    </a>
                  </div>
                )}
              </section>
            )}

          </div>
        )}
      </div>
    </div>
  );
};

/** Decorative outline icons; the accompanying definition list provides their accessible labels. */
function FactIcon({ kind }: { kind: string }) {
  const paths: Record<string, React.ReactNode> = {
    hours: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    workLocation: <><path d="M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 0 1 16 0Z" /><circle cx="12" cy="10" r="2" /></>,
    businessLine: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 7h8M8 11h8M8 15h8" /></>,
    experience: <path d="M3 20h5v-5h5v-5h5V5h3" />,
    education: <><path d="m2 9 10-5 10 5-10 5-10-5ZM6 11v6c4 3 8 3 12 0v-6M22 9v7" /></>,
    compensation: <><rect x="2" y="5" width="20" height="14" rx="2" /><circle cx="12" cy="12" r="3" /><path d="M5 9h.01M19 15h.01" /></>,
    workplace: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 7h1m4 0h1M9 11h1m4 0h1M10 21v-6h4v6" /></>,
    role: <><rect x="3" y="7" width="18" height="14" rx="2" /><path d="M8 7V3h8v4M3 12h18M10 12v3h4v-3" /></>,
  };
  return <svg className="job-fact-icon" width="22" height="22" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {paths[kind] ?? <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 11h18M8 15h2m4 0h2" /></>}
  </svg>;
}
