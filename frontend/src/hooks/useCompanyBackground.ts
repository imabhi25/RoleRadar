import { useEffect, useMemo, useState } from "react";
import type { CompanyProfile } from "../utils/companyProfiles";

interface Background { description: string; sourceUrl: string; }
const cache = new Map<string, Background>();

/** Independent company information is shared by all current and future roles at the company. */
export function useCompanyBackground(base: CompanyProfile | null): CompanyProfile | null {
  const key = base?.website ? `${base.name}\n${base.website}` : "";
  const [loaded, setLoaded] = useState<{ key: string; background: Background } | null>(null);
  useEffect(() => {
    if (!base || base.description || !base.website || !key || cache.has(key)) return;
    const controller = new AbortController();
    const query = new URLSearchParams({ company: base.name, website: base.website });
    void fetch(`/company-background?${query}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) return;
        const value = await response.json() as Partial<Background>;
        if (typeof value.description !== "string" || !value.description.trim() || value.description.length > 1200 || typeof value.sourceUrl !== "string") return;
        const source = new URL(value.sourceUrl);
        const companyHost = new URL(base.website!).hostname.replace(/^www\./, "");
        if (source.protocol !== "https:" || (source.hostname.replace(/^www\./, "") !== companyHost && !source.hostname.endsWith(`.${companyHost}`))) return;
        if (controller.signal.aborted) return;
        const background = { description: value.description, sourceUrl: source.href };
        if (cache.size >= 256) cache.delete(cache.keys().next().value!);
        cache.set(key, background);
        setLoaded({ key, background });
      })
      .catch(() => { /* Keep the company identity and links; never invent background or display a source diagnostic. */ });
    return () => controller.abort();
  }, [base, key]);
  return useMemo(() => {
    if (!base || base.description) return base;
    const background = loaded?.key === key ? loaded.background : cache.get(key);
    return background ? { ...base, ...background } : base;
  }, [base, key, loaded]);
}
