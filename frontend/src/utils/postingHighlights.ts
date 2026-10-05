import type { JobFact } from "./jobFacts";

/** Highlights source statements without inventing a level or turning preferred degrees into requirements. */
export function postingHighlights(title: string, sanitizedHtml: string, experienceLevel?: string | null): JobFact[] {
  const facts: JobFact[] = [];
  const levels: Record<string, string> = { internship: "Internship", entry: "Entry level", mid: "Mid level", senior: "Senior" };
  const level = experienceLevel !== undefined ? levels[experienceLevel || ""] : title.match(/\b(principal|staff|senior|junior|entry[ -]level|intern|internship|mid[ -]level)\b/i)?.[0];
  if (level) {
    facts.push({ key: "experience", label: "Experience level", value: level[0].toUpperCase() + level.slice(1).toLowerCase() });
  }
  const doc = new DOMParser().parseFromString(sanitizedHtml, "text/html");
  let required = false;
  for (const element of Array.from(doc.body.querySelectorAll("h1,h2,h3,h4,h5,h6,p,li"))) {
    if (/^H[1-6]$/.test(element.tagName)) {
      required = element.closest("section[data-section]")?.getAttribute("data-section") === "requirements";
      continue;
    }
    const text = element.textContent?.replace(/\s+/g, " ").trim() ?? "";
    // Keep the whole requirement, including alternatives such as equivalent work experience.
    if (required && text.length <= 200 && /\b(?:bachelor|master|ph\.?d|doctorate|bsc|msc)/i.test(text)
      && !/\b(?:prefer(?:red|ably)?|nice to have|bonus|not required)\b/i.test(text)) {
      facts.push({ key: "education", label: "Education", value: text });
      break;
    }
  }
  return facts;
}
