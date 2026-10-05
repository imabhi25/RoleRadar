/**
 * Language handling for employer-provided descriptions (English, French and bilingual French/English postings).
 *
 * Nothing here translates. It only decides, from the text itself, whether a description is
 *   - English or French (single language), or
 *   - bilingual: one French run and one English run written by the employer, back to back.
 * and, for bilingual ones, splits the sanitized HTML into per-language views. Splitting is deliberately
 * conservative: when the structure is not clear (interleaved languages, a lopsided "English" tail, a language
 * requirement that only the French half states) nothing is separated and the description stays whole.
 * Shared and unpaired material is never dropped: it appears in every view.
 */

import {
  checkUnit,
  cognateOverlap,
  extractFacts,
  MIN_RUN_OVERLAP,
  MIN_SHORT_UNIT_OVERLAP,
  MIN_UNIT_OVERLAP,
  MIN_WORDS_FOR_OVERLAP,
  UNIT_OVERLAP_WORDS,
} from "./descriptionCorrespondence";

export type Lang = "en" | "fr";
export type DescriptionView = Lang | "original";

const FR_WORDS = new Set(
  ("le la les des du de un une et est sont pour avec dans nous vous votre vos notre nos qui que au aux ou ce cette ces sur chez afin " +
    "ainsi être aussi leur leurs ses mais donc comme tout toute tous elle ils elles où dont lors entre sans sous vers cadre pouvez serez aurez ferez")
    .split(" ")
);
const EN_WORDS = new Set(
  "the and of to in for with you we our is are will be your that this as on at by or from have has an it their they can who what which not if all more into about through".split(" ")
);

