import React from "react";
import type { CompanyProfile } from "../utils/companyProfiles";

type LinkKind = "linkedin" | "x" | "github" | "website";

const ICON_PROPS = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "currentColor",
  "aria-hidden": true,
  focusable: false,
} as const;

/** Simple single-colour glyphs so each destination is recognisable at 16px. */
const ICONS: Record<LinkKind, React.ReactElement> = {
  linkedin: (
    <svg {...ICON_PROPS}>
      <path d="M20.4 2H3.6A1.6 1.6 0 0 0 2 3.6v16.8A1.6 1.6 0 0 0 3.6 22h16.8a1.6 1.6 0 0 0 1.6-1.6V3.6A1.6 1.6 0 0 0 20.4 2ZM8.1 18.8H5.2V9.7h2.9v9.1ZM6.6 8.5a1.7 1.7 0 1 1 0-3.400 1.700 1.700 0 0 1 0 3.400Zm12.200 10.300h-2.900v-4.400c0-1.100 0-2.400-1.500-2.400s-1.700 1.100-1.700 2.300v4.500h-2.900V9.700h2.800V11h.1a3 3 0 0 1 2.700-1.500c2.900 0 3.400 1.900 3.400 4.400v4.900Z" />
    </svg>
  ),
  x: (
    <svg {...ICON_PROPS}>
      <path d="M18.200 3h3.100l-6.800 7.700L22.500 21h-6.300l-4.900-6.400L5.600 21H2.500l7.200-8.300L2 3h6.400l4.400 5.900L18.200 3Zm-1.100 16.200h1.700L7.300 4.700H5.500l11.600 14.500Z" />
    </svg>
  ),
  github: (
    <svg {...ICON_PROPS}>
      <path d="M12 .3a12 12 0 0 0-3.800 23.400c.6.1.8-.3.8-.6v-2c-3.300.7-4-1.600-4-1.600-.6-1.400-1.400-1.800-1.400-1.800-1-.7.1-.7.1-.7 1.200.1 1.800 1.200 1.800 1.200 1 1.800 2.800 1.300 3.500 1 0-.8.400-1.300.7-1.600-2.700-.3-5.500-1.300-5.500-5.900 0-1.300.5-2.400 1.200-3.200 0-.4-.5-1.600.2-3.200 0 0 1-.3 3.300 1.200a11.500 11.500 0 0 1 6 0c2.300-1.500 3.300-1.200 3.300-1.200.7 1.600.2 2.800.1 3.200.8.800 1.200 1.900 1.200 3.200 0 4.600-2.800 5.600-5.500 5.900.4.400.8 1.100.8 2.200v3.300c0 .3.2.7.8.6A12 12 0 0 0 12 .3Z" />
    </svg>
  ),
  website: (
    <svg {...ICON_PROPS} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.600 2.700 3.900 5.700 3.900 9s-1.300 6.300-3.900 9c-2.600-2.700-3.900-5.700-3.900-9S9.400 5.700 12 3Z" />
    </svg>
  ),
};

const LABELS: Record<LinkKind, string> = { linkedin: "LinkedIn", x: "X", github: "GitHub", website: "Website" };

interface CompanyLinksProps {
  profile: CompanyProfile;
  className?: string;
}

/**
 * Company-level links (LinkedIn, X, GitHub, Website). X is always icon-only (its name is the glyph). Every one is a real link to a verified URL; a link that
 * is not verified is simply absent. With room they show icon + label, and they collapse to icon-only (the
 * accessible name and tooltip still say where they go) when the pane is tight.
 */
export const CompanyLinks: React.FC<CompanyLinksProps> = ({ profile, className = "" }) => {
  const links: Array<{ kind: LinkKind; url: string }> = [];
  if (profile.linkedin) links.push({ kind: "linkedin", url: profile.linkedin });
  if (profile.x) links.push({ kind: "x", url: profile.x });
  if (profile.github) links.push({ kind: "github", url: profile.github });
  if (profile.website) links.push({ kind: "website", url: profile.website });
  if (links.length === 0) return null;
  return (
    <span className={`company-links ${className}`.trim()} data-count={links.length}>
      {links.map(({ kind, url }) => {
        const destination = kind === "website" ? `${profile.name} website` : `${profile.name} on ${LABELS[kind]}`;
        return (
          <a
            key={kind}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className={`company-link company-link-${kind}`}
            aria-label={`${destination} (opens in a new tab)`}
            title={destination}
          >
            {ICONS[kind]}
            {kind !== "x" && <span className="company-link-label">{LABELS[kind]}</span>}
          </a>
        );
      })}
    </span>
  );
};

/** Verified company facts beyond the header links (description, headquarters, size, founded, industry, benefits). Renders nothing when none exist. */
export const CompanyDetails: React.FC<{ profile: CompanyProfile }> = ({ profile }) => {
  const details: Array<[string, string]> = [];
  if (profile.industry) details.push(["Industry", profile.industry]);
  if (profile.headquarters) details.push(["Headquarters", profile.headquarters]);
  if (profile.size) details.push(["Company size", profile.size]);
  if (profile.founded) details.push(["Founded", profile.founded]);
  if (!profile.description && details.length === 0 && (!profile.benefits || profile.benefits.length === 0)) return null;
  return (
    <div className="job-company-details-block" data-testid="company-details">
      {profile.description && <p className="job-company-description">{profile.description}</p>}
      {details.length > 0 && (
        <dl className="job-company-details">
          {details.map(([label, value]) => (
            <div key={label} className="job-company-detail">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {profile.benefits && profile.benefits.length > 0 && (
        <div className="job-company-benefits">
          <h4 className="job-company-benefits-heading">Benefits &amp; Perks</h4>
          <ul className="job-company-benefits-list">
            {profile.benefits.map((benefit) => (
              <li key={benefit}>{benefit}</li>
            ))}
          </ul>
        </div>
      )}
      {profile.sourceUrl && (
        <div className="job-company-source-provenance">
          <span className="job-company-source-label">Source: </span>
          <a
            href={profile.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="job-company-source-link"
          >
            Official profile
          </a>
          {profile.verifiedDate && (
            <span className="job-company-verified-date"> (verified {profile.verifiedDate})</span>
          )}
        </div>
      )}
    </div>
  );
};
