import { parseAndSanitizeJobDescription } from "./sanitizeDescription";
import {
  presentHeadings,
  removeEmptySections,
  removeRedundantJobHeading,
  removeTitleHeadings,
  separateCompanyIntro,
  separateTeamIntro,
  splitPolicySections,
  structureDescription,
} from "./descriptionSections";
import { extractMetadata, type DescriptionMetadata } from "./descriptionMetadata";
import { analyzeLanguage, type DescriptionView, type Lang } from "./descriptionLanguage";

export interface DescriptionParts {
  companyHtml: string;
  /** Team / background introduction that precedes the role itself ("About the team"); never company background. */
  teamHtml: string;
  mainHtml: string;
  policiesHtml: string;
}

export interface RenderedDescription extends DescriptionParts {
  /** Explicit deadline / address / job family lifted out of the prose (never invented). */
  meta: DescriptionMetadata;
  /** Views the reader can choose between; empty unless the employer supplied both an English and a French half. */
  views: DescriptionView[];
  /** The view these fragments belong to. */
  view: DescriptionView;
  /** Language of the text shown: set when the whole description is clearly one language. */
  language: Lang | null;
}

const EMPTY: DescriptionParts = { companyHtml: "", teamHtml: "", mainHtml: "", policiesHtml: "" };

/** Sanitized HTML (metadata and language already handled) -> the four fragments the detail pane renders. */
function toParts(html: string, company: string, title: string): DescriptionParts {
  const split = splitPolicySections(removeEmptySections(removeTitleHeadings(html, title)));
  // A leading company intro (only when unambiguous) gets its own "About the Company"; a leading team intro sits
  // between it and "About the Job", which then begins at the role's own heading.
  const { companyHtml, jobHtml } = separateCompanyIntro(structureDescription(split.mainHtml, company), company, title);
  const { teamHtml, jobHtml: roleHtml } = separateTeamIntro(jobHtml);
  return {
    companyHtml: presentHeadings(companyHtml),
    teamHtml: presentHeadings(teamHtml),
    mainHtml: presentHeadings(removeRedundantJobHeading(roleHtml)),
    policiesHtml: presentHeadings(split.policiesHtml),
  };
}

/**
 * The one path from a stored description to what the job detail renders. Shared by the UI and the integrity tests so
 * the tests exercise exactly what users see.
 *
 * `view` selects the English or French half of an employer-written bilingual description ("original" is the whole
 * text). It is ignored (the whole text is used) for descriptions that are not clearly bilingual.
 */
export function renderDescription(
  raw: string | null | undefined,
  company: string,
  title: string,
  view?: DescriptionView
): RenderedDescription {
  if (!raw) return { ...EMPTY, meta: {}, views: [], view: "original", language: null };
  const parsed = parseAndSanitizeJobDescription(raw, company);
  const { html, meta } = extractMetadata(parsed.html);
  const analysis = analyzeLanguage(html);
  const chosen: DescriptionView = analysis.bilingual ? (view && analysis.views.includes(view) ? view : "en") : "original";
  return {
    ...toParts(analysis.html[chosen], company, title),
    meta,
    views: analysis.views,
    view: chosen,
    language: analysis.bilingual ? (chosen === "original" ? null : chosen) : analysis.single,
  };
}