const WORD = /[a-zA-Zàâäçéèêëîïôöùûüÿœæ’']+/g;

export interface LangScore {
  fr: number;
  en: number;
}

export function scoreText(text: string): LangScore {
  let fr = 0;
  let en = 0;
  for (const raw of text.toLowerCase().match(WORD) ?? []) {
    const w = raw.replace(/’/g, "'");
    // French elisions ("l'équipe", "d'un", "qu'il") are a strong, unambiguous signal.
    if (/^(?:l|d|j|n|qu|s|c)'[a-zàâçéèêëîïôùûü]/.test(w)) fr += 1;
    const bare = w.replace(/^.*'/, "");
    if (FR_WORDS.has(bare)) fr += 1;
    else if (EN_WORDS.has(bare)) en += 1;
    if (/[àâçéèêëîïôùûœ]/.test(w)) fr += 0.5;
  }
  return { fr, en };
}

/** "fr" / "en" when the block is clearly one language; null for short, numeric or mixed text. */
export function classifyText(text: string): Lang | null {
  const { fr, en } = scoreText(text);
  if (fr + en < 3) return null;
  if (fr >= en * 2) return "fr";
  if (en >= fr * 2) return "en";
  return null;
}

const SEPARATOR_TEXT = /^[\s\-–—_=*~•·.]{3,}$/;
const LANGUAGE_MARKER =
  /^(?:english\s+(?:will\s+follow|version\s+(?:follows?|below)|to\s+follow)|french\s+(?:will\s+follow|version\s+(?:follows?|below))|(?:la\s+)?version\s+fran[cç]aise\s+(?:suit|ci-dessous)|(?:la\s+)?version\s+anglaise\s+(?:suit|ci-dessous)|fran[cç]ais\s+[àa]\s+suivre|anglais\s+[àa]\s+suivre)\.?$/i;

const CONTAINER = new Set(["DIV", "SECTION", "ARTICLE", "MAIN"]);

function plain(el: Node): string {
  return (el.textContent || "").replace(/[\s\u00a0]+/g, " ").trim();
}

function isSeparator(node: Node): boolean {
  if (node.nodeType === 1 && (node as Element).tagName === "HR") return true;
  const t = plain(node);
  return t !== "" && SEPARATOR_TEXT.test(t);
}

function isLanguageMarker(node: Node): boolean {
  return LANGUAGE_MARKER.test(plain(node));
}

function isHeadingNode(node: Node): boolean {
  if (node.nodeType !== 1) return false;
  const el = node as Element;
  if (/^H[1-6]$/.test(el.tagName)) return true;
  if (el.tagName !== "P" || el.children.length !== 1 || !/^(STRONG|B)$/.test(el.children[0].tagName)) return false;
  const t = plain(el);
  return t.length > 0 && t.length <= 80 && plain(el.children[0]) === t;
}

export interface LanguageAnalysis {
  /** Language of a description that is entirely one language (null: unknown, mixed or bilingual). */
  single: Lang | null;
  /** Both employer-written halves were found and can be shown separately. */
  bilingual: boolean;
  /** Views offered to the reader, in display order ("original" only when a split exists). */
  views: DescriptionView[];
  /** HTML for each view; always includes "original". */
  html: Record<DescriptionView, string>;
  /** Why a mixed-language description was NOT split (the complete original is then the only view). */
  fallbackReason?: string;
}

function topLevelRoot(doc: Document): Element {
  let root: Element = doc.body;
  while (root.children.length === 1 && CONTAINER.has(root.children[0].tagName) && root.childNodes.length === 1) root = root.children[0];
  return root;
}

function serialize(doc: Document, nodes: Node[]): string {
  const holder = doc.createElement("div");
  nodes.forEach((n) => holder.appendChild(n.cloneNode(true)));
  return holder.innerHTML.trim();
}

const isRuleText = (text: string) => {
  const t = text.replace(/[\s\u00a0]+/g, " ").trim();
  return t !== "" && SEPARATOR_TEXT.test(t);
};

/** A short line without sentence punctuation that introduces what follows ("Key job responsibilities"). */
function isHeadingLine(text: string): boolean {
  const t = text.replace(/[\s\u00a0]+/g, " ").trim();
  return t.length > 0 && t.length <= 70 && t.split(" ").length <= 8 && !/[.!?;]$/.test(t) && !/^[-•*–]\s/.test(t);
}

/**
 * Bilingual postings (Amazon) put a rule INSIDE one paragraph or list: "...texte français<br>-------<br>English
 * text..." or <li>----</li>. Split those at the rule so each half can be classified on its own. Lines stay in order;
 * single line breaks stay inside their paragraph, a blank line starts a new one, and a short heading-like first line
 * becomes its own paragraph (so it is never swallowed by the language of the lines under it). Only the rule itself
 * becomes a separate node.
 */
export function splitParagraphsAtRules(doc: Document, root: Element): void {
  Array.from(root.children).forEach((el) => {
    if (el.tagName === "UL" || el.tagName === "OL") {
      const items = Array.from(el.children);
      if (!items.some((li) => li.tagName === "LI" && isRuleText(li.textContent || ""))) return;
      const out: Element[] = [];
      let list: Element | null = null;
      items.forEach((li) => {
        if (li.tagName === "LI" && isRuleText(li.textContent || "")) {
          list = null;
          out.push(doc.createElement("hr"));
        } else {
          if (!list) {
            list = doc.createElement(el.tagName.toLowerCase());
            out.push(list);
          }
          list.appendChild(li);
        }
      });
      el.replaceWith(...out);
      return;
    }
    if (el.tagName !== "P" || !el.querySelector("br")) return;
    const lines: Node[][] = [[]];
    el.childNodes.forEach((n) => {
      if (n.nodeType === 1 && (n as Element).tagName === "BR") lines.push([]);
      else lines[lines.length - 1].push(n);
    });
    const textOf = (line: Node[]) => line.map((n) => n.textContent || "").join("");
    if (!lines.some((l) => isRuleText(textOf(l)))) return;
    const out: Element[] = [];
    let group: Node[][] = [];
    const flush = () => {
      if (group.length === 0) return;
      const make = (ls: Node[][]) => {
        const p = doc.createElement("p");
        ls.forEach((line, i) => {
          if (i > 0) p.appendChild(doc.createElement("br"));
          line.forEach((n) => p.appendChild(n));
        });
        return p;
      };
      if (group.length > 1 && isHeadingLine(textOf(group[0]))) {
        out.push(make([group[0]]));
        out.push(make(group.slice(1)));
      } else out.push(make(group));
      group = [];
    };
    lines.forEach((line) => {
      const text = textOf(line);
      if (isRuleText(text)) {
        flush();
        out.push(doc.createElement("hr"));
      } else if (text.replace(/[\s\u00a0]+/g, "") === "") flush();
      else group.push(line);
    });
    flush();
    el.replaceWith(...out);
  });
}

/** A French-only requirement ("bilingue", "maîtrise du français") that the English half does not repeat. */
const FRENCH_REQUIREMENT =
  /\b(?:bilingue|bilinguisme|ma[iî]trise\s+(?:du|de\s+la\s+langue)\s+fran[cç]ais|fran[cç]ais\s+(?:et|ou|\/)\s+anglais|anglais\s+(?:et|ou|\/)\s+fran[cç]ais|courant\s+en\s+fran[cç]ais)\b/i;
const ENGLISH_LANGUAGE_MENTION = /\b(?:bilingual|bilingualism|french|fran[cç]ais)\b/i;

const FR_HEADING = /[àâçéèêëîïôùûœ]|\b(?:propos|poste|equipe|exigences?|minimales?|comp[eé]tences|souhait[eé]es?|avantages|r[eé]mun[eé]ration|salaire|qui\s+sommes|nous|notre|vos?|votre|programme|stages?|description|pr[eé]sentation|profil|qualifications\s+(?:requises|exig[eé]es))\b/i;
const EN_HEADING = /\b(?:about|responsibilities|requirements?|qualifications?|overview|benefits|compensation|skills|summary|position|role|team|what|who|how|why|our|the|you|your|we|minimum|preferred|basic|additional|description|program|internship)\b/i;

function headingLanguage(node: Node): Lang | null {
  const t = plain(node);
  if (FR_HEADING.test(t)) return "fr";
  if (EN_HEADING.test(t)) return "en";
  return null;
}

interface Run {
  lang: Lang;
  nodes: number[];
  length: number;
  paired: boolean;
}

function linksOf(node: Node): string[] {
  if (node.nodeType !== 1) return [];
  const el = node as Element;
  const own = el.tagName === "A" && el.getAttribute("href") ? [el.getAttribute("href")!.trim().toLowerCase()] : [];
  return own.concat(Array.from(el.querySelectorAll("a[href]")).map((a) => a.getAttribute("href")!.trim().toLowerCase()));
}

interface Atom {
  /** node index, or "node:item" for one list item */
  key: string;
  text: string;
  links: string[];
}

/** The smallest pieces that can be matched across languages: a paragraph/line block, or one list item. */
function atomsOf(nodes: Node[], index: number): Atom[] {
  const node = nodes[index];
  const clean = (text: string) => text.replace(/[\s\u00a0]+/g, " ").trim();
  if (node.nodeType === 1 && /^(UL|OL)$/.test((node as Element).tagName)) {
    return Array.from((node as Element).children)
      .map((li, j) => ({ key: `${index}:${j}`, text: clean(li.textContent || ""), links: linksOf(li) }))
      .filter((a) => a.text !== "");
  }
  return [{ key: String(index), text: clean(node.textContent || ""), links: linksOf(node) }];
}

/** Can this French atom and this English atom be shown to say the same thing? Returns a score, or null. */
function matchScore(f: Atom, e: Atom): number | null {
  if (checkUnit({ fr: f.text, en: e.text, frLinks: f.links, enLinks: e.links }) !== null) return null;
  const o = cognateOverlap(f.text, e.text);
  const hasFact = extractFacts(f.text).length > 0;
  const words = Math.min(o.frWords, o.enWords);
  const weakest = Math.min(o.fr, o.en);
  const supported = words >= UNIT_OVERLAP_WORDS ? weakest >= MIN_UNIT_OVERLAP : words >= 1 ? weakest >= MIN_SHORT_UNIT_OVERLAP || hasFact : hasFact;
  return supported ? 1 + weakest + (hasFact ? 0.25 : 0) : null;
}

interface Verdict {
  ok: boolean;
  reason?: string;
  /** atoms shown only in the OTHER language's view: a French atom with a verified English counterpart is left out of
   * the English view, and vice versa. Every unmatched atom stays in every view. */
  hideFromEn: Set<string>;
  hideFromFr: Set<string>;
}

/** Minimum share of the SHORTER half that must be matched; the longer half may carry unmatched extras. */
const MIN_SHORT_SIDE_COVERAGE = 0.8;
const MIN_LONG_SIDE_COVERAGE = 0.3;
/** Share of the labelled text that may sit in language pairs that could not be verified (they stay in every view). */
const MAX_UNVERIFIED_SHARE = 0.2;

/**
 * Align the atoms of a French run and an English run (monotone best-match alignment). An atom pair counts as a
 * translation only if it passes every unit check on its own. Atoms with no verified counterpart are NOT matched and
 * are therefore kept in every view. If too little of either half is matched, the runs are not shown to be translations
 * of each other and the caller must keep the original.
 */
function verifyPair(nodes: Node[], labels: Array<Lang | null>, a: Run, b: Run): Verdict {
  const fail = (reason: string): Verdict => ({ ok: false, reason, hideFromEn: new Set(), hideFromFr: new Set() });
  const fr = a.lang === "fr" ? a : b;
  const en = a.lang === "fr" ? b : a;
  const atomsFor = (run: Run, lang: Lang) => run.nodes.filter((i) => labels[i] === lang).flatMap((i) => atomsOf(nodes, i));
  const F = atomsFor(fr, "fr");
  const E = atomsFor(en, "en");
  if (F.length === 0 || E.length === 0) return fail("empty half");
  if (F.length * E.length > 250_000) return fail("too large to verify");

  const score: Array<Array<number | null>> = F.map((f) => E.map((e) => matchScore(f, e)));
  const dp: number[][] = Array.from({ length: F.length + 1 }, () => new Array<number>(E.length + 1).fill(0));
  for (let i = 1; i <= F.length; i += 1) {
    for (let j = 1; j <= E.length; j += 1) {
      const s = score[i - 1][j - 1];
      dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1], s === null ? 0 : dp[i - 1][j - 1] + s);
    }
  }
  const pairs: Array<[number, number]> = [];
  for (let i = F.length, j = E.length; i > 0 && j > 0; ) {
    const s = score[i - 1][j - 1];
    if (s !== null && dp[i][j] === dp[i - 1][j - 1] + s) {
      pairs.push([i - 1, j - 1]);
      i -= 1;
      j -= 1;
    } else if (dp[i][j] === dp[i - 1][j]) i -= 1;
    else j -= 1;
  }
  pairs.reverse();
  if (pairs.length === 0) return fail("no passage of one language is shown to match a passage of the other");

  const size = (atoms: Atom[], idx: number[]) => idx.reduce((n, i) => n + atoms[i].text.length, 0);
  const frCov = size(F, pairs.map((p) => p[0])) / size(F, F.map((_, i) => i));
  const enCov = size(E, pairs.map((p) => p[1])) / size(E, E.map((_, i) => i));
  const frShorter = size(F, F.map((_, i) => i)) <= size(E, E.map((_, i) => i));
  const shortCov = frShorter ? frCov : enCov;
  const longCov = frShorter ? enCov : frCov;
  if (shortCov < MIN_SHORT_SIDE_COVERAGE || longCov < MIN_LONG_SIDE_COVERAGE) {
    return fail(`only ${(frCov * 100).toFixed(0)}% of the French and ${(enCov * 100).toFixed(0)}% of the English text is matched`);
  }
  const matchedFr = pairs.map(([i]) => F[i].text).join(" ");
  const matchedEn = pairs.map(([, j]) => E[j].text).join(" ");
  const total = cognateOverlap(matchedFr, matchedEn);
  if (total.frWords < MIN_WORDS_FOR_OVERLAP || total.enWords < MIN_WORDS_FOR_OVERLAP) return fail("too little text to verify");
  if (total.fr < MIN_RUN_OVERLAP || total.en < MIN_RUN_OVERLAP) return fail(`low vocabulary overlap ${total.fr.toFixed(2)}/${total.en.toFixed(2)}`);
  return {
    ok: true,
    hideFromEn: new Set(pairs.map(([i]) => F[i].key)),
    hideFromFr: new Set(pairs.map(([, j]) => E[j].key)),
  };
}

const BLOCK_CHILD = /^(?:P|UL|OL|H[1-6]|DIV|TABLE|BLOCKQUOTE|SECTION)$/;

/**
 * A top-level <div>/<section> that only groups blocks (no text of its own) is layout, not content. Lift its children
 * into the parent so one language's half is seen as separate paragraphs and lists rather than one opaque block.
 * Order is kept; nothing is added or removed.
 */
function flattenLayoutWrappers(root: Element): void {
  for (let pass = 0; pass < 4; pass += 1) {
    let changed = false;
    Array.from(root.children).forEach((child) => {
      if (child.tagName !== "DIV" && child.tagName !== "SECTION") return;
      const nodes = Array.from(child.childNodes);
      const hasOwnText = nodes.some((n) => n.nodeType === 3 && (n.textContent || "").trim() !== "");
      const blocks = nodes.filter((n) => n.nodeType === 1 && BLOCK_CHILD.test((n as Element).tagName));
      if (hasOwnText || blocks.length === 0) return;
      child.replaceWith(...nodes);
      changed = true;
    });
    if (!changed) break;
  }
}

export function analyzeLanguage(html: string): LanguageAnalysis {
  const unchanged: LanguageAnalysis = { single: null, bilingual: false, views: [], html: { original: html, en: html, fr: html } };
  if (!html || typeof DOMParser === "undefined") return unchanged;
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  const root = topLevelRoot(doc);
  flattenLayoutWrappers(root);
  splitParagraphsAtRules(doc, root);
  const nodes = Array.from(root.childNodes).filter((n) => !(n.nodeType === 3 && !(n.textContent || "").trim()));
  if (nodes.length === 0) return unchanged;

  // 1. Label every block that is clearly French or English (headings/separators/markers carry no label).
  const labels: Array<Lang | null> = nodes.map((n) => (isSeparator(n) || isLanguageMarker(n) || isHeadingNode(n) ? null : classifyText(plain(n))));
  const lengthOf = (lang: Lang) => nodes.reduce((sum, n, i) => (labels[i] === lang ? sum + plain(n).length : sum), 0);
  const frLen = lengthOf("fr");
  const enLen = lengthOf("en");

  // 2. Maximal same-language runs. Adjacent French/English runs are only CANDIDATE translation pairs: language,
  // adjacency, a separator rule, heading position or similar length prove nothing. Each is verified below.
  const runs: Run[] = [];
  nodes.forEach((_, i) => {
    const l = labels[i];
    if (!l) return;
    const last = runs[runs.length - 1];
    if (last && last.lang === l) {
      last.nodes.push(i);
      last.length += plain(nodes[i]).length;
    } else runs.push({ lang: l, nodes: [i], length: plain(nodes[i]).length, paired: false });
  });
  const candidates: Array<[Run, Run]> = [];
  for (let k = 0; k + 1 < runs.length; k += 1) {
    const a = runs[k];
    const b = runs[k + 1];
    if (a.paired || b.lang === a.lang) continue;
    if (Math.min(a.length, b.length) >= 120) {
      a.paired = true;
      b.paired = true;
      candidates.push([a, b]);
      k += 1;
    }
  }
  if (candidates.length === 0) {
    // No second language of any size next to the first: a plain single-language description (or too unclear to split).
    if (frLen >= 3 * 40 && enLen < frLen * 0.1) return { ...unchanged, single: "fr" };
    if (enLen > 0 && frLen < enLen * 0.1) return { ...unchanged, single: "en" };
    return unchanged;
  }

  // 3. Verify every candidate pair. A pair that is not shown to be a translation is NOT separated: its passages stay in
  // every view. A little of that (short boilerplate such as a one-line legal notice in each language) is tolerated; but
  // when a substantial part of the posting mixes languages without proof, the posting as a whole is ambiguous and
  // NOTHING is separated: the complete original is the only view (no toggle).
  const hideFromEn = new Set<string>();
  const hideFromFr = new Set<string>();
  const spans: Array<[number, number]> = [];
  let unverifiedLength = 0;
  let firstFailure: string | undefined;
  for (const [x, y] of candidates) {
    const verdict = verifyPair(nodes, labels, x, y);
    if (!verdict.ok) {
      unverifiedLength += x.length + y.length;
      firstFailure ??= verdict.reason;
      continue;
    }
    verdict.hideFromEn.forEach((k) => hideFromEn.add(k));
    verdict.hideFromFr.forEach((k) => hideFromFr.add(k));
    spans.push([Math.min(x.nodes[0], y.nodes[0]), Math.max(x.nodes[x.nodes.length - 1], y.nodes[y.nodes.length - 1])]);
  }
  if (spans.length === 0) return { ...unchanged, fallbackReason: firstFailure };
  if (unverifiedLength > MAX_UNVERIFIED_SHARE * (frLen + enLen)) {
    return { ...unchanged, fallbackReason: `a substantial part of the posting mixes languages without proof of translation (${firstFailure})` };
  }

  // 4. Build the views. A view omits only the other language's atoms that have a verified counterpart in this view.
  // Everything else (unmatched French or English passages, shared lines, links, lists) stays, in source order.
  const headingLangs = nodes.map((n) => (isHeadingNode(n) ? headingLanguage(n) : null));
  const bilingualHeadings = headingLangs.includes("fr") && headingLangs.includes("en");
  const inVerifiedPair = (i: number) => spans.some(([from, to]) => i >= from && i <= to);
  const hidden = (view: Lang) => (view === "en" ? hideFromEn : hideFromFr);
  /** The node as it appears in the view, or null when every atom of it is hidden. */
  const render = (i: number, view: Lang): Node | null => {
    const n = nodes[i];
    const hide = hidden(view);
    if (n.nodeType === 1 && /^(UL|OL)$/.test((n as Element).tagName)) {
      const items = Array.from((n as Element).children);
      const kept = items.filter((_, j) => !hide.has(`${i}:${j}`));
      if (kept.length === items.length) return n;
      if (kept.length === 0) return null;
      const copy = n.cloneNode(false) as Element;
      kept.forEach((li) => copy.appendChild(li.cloneNode(true)));
      return copy;
    }
    return hide.has(String(i)) ? null : n;
  };
  const build = (view: Lang): Node[] => {
    const out: Node[] = [];
    nodes.forEach((n, i) => {
      if (isSeparator(n) || isLanguageMarker(n)) return;
      if (isHeadingNode(n)) {
        // Drop a heading of the other language only when everything under it vanished from this view too.
        if (bilingualHeadings && inVerifiedPair(i) && headingLangs[i] !== null && headingLangs[i] !== view) {
          let j = i + 1;
          let sawLabeled = false;
          let allGone = true;
          for (; j < nodes.length && !isHeadingNode(nodes[j]); j += 1) {
            if (labels[j] === null) continue;
            sawLabeled = true;
            if (render(j, view) !== null) allGone = false;
          }
          if (sawLabeled && allGone) return;
        }
        out.push(n);
        return;
      }
      if (labels[i] === null) {
        out.push(n);
        return;
      }
      const shown = render(i, view);
      if (shown) out.push(shown);
    });
    return out;
  };
  const enNodes = build("en");
  const frNodes = build("fr");
  const enText = enNodes.map(plain).join(" ");
  const frText = frNodes.map(plain).join(" ");
  // Language requirements must stay explicit in the English view.
  if (FRENCH_REQUIREMENT.test(frText) && !ENGLISH_LANGUAGE_MENTION.test(enText)) return { ...unchanged, fallbackReason: "French language requirement not repeated in English" };
  if (enText.length < 200 || frText.length < 200) return unchanged;
  // Last line of defence: no number, month, e-mail or link of the original may be missing from either view. This
  // backs up the verification above; it is not what establishes equivalence.
  const originalFacts = new Set(extractFacts(nodes.map(plain).join(" ")).map((f) => f.value));
  const originalLinks = new Set(nodes.flatMap((n) => linksOf(n)));
  for (const view of [enNodes, frNodes]) {
    const have = new Set(extractFacts(view.map(plain).join(" ")).map((f) => f.value));
    const haveLinks = new Set(view.flatMap((n) => linksOf(n)));
    if ([...originalFacts].some((v) => !have.has(v)) || [...originalLinks].some((l) => !haveLinks.has(l))) {
      return { ...unchanged, fallbackReason: "a number, date or link of the original would be missing from a view" };
    }
  }

  return {
    single: null,
    bilingual: true,
    views: ["en", "fr", "original"],
    html: { original: html, en: serialize(doc, enNodes), fr: serialize(doc, frNodes) },
  };
}
