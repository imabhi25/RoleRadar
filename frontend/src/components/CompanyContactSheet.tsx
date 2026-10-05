import React, { useEffect, useState } from "react";
import { apiClient, type CompanyInfo } from "../api/client";
import { CompanyLogo } from "./CompanyLogo";

const PRIORITY_COMPANIES = [
  "Carta",
  "Faire",
  "Plaid",
  "Figma",
  "Scale AI",
  "Waabi",
  "PointClickCare",
  "Stability AI",
];

const FALLBACK_COMPANY_CATALOG: CompanyInfo[] = [
  { name: "Carta", logo_url: "/logos/carta.png", logo_source_url: "https://s3-recruiting.cdn.greenhouse.io/external_greenhouse_job_boards/logos/400/110/100/original/CartaLogo_Black_(1).png", logo_status: "verified", website_url: "https://carta.com", active_jobs_count: 0 },
  { name: "Faire", logo_url: "/logos/faire.png", logo_source_url: "https://www.faire.com/apple-touch-icon.png", logo_status: "verified", website_url: "https://faire.com", active_jobs_count: 0 },
  { name: "Figma", logo_url: "/logos/figma.svg", logo_source_url: "https://upload.wikimedia.org/wikipedia/commons/3/33/Figma-logo.svg", logo_status: "verified", website_url: "https://figma.com", active_jobs_count: 0 },
  { name: "Plaid", logo_url: "/logos/plaid.png", logo_source_url: "https://plaid.com/assets/img/favicons/apple-touch-icon.png", logo_status: "verified", website_url: "https://plaid.com", active_jobs_count: 0 },
  { name: "PointClickCare", logo_url: "/logos/pointclickcare.png", logo_source_url: "https://lever-client-logos.s3.us-west-2.amazonaws.com/458c92e4-e8e4-4bcb-b79a-4d9663eaf4b8-1760615686801.png", logo_status: "verified", website_url: "https://pointclickcare.com", active_jobs_count: 0 },
  { name: "Scale AI", logo_url: "/logos/scaleai.svg", logo_source_url: "https://scale.com/favicon.svg", logo_status: "verified", website_url: "https://scale.com", active_jobs_count: 0 },
  { name: "Stability AI", logo_url: "/logos/stabilityai.png", logo_source_url: "https://images.squarespace-cdn.com/content/v1/6213c340453c3f502425776e/a3485d53-7e65-42b5-bc62-e2e55f8409b9/stability-ai-white-dot-desktop.png", logo_status: "verified", website_url: "https://stability.ai", active_jobs_count: 0 },
  { name: "Waabi", logo_url: "/logos/waabi.png", logo_source_url: "https://lever-client-logos.s3.us-west-2.amazonaws.com/99d3bf4f-9035-4cb6-9d7c-51c8ad9412a8-1757943910265.png", logo_status: "verified", website_url: "https://waabi.ai", active_jobs_count: 0 },
  { name: "1Password", logo_url: "/logos/1password.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://1password.com", active_jobs_count: 0 },
  { name: "Anthropic", logo_url: "/logos/anthropic.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://anthropic.com", active_jobs_count: 0 },
  { name: "Anyscale", logo_url: "/logos/anyscale.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://anyscale.com", active_jobs_count: 0 },
  { name: "Brex", logo_url: "/logos/brex.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://brex.com", active_jobs_count: 0 },
  { name: "Chime", logo_url: "/logos/chime.png", logo_source_url: "https://chime.com", logo_status: "verified", website_url: "https://chime.com", active_jobs_count: 0 },
  { name: "Cloudflare", logo_url: "/logos/cloudflare.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://cloudflare.com", active_jobs_count: 0 },
  { name: "Cohere", logo_url: "/logos/cohere.png", logo_source_url: "https://cohere.com", logo_status: "verified", website_url: "https://cohere.com", active_jobs_count: 0 },
  { name: "Coinbase", logo_url: "/logos/coinbase.svg", logo_source_url: "https://coinbase.com", logo_status: "verified", website_url: "https://coinbase.com", active_jobs_count: 0 },
  { name: "Databricks", logo_url: "/logos/databricks.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://databricks.com", active_jobs_count: 0 },
  { name: "Datadog", logo_url: "/logos/datadog.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://datadoghq.com", active_jobs_count: 0 },
  { name: "Duolingo", logo_url: "/logos/duolingo.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://duolingo.com", active_jobs_count: 0 },
  { name: "Flexport", logo_url: "/logos/flexport.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://flexport.com", active_jobs_count: 0 },
  { name: "GitLab", logo_url: "/logos/gitlab.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://gitlab.com", active_jobs_count: 0 },
  { name: "Grafana Labs", logo_url: "/logos/grafana.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://grafana.com", active_jobs_count: 0 },
  { name: "Linear", logo_url: "/logos/linear.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://linear.app", active_jobs_count: 0 },
  { name: "Mercury", logo_url: "/logos/mercury.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://mercury.com", active_jobs_count: 0 },
  { name: "Metabase", logo_url: "/logos/metabase.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://metabase.com", active_jobs_count: 0 },
  { name: "Mistral AI", logo_url: "/logos/mistralai.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://mistral.ai", active_jobs_count: 0 },
  { name: "Monzo", logo_url: "/logos/monzo.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://monzo.com", active_jobs_count: 0 },
  { name: "Neon", logo_url: "/logos/neon.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://neon.tech", active_jobs_count: 0 },
  { name: "Notion", logo_url: "/logos/notion.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://notion.so", active_jobs_count: 0 },
  { name: "OpenAI", logo_url: "/logos/openai.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://openai.com", active_jobs_count: 0 },
  { name: "Palantir", logo_url: "/logos/palantir.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://palantir.com", active_jobs_count: 0 },
  { name: "Pinterest", logo_url: "/logos/pinterest.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://pinterest.com", active_jobs_count: 0 },
  { name: "PlanetScale", logo_url: "/logos/planetscale.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://planetscale.com", active_jobs_count: 0 },
  { name: "Ramp", logo_url: "/logos/ramp.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://ramp.com", active_jobs_count: 0 },
  { name: "Reddit", logo_url: "/logos/reddit.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://reddit.com", active_jobs_count: 0 },
  { name: "Render", logo_url: "/logos/render.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://render.com", active_jobs_count: 0 },
  { name: "Replit", logo_url: "/logos/replit.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://replit.com", active_jobs_count: 0 },
  { name: "Robinhood", logo_url: "/logos/robinhood.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://robinhood.com", active_jobs_count: 0 },
  { name: "Rubrik", logo_url: "/logos/rubrik.png", logo_source_url: "https://boards.greenhouse.io/rubrik", logo_status: "verified", website_url: "https://rubrik.com", active_jobs_count: 0 },
  { name: "Runway", logo_url: "/logos/runway.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://runwayml.com", active_jobs_count: 0 },
  { name: "Samsara", logo_url: "/logos/samsara.png", logo_source_url: "https://samsara.com", logo_status: "verified", website_url: "https://samsara.com", active_jobs_count: 0 },
  { name: "Sentry", logo_url: "/logos/sentry.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://sentry.io", active_jobs_count: 0 },
  { name: "Sourcegraph", logo_url: "/logos/sourcegraph.png", logo_source_url: "https://sourcegraph.com", logo_status: "verified", website_url: "https://sourcegraph.com", active_jobs_count: 0 },
  { name: "Spotify", logo_url: "/logos/spotify.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://spotify.com", active_jobs_count: 0 },
  { name: "StackAdapt", logo_url: "/logos/stackadapt.png", logo_source_url: "https://stackadapt.com", logo_status: "verified", website_url: "https://stackadapt.com", active_jobs_count: 0 },
  { name: "Stripe", logo_url: "/logos/stripe.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://stripe.com", active_jobs_count: 0 },
  { name: "Supabase", logo_url: "/logos/supabase.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://supabase.com", active_jobs_count: 0 },
  { name: "Toast", logo_url: "/logos/toast.png", logo_source_url: "https://toasttab.com", logo_status: "verified", website_url: "https://toasttab.com", active_jobs_count: 0 },
  { name: "Vercel", logo_url: "/logos/vercel.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://vercel.com", active_jobs_count: 0 },
  { name: "Wealthsimple", logo_url: "/logos/wealthsimple.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://wealthsimple.com", active_jobs_count: 0 },
  { name: "Webflow", logo_url: "/logos/webflow.svg", logo_source_url: "https://simpleicons.org/", logo_status: "verified", website_url: "https://webflow.com", active_jobs_count: 0 },
  { name: "Acme Cloudworks", logo_url: null, logo_source_url: null, logo_status: "unresolved", website_url: null, active_jobs_count: 0 },
  { name: "Biolink Horizons", logo_url: null, logo_source_url: null, logo_status: "unresolved", website_url: null, active_jobs_count: 0 },
  { name: "CyberDwarf Systems", logo_url: null, logo_source_url: null, logo_status: "unresolved", website_url: null, active_jobs_count: 0 },
  { name: "Nimbus Galactic Solutions", logo_url: null, logo_source_url: null, logo_status: "unresolved", website_url: null, active_jobs_count: 0 },
  { name: "PixelPioneer Studios", logo_url: null, logo_source_url: null, logo_status: "unresolved", website_url: null, active_jobs_count: 0 },
  { name: "Quantum Quokka Corp", logo_url: null, logo_source_url: null, logo_status: "unresolved", website_url: null, active_jobs_count: 0 },
  { name: "RetroRocket Robotics", logo_url: null, logo_source_url: null, logo_status: "unresolved", website_url: null, active_jobs_count: 0 },
  { name: "Starlight Data Labs", logo_url: null, logo_source_url: null, logo_status: "unresolved", website_url: null, active_jobs_count: 0 },
];

