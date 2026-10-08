import { resolveApiAsset } from "../api/client";
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  getCompanyLogoSources,
  isDarkMonochromeLogo,
  isLightMonochromeLogo,
} from "../utils/companyLogos";

export interface CompanyLogoProps {
  company: string;
  logoUrl?: string | null;
  websiteUrl?: string | null;
  size?: "sm" | "md" | "lg" | "36" | "card" | "detail";
  className?: string;
}

/**
 * Shared CompanyLogo Component for RoleRadar.
 * Used across Job Cards, Job Detail Modals, and Company views.
 *
 * Rules:
 * - Tries the official website favicon shown in Google results, then existing verified logos.
 * - Always preserves original brand colors, artwork, and aspect ratios.
 * - Never uses blanket brightness/invert filters.
 * - Dark monochrome marks receive a clean neutral backplate in dark mode.
 * - Light monochrome marks receive a dark neutral backplate in light mode.
 * - When no authentic logo exists or image fails to load, renders an honest
 *   generic company icon (never fake initials or invented logos).
 * - Fixed layout prevents cumulative layout shifts (CLS).
 */
export const CompanyLogo: React.FC<CompanyLogoProps> = ({
  company,
  logoUrl: propLogoUrl,
  websiteUrl,
  size = "md",
  className = "",
}) => {
  const sources = useMemo(() => getCompanyLogoSources(company, propLogoUrl, websiteUrl), [company, propLogoUrl, websiteUrl]);
  const sourceKey = JSON.stringify([company, ...sources]);
  // The generic icon holds the box until the picture has actually loaded, so no card ever shows an empty white square.
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const [failures, setFailures] = useState<{ key: string; urls: string[] }>({ key: "", urls: [] });
  const failedUrls = failures.key === sourceKey ? failures.urls : [];
  const logoUrl = sources.find((source) => !failedUrls.includes(source));
  const resolvedUrl = logoUrl ? resolveApiAsset(logoUrl) : null;
  const isFavicon = Boolean(logoUrl?.startsWith("https://www.google.com/s2/favicons?"));
  const showImage = Boolean(resolvedUrl);
  const isFallback = !showImage;
  const showPlaceholder = isFallback || loadedUrl !== resolvedUrl;
  const isDarkMark = showImage && !isFavicon && isDarkMonochromeLogo(company);
  const isLightMark = showImage && !isFavicon && isLightMonochromeLogo(company);
  // A picture whose load event was missed (cached, or never delivered) would stay hidden behind the icon, so also
  // look at the image itself a few times after it starts loading.
  const imageRef = useRef<HTMLImageElement>(null);
  useEffect(() => {
    if (!resolvedUrl) return;
    const check = () => {
      const image = imageRef.current;
      if (image?.complete && image.naturalWidth > 0) setLoadedUrl(resolvedUrl);
    };
    const timers = [0, 250, 1000, 3000].map((delay) => window.setTimeout(check, delay));
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [resolvedUrl]);
  const dimension = size === "detail" ? 46 : size === "card" ? 42 : size === "lg" ? 44 : size === "sm" ? 28 : 36;
  const iconSize = Math.round(dimension * 0.52);

  return (
    <div
      className={`company-logo-container logo-${size} ${
        showPlaceholder ? "company-logo-container-fallback" : "company-logo-container-image"
      } ${isDarkMark ? "logo-dark-mark" : ""} ${
        isLightMark ? "logo-light-mark" : ""
      } ${isFavicon ? "logo-favicon" : ""} ${className}`}
      aria-label={`${company} logo`}
      role="img"
    >
      {showPlaceholder && (
        <svg
          className="company-logo-fallback-icon"
          width={iconSize}
          height={iconSize}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          {/* Honest generic organization/building icon */}
          <rect x="4" y="2" width="16" height="20" rx="2" ry="2" />
          <path d="M9 22v-4h6v4" />
          <path d="M8 6h.01" />
          <path d="M16 6h.01" />
          <path d="M12 6h.01" />
          <path d="M12 10h.01" />
          <path d="M12 14h.01" />
          <path d="M16 10h.01" />
          <path d="M16 14h.01" />
          <path d="M8 10h.01" />
          <path d="M8 14h.01" />
        </svg>
      )}
      {showImage && (
        <img
          key={resolvedUrl}
          src={resolvedUrl!}
          alt="" /* the wrapper carries the one accessible name */
          width={dimension}
          height={dimension}
          loading="lazy"
          ref={imageRef}
          referrerPolicy="no-referrer"
          onError={() => setFailures((previous) => ({ key: sourceKey,
            urls: Array.from(new Set([...(previous.key === sourceKey ? previous.urls : []), logoUrl!])) }))}
          onLoad={() => setLoadedUrl(resolvedUrl)}
          className={`company-logo-img ${loadedUrl === resolvedUrl ? "logo-img-visible" : "logo-img-loading"}`}
        />
      )}
    </div>
  );
};
