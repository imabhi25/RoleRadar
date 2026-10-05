import React, { useCallback, useEffect, useState } from "react";
import {
  apiClient,
  type BreakdownItem,
  type CountryStats,
  type OverviewStats,
  type SkillStats,
} from "../api/client";
import { formatRoleType, formatWorkplaceType } from "../utils/formatters";
import { CountryChart } from "./CountryChart";
import { ErrorBoundary } from "./ErrorBoundary";
import { SkillsChart } from "./SkillsChart";
import { StatCard } from "./StatCard";

type WidgetState<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error" };

/** One independent request per widget: a failing endpoint only affects its own card. */
function useWidget<T>(load: () => Promise<T>): [WidgetState<T>, () => void] {
  const [state, setState] = useState<WidgetState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    load().then(
      (data) => {
        if (!cancelled) setState({ status: "ready", data });
      },
      (err) => {
        if (!cancelled) {
          console.warn("Stats widget failed to load:", err);
          setState({ status: "error" });
        }
      }
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);
  return [state, useCallback(() => setAttempt((n) => n + 1), [])];
}

const WidgetFallback: React.FC<{ label: string; onRetry: () => void; className?: string }> = ({ label, onRetry, className = "chart-card" }) => (
  <div className={className} role="alert">
    <p className="error-message">{label} couldn’t be loaded right now.</p>
    <button type="button" className="retry-button" onClick={onRetry}>
      Retry
    </button>
  </div>
);

const WidgetLoading: React.FC<{ label: string; className?: string }> = ({ label, className = "chart-card" }) => (
  <div className={className} aria-busy="true">
    <p className="empty-chart">Loading {label.toLowerCase()}…</p>
  </div>
);

function BreakdownCard({
  title,
  subtitle,
  fillClass,
  items,
  format,
}: {
  title: string;
  subtitle: string;
  fillClass: string;
  items: BreakdownItem[];
  format: (category: string) => string;
}) {
  return (
    <div className="breakdown-card">
      <h2 className="breakdown-title">{title}</h2>
      <p className="breakdown-subtitle">{subtitle}</p>
      <div className="breakdown-list">
        {items.map((item) => (
          <div key={item.category} className="breakdown-row">
            <div className="breakdown-row-header">
              <span className="breakdown-name">{format(item.category)}</span>
              <span className="breakdown-count">
                {item.count.toLocaleString()} ({item.share_pct}%)
              </span>
            </div>
            <div className="breakdown-bar-bg">
              <div className={`breakdown-bar-fill ${fillClass}`} style={{ width: `${Math.min(100, item.share_pct)}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface StatsViewProps {
  onBackToJobs: () => void;
  onSkillClick: (skill: string) => void;
}

/**
 * The Stats page. Loaded lazily (charts and their library are not part of the initial Jobs bundle) and every widget
 * loads, fails and retries on its own, so one broken analytics endpoint never blanks the page, let alone the job list.
 */
const StatsView: React.FC<StatsViewProps> = ({ onBackToJobs, onSkillClick }) => {
  const [overview, reloadOverview] = useWidget<OverviewStats>(() => apiClient.getOverview());
  const [countries, reloadCountries] = useWidget<CountryStats[]>(() => apiClient.getCountries());
  const [skills, reloadSkills] = useWidget<SkillStats[]>(() => apiClient.getSkills());
  const [roles, reloadRoles] = useWidget<BreakdownItem[]>(() => apiClient.getRoleStats());
  const [workplaces, reloadWorkplaces] = useWidget<BreakdownItem[]>(() => apiClient.getWorkplaceStats());
  const [companies, reloadCompanies] = useWidget<BreakdownItem[]>(() => apiClient.getCompanyStats());

  const total = overview.status === "ready" ? overview.data.total_postings : undefined;
  const chartFallback = (label: string, retry: () => void) => (reset: () => void) => (
    <WidgetFallback label={label} onRetry={() => { reset(); retry(); }} />
  );

  return (
    <section className="stats-view" aria-label="Market Insights & Analytics">
      <div className="stats-view-header">
        <div>
          <h1 className="stats-view-title">Market Intelligence & Tech Demand</h1>
          <p className="stats-view-subtitle">
            Hiring volume, geographical distribution, and technical skill requirements across all countries.
          </p>
        </div>
        <button type="button" onClick={onBackToJobs} className="secondary-button">
          ← Back to Job Search
        </button>
      </div>

      {overview.status === "ready" && (
        <div className="stats-grid">
          <StatCard label="Total Job Postings" value={overview.data.total_postings} description="Active positions analyzed" icon="📄" />
          <StatCard label="Total Companies" value={overview.data.total_companies} description="Hiring organizations" icon="🏢" />
          <StatCard label="Hiring locations" value={overview.data.total_locations} description="Active locations indexed" icon="📍" />
          <StatCard label="Total Skills" value={overview.data.total_skills} description="Unique technical proficiencies" icon="⚡" />
        </div>
      )}
      {overview.status === "error" && <WidgetFallback label="The headline totals" onRetry={reloadOverview} className="breakdown-card" />}

      <div className="charts-grid">
        <ErrorBoundary fallback={chartFallback("The country chart", reloadCountries)}>
          {countries.status === "ready" && <CountryChart data={countries.data} totalPostings={total} />}
          {countries.status === "loading" && <WidgetLoading label="Country chart" />}
          {countries.status === "error" && <WidgetFallback label="The country chart" onRetry={reloadCountries} />}
        </ErrorBoundary>
        <ErrorBoundary fallback={chartFallback("The skills chart", reloadSkills)}>
          {skills.status === "ready" && <SkillsChart data={skills.data} onSkillClick={onSkillClick} />}
          {skills.status === "loading" && <WidgetLoading label="Skills chart" />}
          {skills.status === "error" && <WidgetFallback label="The skills chart" onRetry={reloadSkills} />}
        </ErrorBoundary>
      </div>

      <div className="breakdowns-grid">
        {roles.status === "ready" && (
          <BreakdownCard title="Role Type Breakdown" subtitle="Distribution of employment structures" fillClass="role-fill" items={roles.data} format={formatRoleType} />
        )}
        {roles.status === "error" && <WidgetFallback label="Role type breakdown" onRetry={reloadRoles} className="breakdown-card" />}
        {workplaces.status === "ready" && (
          <BreakdownCard title="Workplace Type Breakdown" subtitle="Remote vs on-site flexibility" fillClass="workplace-fill" items={workplaces.data} format={formatWorkplaceType} />
        )}
        {workplaces.status === "error" && <WidgetFallback label="Workplace breakdown" onRetry={reloadWorkplaces} className="breakdown-card" />}
        {companies.status === "ready" && (
          <BreakdownCard title="Top Hiring Companies" subtitle="Companies with the most active roles" fillClass="company-fill" items={companies.data.slice(0, 5)} format={(name) => name} />
        )}
        {companies.status === "error" && <WidgetFallback label="Top hiring companies" onRetry={reloadCompanies} className="breakdown-card" />}
      </div>
    </section>
  );
};

export default StatsView;
