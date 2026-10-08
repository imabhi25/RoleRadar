/**
 * Shared compensation display. Never invents a range: a min that equals the max is one figure, and malformed
 * or missing values produce nothing.
 */

const SYMBOLS: Record<string, string> = { USD: "$", CAD: "CA$", GBP: "£", EUR: "€", AUD: "A$" };

export type Period = "year" | "month" | "week" | "day" | "hour" | "";

/** The period the SOURCE named, or "" when it named none. A missing period is never guessed from the amount. */
export function periodOf(text?: string | null): Period {
  const t = String(text ?? "");
  if (/year|annual|\byr\b|\bp\.?a\.?\b/i.test(t)) return "year";
  if (/month|\bmo\b/i.test(t)) return "month";
  if (/week|\bwk\b/i.test(t)) return "week";
  if (/\bday\b|daily/i.test(t)) return "day";
  if (/hour|\bhr\b/i.test(t)) return "hour";
  return "";
}

// Mirrors ingestion/pay_rules.py and the jobber_pay_ranges SQL function (parity: tests/fixtures/pay_rules.json).
const FLOOR: Record<string, number> = { year: 1000, month: 100, week: 25, day: 5, hour: 5, "": 5 };
const CEILING: Record<string, number> = { year: 3_000_000, month: 250_000, week: 60_000, day: 12_000, hour: 1_500, "": 3_000_000 };
const MAX_SPREAD = 10;
const PLACEHOLDER_AT_MOST = 10;

/**
 * Why a range cannot be shown as pay, or null when it is believable. Published figures are never edited: a placeholder
 * ($1 – $2), an amount no pay period reaches ($179,300,152 a year), a period that contradicts the amount ("annual $38"),
 * or a range whose top is over 10x its bottom is hidden, not corrected.
 */
export function payRangeProblem(min: number | null | undefined, max: number | null | undefined, currency = "", period: Period = ""): string | null {
  const values = [min, max].filter((n): n is number => typeof n === "number" && Number.isFinite(n) && n > 0);
  if (!values.length) return "no_amount";
  if (typeof min === "number" && typeof max === "number" && min > 0 && max > 0 && min > max) return "inverted";
  if (currency && !Object.hasOwn(SYMBOLS, currency.toUpperCase())) return null;
  const low = Math.min(...values);
  const high = Math.max(...values);
  if (low < FLOOR[period]) return high <= PLACEHOLDER_AT_MOST ? "placeholder" : "below_floor";
  if (high > CEILING[period]) return "above_ceiling";
  if (values.length === 2 && high / low > MAX_SPREAD) return "extreme_spread";
  return null;
}

/** Reject clearly invalid pay strings without rewriting the employer's words or guessing missing units. */
export function isPlausibleCompensationText(text: string): boolean {
  // Only evaluate the pay portion: a small cash benefit or an equity percentage is not base pay.
  const pay = text.split(/\s*[•·]\s*|\s+(?:\+|plus|and)\s+(?=(?:offers?\s+)?(?:equity|stock|rsus?|bonus|sign[- ]on))/i)[0];
  const amount = (number: string, unit: string) => Number(number.replace(/,/g, "")) * (/m/i.test(unit || "") ? 1_000_000 : /k/i.test(unit || "") ? 1000 : 1);
  const amounts = [...pay.matchAll(/(?:\b(USD|CAD|GBP|EUR|AUD)|((?:CA|A|US)?\$|£|€))\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?(?![\w.])/g)];
  // Some sources put the currency after a range, e.g. "1 – 2 CAD".
  const trailingCurrency = pay.match(/\b(USD|CAD|GBP|EUR|AUD)\b/i)?.[1];
  let values: number[] = [];
  let currency = trailingCurrency || "";
  if (amounts.length) {
    values = amounts.map((m) => amount(m[3], m[4]));
    currency = amounts[0][1] || (amounts[0][2] === "£" ? "GBP" : amounts[0][2] === "€" ? "EUR" : trailingCurrency || "USD");
  } else if (trailingCurrency) {
    const range = new RegExp(RANGE.source).exec(pay);
    if (range) values = [amount(range[2], range[3]), amount(range[5], range[6])];
  }
  if (!values.length) return true;
  return payRangeProblem(Math.min(...values), Math.max(...values), currency, periodOf(pay)) === null;
}