export const CompanyContactSheet: React.FC = () => {
  const [companies, setCompanies] = useState<CompanyInfo[]>(FALLBACK_COMPANY_CATALOG);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();
    apiClient
      .getCompanies(controller.signal)
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setCompanies(data);
        } else {
          setCompanies(FALLBACK_COMPANY_CATALOG);
        }
        setLoading(false);
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        // Fallback to local verified catalog if remote API does not have /api/companies yet
        setCompanies(FALLBACK_COMPANY_CATALOG);
        setLoading(false);
      });
    return () => controller.abort();
  }, []);

  // Partition companies into priority, verified, and unresolved
  const priorityList = companies.filter((c) =>
    PRIORITY_COMPANIES.some((p) => p.toLowerCase() === c.name.toLowerCase())
  );
  const otherVerifiedList = companies.filter(
    (c) =>
      c.logo_status === "verified" &&
      !PRIORITY_COMPANIES.some((p) => p.toLowerCase() === c.name.toLowerCase())
  );
  const unresolvedList = companies.filter((c) => c.logo_status !== "verified");

  return (
    <div className="contact-sheet-page">
      <header className="contact-sheet-header">
        <h1 className="contact-sheet-title">Company Logo & Branding Contact Sheet</h1>
        <p className="contact-sheet-subtitle">
          Audited verified brand marks and honest fallbacks across light & dark themes.
          No blanket brightness/invert filters • Original colors and artwork preserved.
        </p>
      </header>

      {/* Summary KPI Badges */}
      <div className="contact-sheet-stats">
        <div className="contact-sheet-stat-badge stat-verified">
          <span className="stat-number">
            {companies.filter((c) => c.logo_status === "verified").length}
          </span>
          <span className="stat-label">Verified Authentic Logos</span>
        </div>
        <div className="contact-sheet-stat-badge stat-unresolved">
          <span className="stat-number">{unresolvedList.length}</span>
          <span className="stat-label">Unresolved (Flagged for Review)</span>
        </div>
        <div className="contact-sheet-stat-badge stat-total">
          <span className="stat-number">{companies.length}</span>
          <span className="stat-label">Total Companies</span>
        </div>
      </div>

      {loading && <p className="contact-sheet-loading">Loading company branding catalog...</p>}

      {/* Section 1: Priority Companies */}
      <section className="contact-sheet-section">
        <div className="section-header-wrap">
          <h2 className="contact-sheet-section-title">Priority Companies (Audit Focus)</h2>
          <span className="section-count">{priorityList.length} Companies</span>
        </div>
        <div className="contact-sheet-grid">
          {priorityList.map((company) => (
            <CompanyAuditCard key={company.name} company={company} />
          ))}
        </div>
      </section>

      {/* Section 2: Other Verified Companies */}
      <section className="contact-sheet-section">
        <div className="section-header-wrap">
          <h2 className="contact-sheet-section-title">Verified Tech Companies</h2>
          <span className="section-count">{otherVerifiedList.length} Companies</span>
        </div>
        <div className="contact-sheet-grid">
          {otherVerifiedList.map((company) => (
            <CompanyAuditCard key={company.name} company={company} />
          ))}
        </div>
      </section>

      {/* Section 3: Unresolved / Flagged Companies */}
      <section className="contact-sheet-section">
        <div className="section-header-wrap">
          <h2 className="contact-sheet-section-title">Unresolved / Flagged for Review</h2>
          <span className="section-count">{unresolvedList.length} Companies</span>
        </div>
        <p className="unresolved-explanation">
          These companies have no verified authentic logo asset on file. As mandated, RoleRadar
          renders an honest generic company building icon and flags the company for manual review,
          never fabricating or inventing placeholder graphics.
        </p>
        <div className="contact-sheet-grid">
          {unresolvedList.map((company) => (
            <CompanyAuditCard key={company.name} company={company} />
          ))}
        </div>
      </section>
    </div>
  );
};

