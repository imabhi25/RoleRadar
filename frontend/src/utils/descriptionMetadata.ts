/**
 * Explicit "Label: value" metadata that some employers (Workday tenants in particular) put at the very top of a
 * description: "Application Deadline: 10/30/2026", "Address: 4100 Gordon Baker Road", "Job Family Group: Technology".
 *
 * Only confidently recognized label/value pairs are lifted out of the prose, so the header can show them in their own
 * place instead of as loose text. Anything ambiguous stays exactly where it was:
 * - a deadline only comes from a deadline LABEL ("Application Deadline", "Apply by", "Date limite de candidature")
 *   with a value that parses to one unambiguous calendar date. A start-date requirement ("start before December 1,
 *   2026") is never a deadline; numeric dates such as 03/04/2026 are not guessed;
 * - an address only counts when the value looks like a street address, never a bare city or country;
 * - if the same field appears more than once with different values (e.g. a French and an English copy that disagree)
 *   nothing is extracted for it.
 */

export interface DescriptionMetadata {
  /** Application deadline as an unambiguous ISO calendar date (YYYY-MM-DD). */
  deadline?: string;
  /** Employer-supplied street address, exactly as written. */
  address?: string;
  /** Employer-supplied job family / function group, exactly as written. */
  jobFamily?: string;
  workLocation?: string;
  hours?: string;
  businessLine?: string;
  /** Employer-named work term, exactly as written ("Winter/Term 2"). Never converted into a season or year. */
  workTerm?: string;
  compensation?: string;
  compensationNotesHtml?: string;
}

const CONTAINER = new Set(["DIV", "SECTION", "ARTICLE", "MAIN", "DL"]);

const fold = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[‘’]/g, "'")
    .toLowerCase();

const squash = (text: string) => text.replace(/[\s\u00a0]+/g, " ").trim();

type Field = Exclude<keyof DescriptionMetadata, "compensationNotesHtml">;

