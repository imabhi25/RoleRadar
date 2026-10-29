import React, { useEffect, useState } from "react";

const DEFAULT_DELAY_MS = 4000;

/**
 * Mounted only while a request is pending; after a short delay it explains the wait so the page doesn't look broken.
 * The API runs as a Vercel Function, so a cold start adds a few seconds at most.
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
      Still loading. This is taking a little longer than usual.
    </p>
  );
};