function money(value: number, currency: string, compactK: boolean): string {
  const prefix = currency ? (SYMBOLS[currency.toUpperCase()] ?? `${currency.toUpperCase()} `) : "";
  const amount = compactK ? `${Math.round(value / 1000)}K` : Math.round(value).toLocaleString("en-US");
  return `${prefix}${amount}`;
}

/**
 * min < max -> "CA$150K – CA$190K"; min === max -> "CA$191,100"; one bound -> "From X" / "Up to X".
 * Returns null when neither bound is a positive finite number, or the bounds are inverted.
 */
export function formatCompensationRange(min?: number | null, max?: number | null, currency = ""): string | null {
  const valid = (n?: number | null): n is number => typeof n === "number" && Number.isFinite(n) && n > 0;
  const lo = valid(min) ? min : null;
  const hi = valid(max) ? max : null;
  if (lo === null && hi === null) return null;
  if (lo !== null && hi !== null) {
    if (lo === hi) return money(lo, currency, false);
    if (lo > hi) return null;
    const compactK = lo % 1000 === 0 && hi % 1000 === 0;
    return `${money(lo, currency, compactK)} – ${money(hi, currency, compactK)}`;
  }
  return lo !== null ? `From ${money(lo, currency, false)}` : `Up to ${money(hi as number, currency, false)}`;
}

const AMOUNT = String.raw`((?:[A-Za-z]{1,3}\$|[$£€]|[A-Z]{3}\s?)?)(\d[\d,]*(?:\.\d+)?)(\s?[kKmM])?`;
const RANGE = new RegExp(String.raw`(?<![\w$£€])${AMOUNT}\s*[–—-]\s*${AMOUNT}(?![\w.])`, "g");

/**
 * Collapses "CA$191,100 – CA$191,100" to "CA$191,100" inside a source compensation summary. Genuine ranges,
 * and every other word of the summary, are left exactly as written.
 */
export function collapseRepeatedRange(text: string): string {
  return text.replace(RANGE, (whole, p1: string, n1: string, u1: string | undefined, p2: string, n2: string, u2: string | undefined) => {
    const same =
      n1.replace(/,/g, "") === n2.replace(/,/g, "") &&
      (u1 || "").trim().toLowerCase() === (u2 || "").trim().toLowerCase() &&
      (p1.trim() === p2.trim() || p1.trim() === "" || p2.trim() === "");
    return same ? `${p1 || p2}${n1}${u1 || ""}` : whole;
  });
}

const SUFFIX: Record<string, string> = { year: "/yr", hour: "/hr", month: "/mo", week: "/wk", day: "/day" };
const PERIOD_NOT_STATED = "period not stated";

/** Whether an amount is exactly representable in compact form (151200 -> 151.2K) without rounding away any digits. */
function isCompactExact(value: number): boolean {
  if (value < 1000) return true;
  const thousands = value / 1000;
  return Math.abs(thousands - Math.round(thousands * 10) / 10) < 1e-9;
}

/** Compact amount: 151200 -> "151.2K", 189000 -> "189K", 60 -> "60"; full digits (12,345) when compact would drop any. */
function compactAmount(value: number, compact = isCompactExact(value)): string {
  if (value >= 1_000_000) return `${Math.round(value / 10_000) / 100}M`;
  if (value < 1000) return String(Math.round(value * 100) / 100);
  return compact ? `${Math.round((value / 1000) * 10) / 10}K` : Math.round(value).toLocaleString("en-US");
}

interface PayInput { min?: number | null; max?: number | null; currency?: string; symbol?: string; interval?: string; qualifier?: string; scope?: string; label?: string; kind?: string }

function payPrefix(currency = "", symbol = ""): string {
  if (currency) return SYMBOLS[currency.toUpperCase()] ?? `${currency.toUpperCase()} `;
  return symbol;
}

/**
 * The one pay format used by job cards, the detail pane and company rows: `CA$151.2K – CA$189K/yr`, `$60/hr`.
 * A period is shown only when the source stated one. It is never inferred from the size of the amount: a bare `$230K` is
 * shown as published, and a small bare figure (`$60`) carries "(period not stated)" so it cannot be read as pay per year.
 * Placeholder, impossible and self-contradictory ranges return null (see payRangeProblem).
 */
