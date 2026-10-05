import React from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import type { SkillStats } from "../api/client";

interface SkillsChartProps {
  data: SkillStats[];
  onSkillClick?: (skill: string) => void;
}

function roundToCleanMax(dataMax: number): number {
  if (dataMax <= 0) return 10;
  const target = dataMax * 1.12;
  if (target <= 50) return Math.ceil(target / 10) * 10;
  if (target <= 200) return Math.ceil(target / 25) * 25;
  if (target <= 1000) return Math.ceil(target / 50) * 50;
  return Math.ceil(target / 100) * 100;
}

export const SkillsChart: React.FC<SkillsChartProps> = ({ data, onSkillClick }) => {
  if (!data || data.length === 0) {
    return <div className="empty-chart">No skills data available.</div>;
  }

  // Display top 10 skills
  const displayData = data.slice(0, 10);

  return (
    <div className="chart-card">
      <div className="chart-header">
        <div>
          <h2 className="chart-title">Most Requested Technical Skills</h2>
          <p className="chart-subtitle">
            Ranked by posting mentions (Top 10 skills shown)
          </p>
        </div>
      </div>
      <div className="chart-wrapper">
        <ResponsiveContainer width="100%" height={380}>
          <BarChart
            layout="vertical"
            data={displayData}
            margin={{ top: 10, right: 35, left: 15, bottom: 10 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" horizontal={false} />
            <XAxis
              type="number"
              domain={[0, (dataMax: number) => roundToCleanMax(dataMax)]}
              allowDecimals={false}
              tick={{ fill: "var(--text-muted)", fontSize: 13 }}
              tickLine={false}
              axisLine={{ stroke: "var(--border-color)" }}
            />
            <YAxis
              type="category"
              dataKey="skill"
              tick={{ fill: "var(--text-main)", fontSize: 13, fontWeight: 500, cursor: onSkillClick ? 'pointer' : 'default' }}
              onClick={(data) => {
                if (onSkillClick && data && data.value) {
                  onSkillClick(data.value);
                }
              }}
              tickLine={false}
              axisLine={{ stroke: "var(--border-color)" }}
              width={105}
            />
            <Tooltip
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  const item = payload[0].payload as SkillStats;
                  return (
                    <div className="custom-tooltip">
                      <p className="tooltip-title">
                        #{item.rank} {item.skill}
                      </p>
                      <p className="tooltip-item">
                        Mentions: <strong>{item.mentions}</strong> postings
                      </p>
                      <p className="tooltip-item">
                        Frequency: <strong>{item.frequency_pct}%</strong>
                      </p>
                    </div>
                  );
                }
                return null;
              }}
              wrapperStyle={{ zIndex: 100 }}
              cursor={{ fill: 'var(--bg-raised)' }}
            />
            <Bar
              dataKey="mentions"
              fill="var(--primary)"
              radius={[0, 6, 6, 0]}
              maxBarSize={22}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              onClick={(data: any) => onSkillClick && onSkillClick(data.skill)}
              style={{ cursor: onSkillClick ? 'pointer' : 'default' }}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
