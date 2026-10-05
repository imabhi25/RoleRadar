/**
 * Evidence that a French passage and an English passage of one description say the same thing.
 *
 * Nothing here translates. Language detection, adjacency, a separator rule or similar length are NOT evidence of
 * equivalence (a French paragraph about salary and office days can sit next to an unrelated English paragraph of the
 * same size). A split into per-language views is only safe when a pair of aligned passages passes ALL of:
 *
 *  1. Same structure: the same number of blocks, list items / lines, and links, in the same order.
 *  2. Same facts: every number, written number, month, currency amount, e-mail and URL in one passage is in the
 *     other, and numbers that carry a recognisable unit (days, weeks, years, ...) carry the same unit.
 *  3. Same shape: comparable length and sentence count.
 *  4. Real lexical overlap: a large enough share of content words in each passage has a cognate in the other
 *     (système/system, distribué/distributed). Unrelated text shares almost none; true translations share many.
 *
 * Any failure means "not shown to be a translation": the caller must then keep the complete original.
 */

const fold = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/œ/g, "oe")
    .replace(/æ/g, "ae")
    .toLowerCase();

// ---------------------------------------------------------------------------------------------------------------
// Facts: numbers, written numbers, months, units, links
// ---------------------------------------------------------------------------------------------------------------

const NUMBER_WORDS: Record<string, string> = {
  // English
  two: "2", three: "3", four: "4", five: "5", six: "6", seven: "7", eight: "8", nine: "9", ten: "10", eleven: "11",
  twelve: "12", fifteen: "15", twenty: "20", thirty: "30", forty: "40", fifty: "50", hundred: "100", thousand: "1000",
  // French
  deux: "2", trois: "3", quatre: "4", cinq: "5", sept: "7", huit: "8", neuf: "9", dix: "10", onze: "11", douze: "12",
  quinze: "15", vingt: "20", trente: "30", quarante: "40", cinquante: "50", cent: "100", mille: "1000",
};

const MONTHS: Record<string, string> = {
  january: "m1", janvier: "m1", february: "m2", fevrier: "m2", march: "m3", mars: "m3", april: "m4", avril: "m4", may: "m5",
  mai: "m5", june: "m6", juin: "m6", july: "m7", juillet: "m7", august: "m8", aout: "m8", september: "m9", septembre: "m9",
  october: "m10", octobre: "m10", november: "m11", novembre: "m11", december: "m12", decembre: "m12",
};

/** Unit classes (translation-equivalent words map to one class). Unknown units are simply not compared. */
const UNITS: Record<string, string> = {
  day: "day", days: "day", jour: "day", jours: "day", journee: "day", journees: "day",
  week: "week", weeks: "week", semaine: "week", semaines: "week",
  month: "month", months: "month", mois: "month",
  year: "year", years: "year", an: "year", ans: "year", annee: "year", annees: "year",
  hour: "hour", hours: "hour", heure: "hour", heures: "hour",
  percent: "pct", pourcent: "pct", pour: "pct",
  dollar: "cur", dollars: "cur", cad: "cur", usd: "cur", eur: "cur", euros: "cur", euro: "cur", cents: "cur",
  employee: "ppl", employees: "ppl", employes: "ppl", employe: "ppl",
};

export interface Fact {
  /** normalized value: "120000", "m10", "https://...", "a@b.c" */
  value: string;
  /** unit class when the number is followed by a recognised unit */
  unit?: string;
}

/**
 * "120 000", "120,000.00", "120.000,00", "1.5", "5" -> "120000", "120000", "120000", "1.5", "5".
 * One lone separator followed by exactly three digits is thousands grouping; otherwise the last separator is decimal.
 */
