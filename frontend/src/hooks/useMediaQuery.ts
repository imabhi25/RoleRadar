import { useEffect, useState } from "react";

/** Tracks a CSS media query. Treats a missing matchMedia (or a non-matching stub) as "no match". */
export function useMediaQuery(query: string): boolean {
  const read = () =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? Boolean(window.matchMedia(query)?.matches)
      : false;
  const [matches, setMatches] = useState<boolean>(read);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(query);
    if (!mql) return;
    const onChange = () => setMatches(Boolean(mql.matches));
    onChange();
    mql.addEventListener?.("change", onChange);
    return () => mql.removeEventListener?.("change", onChange);
  }, [query]);

  return matches;
}

/** Desktop/tablet widths get the split view; phones keep the single-column overlay. */
export const SPLIT_VIEW_QUERY = "(min-width: 900px)";
export function useSplitView(): boolean {
  return useMediaQuery(SPLIT_VIEW_QUERY);
}
