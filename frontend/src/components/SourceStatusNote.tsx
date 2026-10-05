import React, { useEffect, useState } from "react";
import { apiClient, type SourceStatus } from "../api/client";

/**
 * Optional freshness note for the "Official company sources" card. A single global "last refreshed" time cannot show
 * that some employers failed their latest refresh, so this reports degraded coverage per source. It renders nothing
 * while loading, on failure, or when every source is healthy: browsing never depends on it.
 */
export const SourceStatusNote: React.FC = () => {
  const [sources, setSources] = useState<SourceStatus[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    apiClient
      .getSourceStatus(controller.signal)
      .then(setSources)
      .catch(() => setSources(null));
    return () => controller.abort();
  }, []);

  const degraded = (sources ?? []).filter((s) => s.companies_degraded > 0);
  if (degraded.length === 0) return null;
  const count = degraded.reduce((sum, s) => sum + s.companies_degraded, 0);
  return (
    <p className="sources-card-body sources-card-degraded" role="status" data-testid="source-degraded">
      {count} {count === 1 ? "employer" : "employers"} could not be refreshed on the latest run
      {" "}({degraded.map((s) => s.source_name).join(", ")}). Their existing listings are kept and may be out of date.
    </p>
  );
};