const LABELS: Array<[Field, RegExp]> = [
  ["workLocation", /^(?:work(?:ing)?\s+location|job\s+location|lieu\s+de\s+travail)$/],
  ["workTerm", /^(?:work\s+term|terme\s+de\s+travail)$/],
  ["hours", /^(?:hours|weekly\s+hours|hours\s+per\s+week|work(?:ing)?\s+hours|heures(?:\s+par\s+semaine|\s+de\s+travail)?)$/],
  ["businessLine", /^(?:line\s+of\s+business|business\s+(?:line|area|unit)|secteur\s+d'activite)$/],
  ["compensation", /^(?:pay\s+details|salary(?:\s+range)?|compensation(?:\s+range)?|base\s+(?:pay|salary)|salaire(?:\s+de\s+base)?)$/],
  [
    "deadline",
    /^(?:application\s+(?:deadline|closing\s+date|close\s+date|due\s+date)|closing\s+date|apply\s+by|date\s+limite(?:\s+(?:de\s+candidature|pour\s+postuler|de\s+depot))?|date\s+de\s+cloture(?:\s+des\s+candidatures)?)$/,
  ],
  ["address", /^(?:address|street\s+address|office\s+address|work\s+address|adresse(?:\s+(?:du\s+bureau|de\s+travail))?)$/],
  ["jobFamily", /^(?:job\s+family(?:\s+group)?|famille\s+d'emplois?|groupe\s+de\s+famille\s+d'emplois?)$/],
];

function fieldForLabel(text: string): Field | null {
  const t = fold(squash(text)).replace(/\s*[:：]\s*$/, "");
  for (const [field, pattern] of LABELS) if (pattern.test(t)) return field;
  return null;
}

const MONTHS: Record<string, number> = {
  january: 1, jan: 1, february: 2, feb: 2, march: 3, mar: 3, april: 4, apr: 4, may: 5, june: 6, jun: 6, july: 7, jul: 7,
  august: 8, aug: 8, september: 9, sep: 9, sept: 9, october: 10, oct: 10, november: 11, nov: 11, december: 12, dec: 12,
  janvier: 1, janv: 1, fevrier: 2, fevr: 2, mars: 3, avril: 4, avr: 4, mai: 5, juin: 6, juillet: 7, juil: 7, aout: 8,
  septembre: 9, octobre: 10, novembre: 11, decembre: 12,
};

function isoDate(year: number, month: number, day: number): string | null {
  if (year < 2000 || year > 2100 || month < 1 || month > 12 || day < 1 || day > 31) return null;
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** One unambiguous calendar date, or null. Day/month order is never guessed for numeric dates. */
export function parseUnambiguousDate(value: string): string | null {
  const t = fold(squash(value)).replace(/[.,]+$/, "");
  let m = t.match(/^(\d{4})-(\d{2})-(\d{2})(?:[t ].*)?$/);
  if (m) return isoDate(+m[1], +m[2], +m[3]);
  m = t.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})$/);
  if (m) return isoDate(+m[1], +m[2], +m[3]);
  m = t.match(/^([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$/);
  if (m && MONTHS[m[1]]) return isoDate(+m[3], MONTHS[m[1]], +m[2]);
  m = t.match(/^(\d{1,2})(?:er|st|nd|rd|th)?\s+(?:de\s+)?([a-z]+)\.?,?\s+(\d{4})$/);
  if (m && MONTHS[m[2]]) return isoDate(+m[3], MONTHS[m[2]], +m[1]);
  m = t.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/);
  if (m) {
    const a = +m[1];
    const b = +m[2];
    const year = +m[3];
    if (a === b) return isoDate(year, a, b);
    if (a > 12 && b <= 12) return isoDate(year, b, a); // day first
    if (b > 12 && a <= 12) return isoDate(year, a, b); // month first
  }
  return null; // 03/04/2026 and anything else: not guessed
}

const STREET_WORDS =
  /\b(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|place|pl|court|ct|crescent|cres|parkway|pkwy|highway|hwy|suite|ste|unit|floor|rue|chemin|boul|bureau)\b\.?/i;

/** A street address: a number plus street words, or a street word with a comma-separated locality. Not a bare city. */
export function looksLikeStreetAddress(value: string): boolean {
  const t = squash(value);
  if (t.length < 5 || t.length > 140 || /[.!?]\s+[A-Z]/.test(t)) return false;
  return /\d/.test(t) && STREET_WORDS.test(t);
}

interface Candidate {
  field: Field;
  nodes: Node[];
  value: string;
}

const isBlock = (n: Node): n is Element => n.nodeType === 1;

function textOf(n: Node): string {
  return squash(n.textContent || "");
}

/** Is this node the label half of a "Label:" / value pair? Returns the field when it is. */
function labelOnly(n: Node): Field | null {
  if (!isBlock(n) || !/^(?:P|DIV|H[1-6]|LI|DT|STRONG|B|SPAN)$/.test(n.tagName)) return null;
  const t = textOf(n);
  if (t.length === 0 || t.length > 50) return null;
  return fieldForLabel(t);
}

function topLevelRoot(doc: Document): Element {
  let root: Element = doc.body;
  while (root.children.length === 1 && CONTAINER.has(root.children[0].tagName) && root.childNodes.length === 1) root = root.children[0];
  return root;
}

export function extractMetadata(html: string): { html: string; meta: DescriptionMetadata } {
  const none = { html: html || "", meta: {} as DescriptionMetadata };
  if (!html || typeof DOMParser === "undefined") return none;
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  const root = topLevelRoot(doc);
  // Some ATS templates put label/value pairs in separate wrapper divs.
  const unwrap = (parent: Element) => {
    for (const child of Array.from(parent.children)) {
      if (!CONTAINER.has(child.tagName)) continue;
      unwrap(child);
      if (child.tagName === "DL" || child.querySelector("h1,h2,h3,h4,h5,h6") || (child.children.length === 1 && /^(?:P|DIV)$/.test(child.children[0].tagName))) {
        child.replaceWith(...Array.from(child.childNodes));
      }
    }
  };
  unwrap(root);
  const nodes = Array.from(root.childNodes).filter((n) => !(n.nodeType === 3 && !(n.textContent || "").trim()));
  const candidates: Candidate[] = [];

  for (let i = 0; i < nodes.length; i += 1) {
    const node = nodes[i];
    // Form A: a label-only block ("Address:") followed by a short value block / text.
    const field = labelOnly(node);
    if (field && i + 1 < nodes.length) {
      const next = nodes[i + 1];
      const value = textOf(next);
      if (value && value.length <= 160 && !labelOnly(next) && !(isBlock(next) && /^H[1-6]$/.test(next.tagName))) {
        candidates.push({ field, nodes: [node, next], value });
        i += 1;
        continue;
      }
    }
    // Form B: a bold label separated from its value by a line break, including templates without a colon.
    if (isBlock(node) && /^(?:P|DIV|LI|H[1-6])$/.test(node.tagName)) {
      const label = node.firstElementChild;
      const f = label && /^(?:STRONG|B|SPAN)$/.test(label.tagName) ? fieldForLabel(textOf(label)) : null;
      const children = Array.from(node.childNodes);
      const index = label ? children.indexOf(label) : -1;
      if (f && index >= 0 && children.slice(0, index).every((child) => !textOf(child))) {
        const value = children.slice(index + 1).map(textOf).join(" ").trim();
        if (value && value.length <= 160) { candidates.push({ field: f, nodes: [node], value }); continue; }
      }
    }
    // Form C: one block, "Application Deadline: 10/30/2026" (the colon is required here).
    if (isBlock(node) && /^(?:P|DIV|LI|H[1-6])$/.test(node.tagName)) {
      const t = textOf(node);
      const m = t.match(/^([^:：]{3,45})\s*[:：]\s*(.{2,160})$/);
      if (m) {
        const f = fieldForLabel(m[1]);
        if (f) candidates.push({ field: f, nodes: [node], value: m[2] });
      }
    }
  }

  const meta: DescriptionMetadata = {};
  const remove: Node[] = [];
  const take = (field: Field, accept: (value: string) => string | null, assign: (value: string) => void) => {
    const found = candidates.filter((c) => c.field === field);
    if (found.length === 0) return;
    const parsed = found.map((c) => accept(c.value));
    if (parsed.some((p) => p === null)) return; // one unrecognized value: leave every copy in the prose
    const distinct = new Set(parsed.map((p) => (p as string).toLowerCase()));
    if (distinct.size !== 1) return; // conflicting copies: ambiguous
    assign(parsed[0] as string);
    found.forEach((c) => remove.push(...c.nodes));
  };
  take("deadline", parseUnambiguousDate, (v) => (meta.deadline = v));
  take("address", (v) => (looksLikeStreetAddress(v) ? squash(v) : null), (v) => (meta.address = v));
  take("jobFamily", (v) => (squash(v).length >= 2 && squash(v).length <= 60 ? squash(v) : null), (v) => (meta.jobFamily = v));

  take("workLocation", (v) => v.length <= 140 && !/[.!?]\s/.test(v) ? squash(v) : null, (v) => (meta.workLocation = v));
  take("hours", (v) => /^(?:\d{1,3}(?:[.,]\d{1,2})?)(?:\s*(?:hours?|hrs?)(?:\s*(?:per|a|\/)\s*week)?)?$/i.test(v) && parseFloat(v.replace(",", ".")) > 0 && parseFloat(v.replace(",", ".")) <= 168 ? squash(v) : null, (v) => (meta.hours = v));
  take("workTerm", (v) => v.length <= 60 && !/[.!?]\s/.test(v) ? squash(v) : null, (v) => (meta.workTerm = v));
  take("businessLine", (v) => v.length <= 120 && !/[.!?]\s/.test(v) ? squash(v) : null, (v) => (meta.businessLine = v));
  // Extract only a compact monetary value, never pay-policy paragraphs or eligibility conditions.
  take("compensation", (v) => v.length <= 160 && /(?:[$€£]|\b(?:CAD|USD|EUR|GBP)\b)/i.test(v) && /\d/.test(v) && !/\b(?:depending|eligible|committed|equitable|experience|qualifications)\b/i.test(v) ? squash(v) : null, (v) => (meta.compensation = v));

  if (meta.compensation) {
    const notes: string[] = [];
    for (const candidate of candidates.filter((value) => value.field === "compensation")) {
      let next: Node | null = candidate.nodes.at(-1)?.nextSibling ?? null;
      while (next) {
        const following: Node | null = next.nextSibling;
        if (next.nodeType === 3 && !textOf(next)) { next = following; continue; }
        if (!isBlock(next) || !/^(?:P|DIV)$/.test(next.tagName) || labelOnly(next)) break;
        const value = textOf(next);
        if (!/\b(?:compensation|salary|pay|remuneration)\b/i.test(value) || /\b(?:you will|responsibilities|we are hiring|build)\b/i.test(value)) break;
        notes.push(next.outerHTML);
        remove.push(next);
        next = following;
      }
    }
    if (notes.length) meta.compensationNotesHtml = notes.join("");
  }

  if (remove.length === 0) return none;
  remove.forEach((n) => n.parentNode?.removeChild(n));
  return { html: doc.body.innerHTML.trim(), meta };
}