export function formatPay(min?: number | null, max?: number | null, currency = "", interval = "", symbol = ""): string | null {
  const valid = (n?: number | null): n is number => typeof n === "number" && Number.isFinite(n) && n > 0;
  const lo = valid(min) ? min : null;
  const hi = valid(max) ? max : null;
  if (lo === null && hi === null) return null;
  if (lo !== null && hi !== null && lo > hi) return null;
  const top = hi ?? (lo as number);
  const period = periodOf(interval);
  if (payRangeProblem(lo ?? top, top, currency, period) !== null) return null;
  const prefix = payPrefix(currency, symbol);
  // Both ends of a range use the same style: "$113,645 – $191,000", never "$113,645 – $191K".
  const compact = [lo, hi].filter((n): n is number => n !== null).every(isCompactExact);
  const fmt = (n: number) => `${prefix}${compactAmount(n, compact)}`;
  const suffix = period ? SUFFIX[period] : top < 1000 ? ` (${PERIOD_NOT_STATED})` : "";
  if (lo !== null && hi !== null) return `${lo === hi ? fmt(lo) : `${fmt(lo)} – ${fmt(hi)}`}${suffix}`;
  return `${lo !== null ? "From " : "Up to "}${fmt(top)}${suffix}`;
}

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" ? v : v == null || v === "" ? NaN : Number(v));

/** Ranges stated in the posting text (stored by ingestion with source "posting_text"), each with its own currency and period. */
function textRanges(compensation: Dict): PayInput[] {
  if (compensation.source !== "posting_text" || !Array.isArray(compensation.ranges)) return [];
  return compensation.ranges
    .filter((r): r is Dict => Boolean(r) && typeof r === "object")
    .map((r) => ({
      min: num(r.min), max: num(r.max), currency: String(r.currency || ""), symbol: String(r.symbol || ""), interval: String(r.interval || ""),
      qualifier: r.qualifier ? String(r.qualifier) : "", scope: r.scope ? String(r.scope) : "", label: r.label ? String(r.label) : "", kind: r.kind ? String(r.kind) : "",
    }))
    .filter((r) => payRangeProblem(r.min, r.max, r.currency, periodOf(r.interval)) === null);
}

interface CardPay { text: string; periodMissing: boolean; ranges: PayInput[] }

/** A range the posting wrote for a place is this job's pay on a card only when its place covers every location of the job. */
const coversTheJob = (r: PayInput) => !r.qualifier || r.scope === "all";
const PAY_BY_LOCATION = "Pay varies by location";

function resolveCardPay(compensation?: Record<string, unknown> | null): CardPay | null {
  if (!compensation || typeof compensation !== "object") return null;
  // Ingestion marked the published figures unusable (placeholder, impossible, contradictory): the numbers stay stored, never shown.
  if (compensation.validation) return null;

  const summaryComps = compensation.summaryComponents;
  if (Array.isArray(summaryComps) && summaryComps.length > 0) {
    const components = summaryComps.filter((c): c is Record<string, unknown> => Boolean(c) && typeof c === "object");
    // Prefer identified pay over untyped benefits, and skip components without a usable range.
    const salaries = components.filter((c) => /^(?:Salary|BaseSalary|Hourly|Wage)$/i.test(String(c.compensationType)));
    const untyped = components.filter((c) => !c.compensationType);
    for (const salaryComp of [...salaries, ...untyped]) {
      const interval = String(salaryComp.interval || "");
      const text = formatPay(num(salaryComp.minValue), num(salaryComp.maxValue), String(salaryComp.currencyCode || ""), interval);
      if (text) return { text, periodMissing: !periodOf(interval), ranges: [] };
    }
  }

  const everyStated = textRanges(compensation);
  const stated = everyStated.filter(coversTheJob);
  // Pay written only for places that are not (all of) this job's locations: no number on the card, the pane lists it with its place.
  if (everyStated.length && !stated.length) return { text: PAY_BY_LOCATION, periodMissing: everyStated.some((r) => !periodOf(r.interval)), ranges: everyStated };
  if (stated.length) {
    const groups = new Set(stated.map((r) => `${r.currency || r.symbol}|${periodOf(r.interval)}`));
    const periodMissing = stated.some((r) => !periodOf(r.interval));
    // Different currencies or periods are never blended into one span, nor are several bare "$" ranges (US vs Canada).
    if (stated.length > 1 && (groups.size > 1 || !stated.every((r) => r.currency) || new Set(stated.map((r) => r.qualifier)).size > 1)) {
      return { text: "Multiple pay ranges", periodMissing, ranges: everyStated };
    }
    const text = formatPay(Math.min(...stated.map((r) => r.min as number)), Math.max(...stated.map((r) => r.max as number)), stated[0].currency, stated[0].interval, stated[0].symbol);
    // On-target earnings (base plus commission or bonus target) are never presented as plain base pay.
    const ote = stated.every((r) => r.kind === "ote");
    return text ? { text: ote ? `${text} OTE` : text, periodMissing, ranges: everyStated } : null;
  }

  // Greenhouse / Lever shape.
  if (compensation.min != null || compensation.max != null) {
    const interval = String(compensation.interval || "");
    const text = formatPay(num(compensation.min), num(compensation.max), String(compensation.currency || ""), interval, String(compensation.symbol || ""));
    // A structured range that failed the pay rules must not resurface through its own summary text.
    return text ? { text, periodMissing: !periodOf(interval), ranges: [] } : null;
  }

  for (const key of ["compensationTierSummary", "scrapeableCompensationSalarySummary"] as const) {
    const value = compensation[key];
    if (typeof value === "string" && value.trim()) {
      const text = salarySummary(value);
      // The source's own words are shown as written, so there is nothing to annotate.
      if (text) return { text, periodMissing: false, ranges: [] };
    }
  }
  return null;
}

