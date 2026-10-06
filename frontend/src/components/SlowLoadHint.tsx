import React, { useEffect, useState } from "react";

const DEFAULT_DELAY_MS = 4000;

/**
 * The API runs on a host that sleeps when idle, so the first request after a quiet period can take up to a minute.
 * Mounted only while a request is pending; after a short delay it explains the wait so the page doesn't look broken.
 */
export const SlowLoadHint: React.FC<{ delayMs?: number }> = ({ delayMs = DEFAULT_DELAY_MS }) => {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(true), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs]);

  if (!visible) return null;
  return (
    <p className="slow-load-hint" role="status">
      Waking up the server. The first load after a quiet period can take up to a minute.
    </p>
  );
};