interface CompanyAuditCardProps {
  company: CompanyInfo;
}

const CompanyAuditCard: React.FC<CompanyAuditCardProps> = ({ company }) => {
  const isVerified = company.logo_status === "verified";

  return (
    <article className="company-audit-card">
      <div className="company-audit-header">
        <h3 className="company-audit-name">{company.name}</h3>
        <span
          className={`company-status-pill ${
            isVerified ? "status-verified" : "status-unresolved"
          }`}
        >
          {isVerified ? "✓ Verified" : "⚠ Unresolved"}
        </span>
      </div>

      {/* Dual Theme Preview (Side-by-side Light & Dark verification) */}
      <div className="company-audit-previews">
        {/* Light Theme Box */}
        <div className="theme-preview-box light-preview" data-theme="light">
          <span className="preview-label">Light</span>
          <div className="preview-logos-row">
            <CompanyLogo company={company.name} logoUrl={company.logo_url} size="sm" />
            <CompanyLogo company={company.name} logoUrl={company.logo_url} size="md" />
            <CompanyLogo company={company.name} logoUrl={company.logo_url} size="lg" />
          </div>
        </div>

        {/* Dark Theme Box */}
        <div className="theme-preview-box dark-preview" data-theme="dark">
          <span className="preview-label">Dark</span>
          <div className="preview-logos-row">
            <CompanyLogo company={company.name} logoUrl={company.logo_url} size="sm" />
            <CompanyLogo company={company.name} logoUrl={company.logo_url} size="md" />
            <CompanyLogo company={company.name} logoUrl={company.logo_url} size="lg" />
          </div>
        </div>
      </div>

      {/* Metadata & Provenance */}
      <div className="company-audit-meta">
        <div className="meta-line">
          <span className="meta-key">Asset:</span>
          <span className="meta-val meta-code">
            {company.logo_url || "Generic fallback icon"}
          </span>
        </div>
        {company.logo_source_url && (
          <div className="meta-line">
            <span className="meta-key">Source:</span>
            <a
              href={company.logo_source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="meta-val meta-link"
              title={company.logo_source_url}
            >
              {truncateUrl(company.logo_source_url)} ↗
            </a>
          </div>
        )}
        {company.website_url && (
          <div className="meta-line">
            <span className="meta-key">Website:</span>
            <a
              href={company.website_url}
              target="_blank"
              rel="noopener noreferrer"
              className="meta-val meta-link"
            >
              {company.website_url} ↗
            </a>
          </div>
        )}
      </div>
    </article>
  );
};

function truncateUrl(url: string): string {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.length > 20 ? parsed.pathname.slice(0, 18) + "…" : parsed.pathname;
    return `${parsed.hostname}${path}`;
  } catch {
    return url.length > 30 ? url.slice(0, 27) + "…" : url;
  }
}
