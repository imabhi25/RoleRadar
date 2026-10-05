import React from "react";
import type { JobSummary } from "../api/client";
import {
  formatPostedDate,
  formatPostingDate,
  formatJobTitle,
} from "../utils/formatters";
import { CompanyLogo } from "./CompanyLogo";
import { formatExtraLocations, summarizeLocations } from "../utils/locations";
import { getJobCardCompensation } from "../utils/compensation";

interface JobCardProps {
  job: JobSummary;
  onClick: (jobId: string) => void;
  /** Highlights the card whose detail is open in the desktop split view. */
  selected?: boolean;
  /** Countries in the active Country filter: a job with several locations leads with the one the user asked for. */
  preferredCountries?: string[];
}

export const JobCard: React.FC<JobCardProps> = ({ job, onClick, selected = false, preferredCountries }) => {
  // With a country filter active, a multi-location job shows the location that matches it (Toronto for Canada)
  // instead of whichever location the employer listed first (San Francisco).
  const matching = preferredCountries && preferredCountries.length > 0 && !preferredCountries.includes(job.country ?? "")
    ? job.locations?.find((loc) => preferredCountries.includes(loc.country))
    : undefined;
  const locations = summarizeLocations({ ...job, locations: matching ? [matching, ...(job.locations || []).filter((loc) => loc !== matching)] : job.locations });
  const cardLocations = [...new Set(locations.all.map((label) => label.split(" · ")[0]))];
  const primaryLocation = cardLocations[0] || "";
  const displayLocation = cardLocations.length > 1 ? `${primaryLocation} ${formatExtraLocations(cardLocations.length - 1)}` : primaryLocation;
  const fullLocation = cardLocations.join("; ");
  const displayDate = formatPostedDate(job.posted_at, Date.now(), job.posted_at_precision);
  const displayCompensation = getJobCardCompensation(job.compensation);

  // Browsing cards show only location, available salary, and posting age.
  const metaItems: {
    text: string;
    isLocation?: boolean;
    isCompensation?: boolean;
    isDate?: boolean;
    fullText?: string;
    isoDate?: string;
  }[] = [];
  if (displayLocation) {
    metaItems.push({
      text: displayLocation,
      isLocation: true,
      fullText: fullLocation,
    });
  }
  if (displayCompensation) {
    metaItems.push({
      text: displayCompensation,
      isCompensation: true,
      fullText: "Employer-provided compensation",
    });
  }
  if (displayDate) {
    metaItems.push({
      text: displayDate,
      isDate: true,
      isoDate: job.posted_at || undefined,
      fullText: formatPostingDate(job.posted_at, job.posted_at_precision) || undefined,
    });
  }

  return (
    <article
      className={`job-card${selected ? " is-selected" : ""}`}
      id={`job-card-${job.job_id}`}
    >
      <div className="job-card-inner">
        {/* Company Logo with automatic fallback */}
        <CompanyLogo
          company={job.company}
          logoUrl={job.company_logo_url}
          size="card"
        />

        {/* Card Main Info */}
        <div className="job-card-content">
          {/* Top Row: Title */}
          <div className="job-card-title-row">
            <h3 className="job-card-title">
              {/* The one real control: a native button whose hit area is stretched over the whole card (CSS ::after),
                  so keyboard, screen-reader and pointer users all get the same single, correctly-named target. */}
              <button
                type="button"
                className="job-title-btn"
                id={`job-title-btn-${job.job_id}`}
                aria-current={selected ? "true" : undefined}
                aria-label={`View details for ${job.title} at ${job.company}`}
                onClick={() => onClick(job.job_id)}
              >
                <span className="job-card-title-text">{formatJobTitle(job.title)}</span>
              </button>
            </h3>
          </div>

          {/* Company Name */}
          <div className="job-card-company">{job.company}</div>

          {/* Location • Salary, when supplied • Posted age */}
          {metaItems.length > 0 && (
            <div className="job-card-meta-row">
              {metaItems.map((item, idx) => (
                <span
                  key={idx}
                  className={`meta-detail ${
                    item.isLocation ? "meta-location" : item.isCompensation ? "meta-compensation" : item.isDate ? "meta-date" : ""
                  }`.trim()}
                  title={item.fullText}
                >
                  {item.isLocation && (
                    <svg
                      className="location-icon"
                      width="13"
                      height="13"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                      <circle cx="12" cy="10" r="3" />
                    </svg>
                  )}
                  {item.isDate && item.isoDate ? (
                    <time dateTime={item.isoDate} title={item.fullText}>
                      {item.text}
                    </time>
                  ) : (
                    item.text
                  )}
                </span>
              ))}
            </div>
          )}

        </div>

        {/* Right CTA Hint: Non-interactive to avoid duplicate tab stops */}
        <div className="job-card-action-wrap" aria-hidden="true">
          <span className="view-job-hint">View details →</span>
        </div>
      </div>
    </article>
  );
};
