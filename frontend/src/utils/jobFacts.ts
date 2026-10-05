import type { JobSummary } from "../api/client";
import { collapseRepeatedRange, getCompensationDetail, getCompensationExtras, isPlausibleCompensationText } from "./compensation";
import { formatRoleType, formatWorkplaceType, formatPostingDate, formatPostedDate } from "./formatters";

export interface JobFact {
  key: "posted" | "deadline" | "role" | "jobFamily" | "workplace" | "term" | "workTerm" | "compensation" | "experience" | "education" | "hours" | "businessLine" | "workLocation" | "sourceCompensation";
  label: string;
  value: string;
}

const EMPTY_VALUES = /^(unknown|unspecified|n\/a|na|not available|none|null|undefined|-+)$/i;

/** True when a display value is real content (never "Unknown", "N/A", "Not available", ...). */
export function hasFactValue(value: string | null | undefined): value is string {
  return typeof value === "string" && value.trim() !== "" && !EMPTY_VALUES.test(value.trim());
}

export const formatAbsoluteDate = formatPostingDate;

/**
 * Compact facts for the job detail view. Only facts backed by real data are returned;
 * location and skills live elsewhere so no metadata is shown twice.
 */
export function buildJobFacts(
  job: JobSummary,
  opts: {
    primaryLocation?: string;
    /** Explicit application deadline lifted from the description (ISO date). Never a start-date requirement. */
    deadline?: string;
    /** Explicit "Job Family Group" metadata lifted from the description. */
    jobFamily?: string;
    workLocation?: string;
    hours?: string;
    businessLine?: string;
    /** Employer-named work term, shown as written. */
    workTerm?: string;
    compensation?: string;
  } = {}
): JobFact[] {
  const facts: JobFact[] = [];

  // A date well in the future is a source error, not a posting date: show nothing rather than repeat it.
  const posted = formatPostedDate(job.posted_at, Date.now(), job.posted_at_precision) === null
    ? null : formatAbsoluteDate(job.posted_at, job.posted_at_precision);
  // The detail page shows the exact date only; relative age belongs to browsing (job cards).
  if (posted) facts.push({ key: "posted", label: "Posted", value: posted });
  const applyBy = opts.deadline ? formatAbsoluteDate(opts.deadline, "date") : null;
  if (applyBy) facts.push({ key: "deadline", label: "Apply by", value: applyBy });

  const role = job.role_type ? formatRoleType(job.role_type) : "";
  if (hasFactValue(role)) facts.push({ key: "role", label: "Role", value: role });
  if (hasFactValue(opts.jobFamily)) facts.push({ key: "jobFamily", label: "Job family", value: opts.jobFamily! });

  if (hasFactValue(job.academic_term)) facts.push({ key: "term", label: "Term", value: job.academic_term! });
  // The employer's own wording ("Winter/Term 2"): shown as written, never turned into a season and year.
  if (hasFactValue(opts.workTerm) && opts.workTerm!.toLowerCase() !== (job.academic_term || "").toLowerCase()) {
    facts.push({ key: "workTerm", label: "Work term", value: opts.workTerm! });
  }

  const workplace = job.workplace_type ? formatWorkplaceType(job.workplace_type) : "";
  // "Canada · Remote" already says it: do not repeat Remote as a separate fact.
  const workplaceInLocation = workplace !== "" && new RegExp(`\\b${workplace}\\b`, "i").test(opts.primaryLocation || "");
  if (hasFactValue(workplace) && !workplaceInLocation) facts.push({ key: "workplace", label: "Workplace", value: workplace });

  const comp = job.compensation;
  // One pay format everywhere: the structured figure (same string as the card) plus any non-pay notes from the source.
  const structuredPay = getCompensationDetail(comp);
  const extras = getCompensationExtras(comp);
  // Figures ingestion marked unusable (placeholder, impossible) are not shown through their summary text either.
  // A structured min/max that failed the pay rules does not come back through its own summary string.
  const structuredFailed = Boolean(comp && (comp.min != null || comp.max != null) && !structuredPay);
  const compText = comp && !comp.validation && !structuredFailed
    ? comp.compensationTierSummary || comp.scrapeableCompensationSalarySummary || ""
    : "";
  const compValue = structuredPay
    ? [structuredPay, extras].filter(Boolean).join(" · ")
    : (isPlausibleCompensationText(compText)
        ? collapseRepeatedRange(compText.replace(/\s*[•·]\s*/g, " · ").trim()) : "") || "";
  // Pay that ingestion lifted from this very text is already shown as Compensation: do not repeat it as "Source pay details".
  const sourcePay = opts.compensation && comp?.source !== "posting_text" && isPlausibleCompensationText(opts.compensation) ? opts.compensation : "";
  if (hasFactValue(compValue || sourcePay)) facts.push({ key: "compensation", label: "Compensation", value: compValue || sourcePay });
  if (hasFactValue(compValue) && hasFactValue(sourcePay) && compValue.replace(/[^a-z0-9]/gi, "").toLowerCase() !== sourcePay.replace(/[^a-z0-9]/gi, "").toLowerCase()) {
    facts.push({ key: "sourceCompensation", label: "Source pay details", value: sourcePay });
  }
  if (hasFactValue(opts.hours)) facts.push({ key: "hours", label: "Working hours", value: opts.hours });
  if (hasFactValue(opts.businessLine)) facts.push({ key: "businessLine", label: "Business area", value: opts.businessLine });
  const sameLocation = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (hasFactValue(opts.workLocation) && sameLocation(opts.workLocation) !== sameLocation(opts.primaryLocation || job.location || "")) {
    facts.push({ key: "workLocation", label: "Work location", value: opts.workLocation });
  }

  return facts;
}