export function normalizeNumber(raw: string): string | null {
  const s = raw.replace(/[\s\u00a0\u202f']/g, "");
  if (!/^\d[\d.,]*$/.test(s) || /[.,]$/.test(s)) return null;
  const dots = (s.match(/\./g) ?? []).length;
  const commas = (s.match(/,/g) ?? []).length;
  let out = s;
  if (dots + commas > 0) {
    const last = Math.max(s.lastIndexOf("."), s.lastIndexOf(","));
    const tail = s.slice(last + 1);
    const lone = dots + commas === 1;
    const thousandsOnly = (dots === 0 || commas === 0) && !lone; // 1,234,567 or 1.234.567
    if (thousandsOnly || (lone && tail.length === 3)) out = s.replace(/[.,]/g, "");
    else out = `${s.slice(0, last).replace(/[.,]/g, "")}.${tail}`;
    out = out.replace(/\.0+$/, "");
  }
  return out.replace(/^0+(?=\d)/, "");
}

const NUMBER = String.raw`\d{1,3}(?:[\s\u00a0\u202f,.']\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?`;
const TOKEN = new RegExp(String.raw`https?:\/\/[^\s<>)"']+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|${NUMBER}|[a-zA-Z]+`, "g");

/** Facts in a text: numbers (digits or words), months, links and e-mails, in order, with units where recognised. */
export function extractFacts(text: string): Fact[] {
  const facts: Fact[] = [];
  const t = text.replace(/[\s\u00a0]+/g, " ");
  const matches = Array.from(t.matchAll(TOKEN));
  matches.forEach((m, index) => {
    const token = m[0];
    if (/^https?:/i.test(token)) {
      facts.push({ value: token.replace(/[.,;:]+$/, "").toLowerCase() });
      return;
    }
    if (/@/.test(token)) {
      facts.push({ value: token.toLowerCase() });
      return;
    }
    if (/^\d/.test(token)) {
      // "126,000.00 - 210,400.00" is two numbers; "120 000" is one. Split only on separators that are not grouping.
      const value = normalizeNumber(token);
      if (value === null) return;
      const next = matches[index + 1]?.[0];
      const unitWord = next && /^[a-z]+$/i.test(next) ? fold(next) : undefined;
      const afterNumber = t.slice((m.index ?? 0) + token.length, (m.index ?? 0) + token.length + 3);
      const unit = /^\s*%/.test(afterNumber) ? "pct" : unitWord ? UNITS[unitWord] : undefined;
      facts.push({ value, unit });
      return;
    }
    const word = fold(token);
    if (NUMBER_WORDS[word]) {
      const next = matches[index + 1]?.[0];
      const unitWord = next && /^[a-z]+$/i.test(next) ? fold(next) : undefined;
      facts.push({ value: NUMBER_WORDS[word], unit: unitWord ? UNITS[unitWord] : undefined });
    } else if (MONTHS[word]) {
      // A month only counts as a date fact next to a day or a year ("30 octobre", "May 2026"); "may be required" and
      // "mars" as a plain word are not dates.
      const near = (m?: RegExpMatchArray) => !!m && /^\d{1,4}$/.test(normalizeNumber(m[0]) ?? "") && Number(normalizeNumber(m[0])) >= 1 && Number(normalizeNumber(m[0])) <= 2100;
      if (near(matches[index - 1]) || near(matches[index + 1])) facts.push({ value: MONTHS[word] });
    }
  });
  return facts;
}

/** Do two fact lists agree exactly (as multisets), with equal units wherever both sides name one? */
export function factsAgree(a: Fact[], b: Fact[]): boolean {
  if (a.length !== b.length) return false;
  const pool = b.slice();
  for (const fact of a) {
    // prefer an exact (value + unit) match, then a value match where a unit is unknown on either side
    let index = pool.findIndex((x) => x.value === fact.value && x.unit === fact.unit);
    if (index < 0) index = pool.findIndex((x) => x.value === fact.value && (!x.unit || !fact.unit));
    if (index < 0) return false;
    pool.splice(index, 1);
  }
  return true;
}

// ---------------------------------------------------------------------------------------------------------------
// Lexical overlap (cognates)
// ---------------------------------------------------------------------------------------------------------------

const STOP = new Set(
  ("avec dans pour nous vous votre vos notre nos cette ces sont etre avoir plus comme aussi leur leurs ainsi afin chez sous entre " +
    "vers donc mais dont lors tout toute tous elle elles ils ont est une des les aux que qui par sur ses son ceux celles " +
    "that this with from have will your their they what which would could about into through also more than them then there these those " +
    "been being were while where when other such each only very much many most some over make take just like our you are the and for not but can may " +
    "who how all any").split(" ")
);

function contentTokens(text: string): string[] {
  return fold(text)
    .split(/[^a-z]+/)
    .filter((w) => w.length >= 4 && !STOP.has(w));
}

function commonPrefix(a: string, b: string): number {
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i += 1;
  return i;
}

/** French/English word pair that looks like the same word (système/system, expérience/experienced). */
export function isCognate(fr: string, en: string): boolean {
  const lcp = commonPrefix(fr, en);
  return lcp >= 4 && lcp >= Math.min(fr.length, en.length) * 0.6;
}

/**
 * Everyday job-posting vocabulary that is NOT a cognate pair (équipe/team, équilibre/balance, bureau/office...).
 * (French stem, English stem), accent-folded, matched by prefix. This is one signal among several, never proof alone:
 * a posting is only split when structure, facts, links and overall vocabulary all agree.
 */
const GLOSSARY: Array<[string, string]> = [
  ["equip", "team"], ["client", "custom"], ["entrepris", "compan"], ["societe", "compan"], ["travail", "work"], ["vie", "life"],
  ["equilibr", "balanc"], ["harmon", "harmon"], ["apprend", "learn"], ["apprent", "learn"], ["carrier", "career"], ["croiss", "growth"],
  ["croiss", "grow"], ["bureau", "office"], ["poste", "role"], ["poste", "position"], ["poste", "job"], ["emploi", "job"], ["candidat", "candidate"],
  ["exigen", "requirement"], ["competen", "skill"], ["formation", "educat"], ["formation", "train"], ["diplom", "degree"], ["baccalaur", "bachelor"],
  ["connaiss", "knowledge"], ["capacit", "abilit"], ["soutien", "support"], ["soutenir", "support"], ["offre", "offer"], ["offrons", "offer"],
  ["avantag", "benefit"], ["remunerat", "compensat"], ["salair", "pay"], ["equitab", "equal"], ["egalite", "equal"], ["chance", "opportunit"],
  ["valeur", "value"], ["objectif", "goal"], ["resultat", "result"], ["reussite", "success"], ["succes", "success"], ["concev", "design"],
  ["concept", "design"], ["livrer", "deliver"], ["fournir", "provid"], ["fournis", "provid"], ["creer", "creat"], ["construi", "build"],
  ["batir", "build"], ["bati", "built"], ["amelior", "improv"], ["partenaire", "partner"], ["securite", "secur"], ["fiabilit", "reliab"],
  ["monde", "world"], ["mondial", "world"], ["partout", "around"], ["fonction", "function"], ["gestion", "manag"], ["gerer", "manag"],
  ["diriger", "lead"], ["dirige", "lead"], ["superieur", "senior"], ["stagiaire", "intern"], ["stage", "intern"], ["etudiant", "student"],
  ["semaine", "week"], ["mois", "month"], ["jour", "day"], ["annee", "year"], ["heure", "hour"], ["plein", "full"], ["bilingue", "bilingual"],
  ["francais", "french"], ["anglais", "english"], ["langue", "language"], ["deplac", "travel"], ["voyage", "travel"], ["conge", "leave"],
  ["vacances", "vacation"], ["assurance", "insurance"], ["retraite", "retire"], ["retraite", "pension"], ["sante", "health"], ["horaire", "schedule"],
  ["echelle", "range"], ["fourchette", "range"], ["adaptation", "accommodat"], ["handicap", "disab"], ["candidature", "applicat"], ["postuler", "appl"],
  ["notamment", "includ"], ["inclure", "includ"], ["comprend", "includ"], ["comprendre", "understand"], ["comprend", "understand"],
  ["precis", "accurate"], ["besoin", "need"], ["enjeu", "challenge"], ["defi", "challenge"], ["probleme", "problem"], ["solution", "solution"],
  ["utilis", "use"], ["outil", "tool"], ["logiciel", "software"], ["ingenieur", "engineer"], ["developpeur", "developer"], ["donnee", "data"],
  ["infonuage", "cloud"], ["nuage", "cloud"], ["reseau", "network"], ["niveau", "level"], ["large", "wide"], ["grand", "large"], ["grande", "large"],
  ["plateforme", "platform"], ["mission", "mission"], ["projet", "project"], ["mise", "putting"], ["production", "production"], ["pret", "ready"],
  ["curieu", "curious"], ["apprentissage", "learning"], ["mentorat", "mentor"], ["performance", "performance"], ["nature", "nature"],
  ["collegue", "teammate"], ["coequipier", "teammate"], ["colleague", "colleague"], ["milieu", "environment"], ["environnement", "environment"],
  ["detail", "detail"], ["passion", "passion"], ["souci", "attention"], ["desir", "desire"], ["constant", "constant"], ["autonomie", "autonom"],
  ["autonom", "independ"], ["fluide", "fluid"], ["dynamique", "dynamic"], ["recherch", "seek"], ["recherch", "look"], ["motiv", "motivat"],
  ["rejoindre", "join"], ["joignez", "join"], ["contribu", "contribut"], ["role", "role"], ["etudes", "pursu"], ["cours", "pursu"], ["troisieme", "third"],
  ["quatrieme", "fourth"], ["annees", "year"], ["rapport", "report"], ["donner", "give"], ["offrir", "provid"], ["tenir", "hold"],
];

const glossaryMatch = (fr: string, en: string) => GLOSSARY.some(([f, e]) => fr.startsWith(f) && en.startsWith(e));
const related = (fr: string, en: string) => isCognate(fr, en) || glossaryMatch(fr, en);

export interface Overlap {
  /** share of French content words that have an English counterpart (cognate or glossary) */
  fr: number;
  /** share of English content words that have a French counterpart */
  en: number;
  frWords: number;
  enWords: number;
}

export function cognateOverlap(frText: string, enText: string): Overlap {
  const fr = contentTokens(frText);
  const en = contentTokens(enText);
  const frHit = fr.filter((f) => en.some((e) => related(f, e))).length;
  const enHit = en.filter((e) => fr.some((f) => related(f, e))).length;
  return { fr: fr.length ? frHit / fr.length : 0, en: en.length ? enHit / en.length : 0, frWords: fr.length, enWords: en.length };
}

// ---------------------------------------------------------------------------------------------------------------
// Shape
// ---------------------------------------------------------------------------------------------------------------

export function sentenceCount(text: string): number {
  const parts = text
    .replace(/\b(?:e\.g|i\.e|etc|vs|inc|ltd|st|no|mr|mrs|dr)\./gi, "$1")
    .split(/[.!?]+(?=\s+[A-ZÀ-ÖØ-Þ"“(]|\s*$)/)
    .map((s) => s.trim())
    .filter((s) => s.length > 3);
  return Math.max(1, parts.length);
}

export interface UnitCheck {
  fr: string;
  en: string;
  frLinks: string[];
  enLinks: string[];
}

/** Hard checks on one aligned unit (paragraph, list item or line). Returns the reason it failed, or null. */
export function checkUnit(u: UnitCheck): string | null {
  if (!factsAgree(extractFacts(u.fr), extractFacts(u.en))) return "facts";
  const a = u.frLinks.slice().sort().join("|");
  const b = u.enLinks.slice().sort().join("|");
  if (a !== b) return "links";
  const lf = u.fr.length;
  const le = u.en.length;
  if (Math.min(lf, le) >= 40 && (lf / le > 2.6 || lf / le < 0.4)) return "length";
  if (Math.max(lf, le) >= 140) {
    const sf = sentenceCount(u.fr);
    const se = sentenceCount(u.en);
    // translations merge and split sentences; a large difference is not a translation of the same passage
    if (Math.abs(sf - se) > Math.max(1, Math.floor(Math.max(sf, se) * 0.5))) return "sentences";
  }
  return null;
}

/** Thresholds, calibrated on the real bilingual postings in the inventory and on adversarial unrelated pairs (see tests). */
export const MIN_RUN_OVERLAP = 0.3;
/** A paragraph or list item with at least this many content words must show this much overlap on its own. */
export const MIN_UNIT_OVERLAP = 0.2;
export const UNIT_OVERLAP_WORDS = 6;
/** Shorter units need stronger overlap, or an agreeing fact, since they have little text to compare. */
export const MIN_SHORT_UNIT_OVERLAP = 0.4;
/** Passages with fewer content words than this cannot be verified by lexical overlap on their own. */
export const MIN_WORDS_FOR_OVERLAP = 8;

/** Diagnostic: why two passages are (not) accepted as a pair. Used by tests and audits, never by the UI. */
export function explainMatch(fr: string, en: string, frLinks: string[] = [], enLinks: string[] = []): { hard: string | null; overlap: Overlap; frFacts: Fact[]; enFacts: Fact[] } {
  return { hard: checkUnit({ fr, en, frLinks, enLinks }), overlap: cognateOverlap(fr, en), frFacts: extractFacts(fr), enFacts: extractFacts(en) };
}
