import React, { useEffect, useState } from "react";
import { apiClient, type SourceStatus } from "../api/client";

// The scheduled importer runs every three hours. Allow for delayed starts and long scans.
const STALE_HOURS = 12;
const refreshDate = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export const SourceStatusNote: React.FC = () => {
  const [sources, setSources] = useState<SourceStatus[] | "unavailable" | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    apiClient
      .getSourceStatus(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setSources(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) setSources("unavailable");
      });
    return () => controller.abort();
  }, []);

  if (sources === null) return null;
  if (sources === "unavailable") {
    return <p className="source-status" role="status">Source refresh status unavailable.</p>;
  }

  const cutoff = Date.now() - STALE_HOURS * 60 * 60 * 1000;
  const stale: string[] = [];
  let latestSuccess: number | null = null;
  for (const source of sources) {
    const timestamp = Date.parse(source.last_success_at ?? "");
    const hasSuccess = Number.isFinite(timestamp);
    if (hasSuccess && (latestSuccess === null || timestamp > latestSuccess)) {
      latestSuccess = timestamp;
    }
    if (!hasSuccess || timestamp < cutoff) stale.push(source.source_name);
  }

  const degraded = sources.filter((source) => source.companies_degraded > 0);
  const count = degraded.reduce((sum, source) => sum + source.companies_degraded, 0);
  const latest = latestSuccess === null ? null : new Date(latestSuccess);
  return (
    <div className="source-status" role="status">
      <p>
        {latest ? (
          <>Latest successful source refresh on <time dateTime={latest.toISOString()}>{refreshDate.format(latest)}</time></>
        ) : "No successful source refresh recorded yet."}
      </p>
      {count > 0 && (
        <p data-testid="source-degraded">
          {count} {count === 1 ? "employer" : "employers"} could not be fully refreshed on their latest attempt
          {" "}({degraded.map((source) => source.source_name).join(", ")}). Existing listings may be out of date.
        </p>
      )}
      {stale.length > 0 && (
        <p>No successful refresh in the last {STALE_HOURS} hours for {stale.join(", ")}.</p>
      )}
    </div>
  );
};
