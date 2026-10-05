import React from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from "recharts";
import type { CountryStats } from "../api/client";

interface CountryChartProps {
  data: CountryStats[];
  /** Unique postings overall (the headline figure); the bars below can add up to more than this. */
  totalPostings?: number;
}

const COLORS = ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b"];

/** A posting can list locations in both countries, so per-country counts overlap and are not shares of a whole. */
export const OVERLAP_NOTE = "Multi-country postings may be counted in more than one country.";

export const CountryChart: React.FC<CountryChartProps> = ({ data, totalPostings }) => {
  if (!data || data.length === 0) {
    return (
      <div className="chart-card">
        <div className="chart-header">
          <div>
            <h2 className="chart-title">Jobs with locations in each country</h2>
            <p className="chart-subtitle">{OVERLAP_NOTE}</p>
          </div>
        </div>
        <div className="empty-chart">
          No country-specific location data available for current postings.
        </div>
      </div>
    );
  }

  return (
    <div className="chart-card">
      <div className="chart-header">
        <div>
          <h2 className="chart-title">Jobs with locations in each country</h2>
          <p className="chart-subtitle">
            {OVERLAP_NOTE}
            {totalPostings !== undefined && (
              <> Total unique postings: <strong>{totalPostings.toLocaleString()}</strong>.</>
            )}
          </p>
        </div>
      </div>
      <div className="chart-wrapper">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart
            data={data}
            margin={{ top: 20, right: 20, left: 0, bottom: 20 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
            <XAxis
              dataKey="country"
              tick={{ fill: "var(--text-muted)", fontSize: 13 }}
              tickLine={false}
              axisLine={{ stroke: "var(--border-color)" }}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fill: "var(--text-muted)", fontSize: 13 }}
              tickLine={false}
              axisLine={{ stroke: "var(--border-color)" }}
            />
            <Tooltip
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  const item = payload[0].payload as CountryStats;
                  return (
                    <div className="custom-tooltip">
                      <p className="tooltip-title">{item.country}</p>
                      <p className="tooltip-item">
                        Jobs with a location here: <strong>{item.postings}</strong>
                      </p>
                    </div>
                  );
                }
                return null;
              }}
            />
            <Bar dataKey="postings" radius={[6, 6, 0, 0]} maxBarSize={55}>
              {data.map((_, index) => (
                <Cell
                  key={`country-cell-${index}`}
                  fill={COLORS[index % COLORS.length]}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-footer-metrics">
        {data.map((c, i) => (
          <div key={c.country} className="country-legend-item">
            <span
              className="legend-dot"
              style={{ backgroundColor: COLORS[i % COLORS.length] }}
            />
            <span className="legend-label">{c.country}:</span>
            <span className="legend-value">
              {c.postings.toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};
