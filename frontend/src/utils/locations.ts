import { cleanLocationDisplay } from "./formatters";

export interface LocationSource {
  location: string;
  country: string;
  locations?: { location: string; country: string; source_location?: string }[];
}

const REGION_PREFIX = /^(?:AMER|NAMER|NA|EMEA|APAC|LATAM|APJ)\s*[-–—:]\s*/i;
const WORK_MODES = ["Remote", "Hybrid", "On-site"];

/** "745 THURLOW ST", "1 Yonge Street", "200 Bay Ave.": a number, a name and a street-type word, nothing else. */
const STREET_ADDRESS =
  /^\d+[A-Za-z]?(?:-\d+)?\s+(?:[\p{L}0-9.'’-]+\s+){0,4}(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|way|lane|ln|hwy|highway|sq|square|pl|place|cres|crescent|ct|court|pkwy|parkway|terrace|trail)\.?(?:\s+(?:n|s|e|w|ne|nw|se|sw))?\.?$/iu;
const LOWER_WORDS = new Set(["of", "de", "la", "le", "du", "des", "and", "the"]);
const KEEP_UPPER = /^(?:[A-Z]{1,3}|N?[A-Z]{2}\d?)$/;
const COUNTRY_ALIASES = [
  { name: "Canada", aliases: ["canada", "ca", "can"] },
  { name: "United States", aliases: ["united states", "united states of america", "usa", "us"] },
  { name: "United Kingdom", aliases: ["united kingdom", "uk", "gb", "gbr"] },
];
const US_STATE_NAMES = new Set("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming".toLowerCase().split("|"));
const US_STATES = new Set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split(" "));

/** ALL-CAPS place names become Title Case ("TORONTO" -> "Toronto"); short codes like ON, BC, USA stay as they are. */
function smartCase(part: string): string {
  if (/^[A-Z]\d[A-Z]\s?\d[A-Z]\d$/i.test(part)) return part.toUpperCase();
  if (!/\p{L}/u.test(part) || part !== part.toUpperCase() || part === part.toLowerCase()) return part;
  if (part.length <= 3 && KEEP_UPPER.test(part)) return part;
  return part
    .toLowerCase()
    .split(/(\s+|-)/)
    .map((word, i) => {
      if (!word.trim() || word === "-") return word;
      if (i > 0 && LOWER_WORDS.has(word)) return word;
      return word.replace(/(^|['’])(\p{L})/gu, (_m, pre: string, ch: string) => pre + ch.toUpperCase());
    })
    .join("");
}

/**
 * Turns a raw source location label into a compact, readable one for display only, e.g.
 * "AMER - Canada - British Columbia - Remote" -> "Canada, British Columbia · Remote".
 * Clear street-address noise before a city is dropped ("745 THURLOW ST:VANCOUVER, Canada" -> "Vancouver, Canada")
 * and ALL-CAPS place names are title-cased. The stored location data is never changed.
 */
export function prettyLocationLabel(raw: string, country?: string): string {
  let text = (raw || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  text = text.replace(REGION_PREFIX, "");

  const modes: string[] = [];
  const stripMode = (mode: string, pattern: RegExp) => {
    if (pattern.test(text)) {
      modes.push(mode);
      text = text.replace(pattern, " ");
    }
  };
  // "- Remote", "(Remote)", "Remote -", ", Remote" and a bare "Remote"
  stripMode("Remote", /(?:^|[\s(,–—-])remote(?:[)\s,–—-]|$)/i);
  stripMode("Hybrid", /(?:^|[\s(,–—-])hybrid(?:[)\s,–—-]|$)/i);
  stripMode("On-site", /(?:^|[\s(,–—-])on[\s-]?site(?:[)\s,–—-]|$)/i);

  const rawParts = text
    .split(/\s+[-–—]\s+|\s*[,;:]\s*/)
    .map((p) => p.replace(/^[\s()–—-]+|[\s()–—-]+$/g, ""))
    .filter(Boolean);
  // A street address followed by a recognizable place ("745 THURLOW ST:VANCOUVER") shows the place only.
  // A lone address, or one with nothing after it, is kept as written rather than guessed at.
  const withoutStreets = rawParts.filter((p, i) => !(STREET_ADDRESS.test(p) && rawParts.slice(i + 1).some((q) => !STREET_ADDRESS.test(q))));
  let parts = (withoutStreets.length > 0 ? withoutStreets : rawParts).map(smartCase);
  // Only interpret a country code when the source supplies its country context or spells out the country.
  // CA is a Canadian country code here, but remains a California state code in a US posting.
  const identity = COUNTRY_ALIASES.find((entry) => entry.aliases.includes((country || "").trim().toLowerCase()))
    || COUNTRY_ALIASES.find((entry) => parts.some((part) => part.toLowerCase() === entry.name.toLowerCase()))
    || COUNTRY_ALIASES.find((entry) => entry.name === "United States" && /^(?:us|usa)$/i.test(parts[0] || ""));
  if (identity) {
    const indices = parts.flatMap((part, index) => identity.aliases.includes(part.toLowerCase()) ? [index] : []);
    if (indices.length > 1) {
      const preferred = parts.find((part) => part.toLowerCase() === identity.name.toLowerCase()) || parts[indices[0]];
      parts = parts.flatMap((part, index) => index === indices[0] ? [preferred] : indices.includes(index) ? [] : [part]);
    }
    // Country-first ATS labels use country, state, city. California's CA remains a state.
    if (identity.name === "United States" && identity.aliases.includes(parts[0]?.toLowerCase()) && parts.length > 1) {
      const places = parts.slice(1);
      parts = places.length === 2 && (US_STATES.has(places[0].toUpperCase()) || US_STATE_NAMES.has(places[0].toLowerCase()))
        ? [places[1], places[0], identity.name]
        : [...places, identity.name];
    }
    if (identity.name === "United States" && parts.length === 2 && US_STATES.has(parts[0].toUpperCase()) && identity.aliases.includes(parts[1].toLowerCase())) parts = [parts[0].toUpperCase(), identity.name];
    // Canada sources often append CA; keep existing readable US/UK abbreviations intact.
    if (identity.name === "Canada" && parts.length > 1 && identity.aliases.includes(parts.at(-1)!.toLowerCase())) parts[parts.length - 1] = identity.name;
  }
  // Amazon's San Francisco office identifier is not a geographic region. Preserve unfamiliar codes,
  // postal codes, street addresses and other cities rather than guessing their meaning.
  parts = parts.filter((part, index) => !(index > 0 && /^SF\d+$/i.test(part) && /^San Francisco$/i.test(parts[index - 1])));
  const place = parts.join(", ");
  const mode = WORK_MODES.filter((m) => modes.includes(m)).join(" / ");
  if (place && mode) return `${place} · ${mode}`;
  return place || mode || raw.trim();
}

/** "+1 location" / "+6 locations" */
export function formatExtraLocations(count: number): string {
  return `+${count} ${count === 1 ? "location" : "locations"}`;
}

/** Display-only postal formatting. Keep unit/postal codes and retain the complete address for maps. */
export function formatPostalAddress(raw: string, primaryLocation = ""): { label: string; full: string } {
  const parts = raw.replace(/\s+/g, " ").trim().split(/\s*[,;:]\s*/).filter(Boolean).map((part) => {
    if (part !== part.toUpperCase() || !/\p{L}/u.test(part)) return part;
    return part.split(/(\s+|-)/).map((word) => {
      // Direction/province codes, postal codes, unit numbers and known brand initials are meaningful.
      if (/\d/.test(word) || /^(?:N|S|E|W|NE|NW|SE|SW|ON|QC|BC|AB|MB|NB|NS|NL|NT|NU|PE|YT|USA|UK|RBC|BMO|TD|HSBC|IBM|TH)$/i.test(word)) return word;
      return word.toLowerCase().replace(/(^|['’])(\p{L})/gu, (_match, prefix: string, letter: string) => prefix + letter.toUpperCase());
    }).join("");
  });
  const fold = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^\p{L}\p{N}]/gu, "").toLowerCase();
  const city = primaryLocation.split(/[,·]/)[0].trim();
  // The city already appears above the address. Suppress only an exact trailing city match.
  const repeatsCity = parts.length > 1 && city && fold(parts.at(-1)!) === fold(city);
  return { full: parts.join(", "), label: (repeatsCity ? parts.slice(0, -1) : parts).join(", ") };
}

/**
 * Compact location model for cards and the detail header: a primary label plus every distinct
 * location (in source order). One requisition may have many; callers show `primary` and reveal `all`
 * on demand instead of printing a giant joined string.
 */
export function summarizeLocations(job: LocationSource): { primary: string; all: string[] } {
  const labels: string[] = [];
  const push = (value: string, country: string) => {
    for (const piece of value.split(" • ")) {
      const pretty = prettyLocationLabel(piece, country);
      if (pretty) labels.push(pretty);
    }
  };
  if (job.locations && job.locations.length > 0) {
    for (const loc of job.locations) {
      push(cleanLocationDisplay(loc.source_location || loc.location, loc.country, false).full, loc.country);
    }
  } else {
    push(cleanLocationDisplay(job.location, job.country, false).full, job.country);
  }
  const seen = new Set<string>();
  const all = labels.filter((label) => {
    const key = label.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return { primary: all[0] ?? "", all };
}
