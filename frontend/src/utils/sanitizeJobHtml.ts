import sanitizeHtml from "sanitize-html";
import { isValidHttpUrl } from "./applyUrls";

/**
 * Restrictive allow-list configuration for sanitize-html.
 * Allows safe semantic typography and layout tags while eliminating
 * scripts, styles, iframes, objects, forms, inline event handlers, and unsafe URLs.
 */
export const RESTRICTIVE_SANITIZER_CONFIG: sanitizeHtml.IOptions = {
  allowedTags: [
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "strong", "b", "em", "i", "u", "s", "strike",
    "blockquote", "code", "pre", "div", "span", "table", "thead", "tbody", "tr", "th", "td",
    "a"
  ],
  allowedAttributes: {
    a: ["href", "target", "rel", "title"]
  },
  allowedSchemes: ["http", "https", "mailto"],
  allowedSchemesByTag: {
    a: ["http", "https", "mailto"]
  },
  allowProtocolRelative: false,
  transformTags: {
    a: (_tagName, attribs) => ({
      tagName: "a",
      attribs: {
        ...attribs,
        target: "_blank",
        rel: "noopener noreferrer"
      }
    })
  }
};

/**
 * Sanitizes untrusted job descriptions into safe, sanitized HTML using
 * the maintained, server-compatible `sanitize-html` library with a restrictive allow-list.
 */
export function sanitizeJobHtml(rawHtml: string | null | undefined): string {
  if (!rawHtml || typeof rawHtml !== "string") {
    return "<p>No description provided.</p>";
  }

  const clean = sanitizeHtml(rawHtml, RESTRICTIVE_SANITIZER_CONFIG).trim();

  // Strip empty tags or whitespace-only results
  const textContent = clean.replace(/<[^>]*>/g, "").trim();
  if (!textContent) {
    return "<p>No description provided.</p>";
  }

  return clean;
}

/**
 * Validates untrusted Apply URLs to ensure they only use http: or https:,
 * preventing javascript:, data:, vbscript:, or malformed protocols.
 */
export function validateApplyUrl(url: string | null | undefined): string | null {
  if (!url || typeof url !== "string") return null;
  const trimmed = url.trim();
  if (trimmed.length < 10 || /[\s\r\n\t<>"'`]/.test(trimmed)) {
    return null;
  }
  if (!isValidHttpUrl(trimmed)) return null;

  try {
    const parsed = new URL(trimmed);
    if ((parsed.protocol === "http:" || parsed.protocol === "https:") && parsed.hostname && parsed.hostname.includes(".")) {
      return parsed.href;
    }
    return null;
  } catch {
    return null;
  }
}