/** Employer pay from any ATS shape (Ashby components, Greenhouse/Lever {min,max,currency,interval}, posting-text ranges) as one string. */
export function getJobCardCompensation(compensation?: Record<string, unknown> | null): string | null {
  return resolveCardPay(compensation)?.text ?? null;
}

/**
 * The detail-pane pay value: the card string, expanded to every stated range when the posting gave several (US/Canada,
 * Level 4/5), and flagged when the source gave no period.
 */
export function getCompensationDetail(compensation?: Record<string, unknown> | null): string | null {
  const card = resolveCardPay(compensation);
  if (!card) return null;
  const withoutNote = (text: string) => text.replace(` (${PERIOD_NOT_STATED})`, "");
  let body = withoutNote(card.text);
  if (card.ranges.length > 1 || card.ranges.some((r) => r.qualifier)) {
    // Every stated range, each with the level and place the employer wrote for it.
    body = card.ranges
      .map((range) => {
        const text = formatPay(range.min, range.max, range.currency, range.interval, range.symbol);
        const words = [range.label, range.qualifier, range.kind === "ote" ? "(on-target earnings)" : ""].filter(Boolean).join(" ");
        return text ? `${withoutNote(text)}${words ? ` ${words}` : ""}` : "";
      })
      .filter(Boolean)
      .join(" · ");
  }
  return card.periodMissing ? `${body} · ${PERIOD_NOT_STATED}` : body;
}

/** Non-pay parts of a source summary ("Offers Equity", "Plus up to 20% bonus", "Multiple ranges"), without repeating the pay. */
export function getCompensationExtras(compensation?: Record<string, unknown> | null): string {
  const text = compensation && typeof compensation.compensationTierSummary === "string" ? compensation.compensationTierSummary : "";
  const detailListsRanges = compensation?.source === "posting_text" && Array.isArray(compensation.ranges) && compensation.ranges.length > 1;
  return text
    .split(/\s*[•·]\s*/)
    .map((part) => part.trim())
    .filter((part) => part && !(/\d/.test(part) && /(?:[$£€]|\b(?:USD|CAD|GBP|EUR|AUD)\b)/.test(part)) && !(detailListsRanges && part === "Multiple ranges"))
    .join(" · ");
}

function salarySummary(value: string): string | null {
  const salary = collapseRepeatedRange(value.trim()).split(/\s*[•·]\s*|\s+(?:\+|plus|and)\s+(?=(?:offers?\s+)?(?:equity|stock|rsus?|bonus|sign[- ]on))/i)[0].trim();
  if (!/\d/.test(salary) || /^(?:offers?\s+)?(?:equity|stock|rsus?|bonus)\b/i.test(salary) || (salary.includes("%") && !/[$£€]|\b(?:USD|CAD|GBP|EUR|AUD)\b/.test(salary))) return null;
  return salary && isPlausibleCompensationText(salary) ? salary : null;
}
