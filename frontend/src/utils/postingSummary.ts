import { classifySectionHeading, isBoilerplateHeading } from "./descriptionSections";

type Bucket = "requirements" | "responsibilities" | "preferred" | "details" | "benefits";
type Kind = Bucket | "intro" | "skip";
const ORDER: Bucket[] = ["requirements", "responsibilities", "preferred", "details", "benefits"];
/** A richer overview, rather than a handful of bullets. Whole source blocks are never truncated. */
export const SUMMARY_CHARACTER_BUDGET = 4000;
const LABELS = {
  en: { requirements: "Requirements", responsibilities: "Responsibilities", preferred: "Preferred qualifications", details: "Role details", benefits: "Benefits" },
  fr: { requirements: "Exigences", responsibilities: "Responsabilités", preferred: "Qualifications souhaitées", details: "Détails du poste", benefits: "Avantages" },
};
const clean = (text: string) => text.replace(/\s+/g, " ").trim();

/**
 * Conditions that decide whether a particular reader can take the job: where and how often they must be in an office,
 * relocation, language, who may apply (students, graduation dates, work authorization) and when. They are kept in the
 * Summary wherever the employer put them, even inside a company-description section that is otherwise left out.
 */
const APPLICANT_CONDITIONS: RegExp[] = [
  // Office attendance
  /\b(?:\d+|one|two|three|four|five)\s*(?:-\s*\d+\s*)?days?\b[^.]{0,80}\b(?:office|week|on[ -]?site|in[ -]person|remote|home)\b/,
  /\b(?:based|located|work(?:ing)?)\s+(?:in|out of|at|from)\s+(?:our|the|a)\b[^.]{0,60}\boffices?\b/,
  /\b(?:hybrid|on[ -]?site|in[ -]office|in[ -]person|remote|office[ -]based)\s+(?:role|position|work|model|schedule|policy|arrangement|opportunity|requirement|attendance|presence)s?\b/,
  /\bthis\s+(?:is\s+(?:a|an)\s+)?(?:fully\s+|primarily\s+)?(?:hybrid|on[ -]?site|remote|in[ -]office|in[ -]person)\b/,
  /\b(?:in[ -]office|in[ -]person|on[ -]?site)\s+(?:requirement|attendance|presence|expectation|policy|days?)s?\b/,
  /\b(?:required|expected|must|will\s+be\s+required)\b[^.]{0,70}\b(?:in\s+the\s+office|on[ -]?site|in[ -]person|in[ -]office|to\s+relocate)\b/,
  /\bwork(?:ing)?\s+model\b|\bworkplace\s+model\b/,
  // Relocation
  /\brelocat(?:e|ion|ing)\b/,
  // Language
  /\b(?:french|english|spanish|bilingual|bilingue|francais|anglais)\b[^.]{0,60}\b(?:required|requis|mandatory|must|essential|fluen\w+|proficien\w+|knowledge|connaissance|assessment|test)\b/,
  /\b(?:knowledge|command|fluency|proficiency|connaissance|maitrise)\b[^.]{0,30}\b(?:of|in|du|de l'?)\s*(?:the\s+)?(?:french|english|spanish|francais|anglais)\b/,
  // Who may apply and when
  /\b(?:students?|graduat\w+|co-?op|intern(?:ship)?s?)\b[^.]{0,80}\b(?:graduat\w+|enrolled|eligible|available|returning|pursuing|term|semester)\b/,
  /\b(?:graduat(?:e|ed|ing|ion)|graduation date)\b[^.]{0,60}\b(?:\d{4}|date|by|before|after|later)\b/,
  /\b(?:currently\s+(?:enrolled|pursuing)|returning\s+to\s+(?:school|university)|full-?time\s+student)\b/,
  /\bwork\s+term\b|\bterm\s+\d\b/,
  /\b(?:work\s+authori[sz]ation|authori[sz]ed\s+to\s+work|eligible\s+to\s+work|right\s+to\s+work|visa|sponsorship|citizen(?:ship)?|permanent\s+resident|security\s+clearance|export\s+control|itar)\b/,
];

const fold = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
/** Equal-opportunity and diversity boilerplate names "citizenship" or "inclusive" without stating any condition for the applicant. */
const EEO_BOILERPLATE = /\b(?:equal\s+(?:opportunity|employment)|regardless\s+of|without\s+regard|protected\s+(?:class|status)|diversity|inclusi(?:on|ve)|accommodat\w+|discriminat\w+|drug[- ]free)\b/;
const STRONG_CONDITION = /\b(?:visa|sponsor\w*|authori[sz]ed\s+to\s+work|work\s+authori[sz]ation|clearance|itar|export\s+control|relocat\w+|in[ -]office|on[ -]?site)\b/;
export function isApplicantCondition(text: string): boolean {
  const folded = fold(text).replace(/[\u2018\u2019]/g, "'");
  if (EEO_BOILERPLATE.test(folded) && !STRONG_CONDITION.test(folded)) return false;
  return APPLICANT_CONDITIONS.some((pattern) => pattern.test(folded));
}

/** The sentences of a block that state an applicant condition (used for company sections, which are otherwise left out). */
function applicantConditionSentences(text: string): string {
  return text.split(/(?<=[.!?])\s+(?=[A-Z0-9"“(])/).filter(isApplicantCondition).join(" ");
}

/** Important applicant conditions deserve space even when the employer puts them after general prose. */
function isKeyCondition(text: string): boolean {
  const folded = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  return /\b(?:\d+\+?\s*(?:years?|ans|annees)|bachelor|master(?:'s)?|ph\.?d|doctorate|degree|diplome|equivalent\s+(?:experience|practical)|experience\s+(?:instead|equivalente)|not\s+required|visa|sponsorship|work\s+authori[sz]ation|authori[sz]ed\s+to\s+work|eligible\s+to\s+work|security\s+clearance|citizenship|citizen|citoyennete|habilitation|permis\s+de\s+travail)\b/i.test(folded)
    || /\b(?:in[ -]?office|in[ -]?person|on[ -]?site|hybrid|remote|relocat(?:e|ion)|teletravail|hybride|bureau)\b/i.test(folded)
    || /\b(?:\d+|one|two|three|four|five)\s+days?\b[^.]{0,80}\b(?:office|week)\b/i.test(folded)
    || /\b(?:remote|hybrid|on[ -]?site|in[ -]?person|office|relocat(?:e|ion)|teletravail|hybride|bureau)\b[^.]{0,100}\b(?:only|must|require|within|days?\s+(?:a|per)|not|allowed|eligible|obligatoire|uniquement)\b/i.test(folded)
    || /\b(?:must|required|only|not|obligatoire|uniquement)\b[^.]{0,100}\b(?:remote|hybrid|on[ -]?site|office|relocat(?:e|ion)|based|resid(?:e|ent)|teletravail|bureau)\b/i.test(folded)
    || /\b(?:start|apply|application|deadline|working\s+hours?|hours?\s+per\s+week|shift|weekend|travel|debut|date\s+limite|horaire|heures?\s+par\s+semaine)\b[^.]{0,100}(?:\d|\bbefore\b|\bby\b|\brequired\b|\bmust\b|\bavant\b)/i.test(folded)
    || isApplicantCondition(text);
}

/** Recognize ATS question headings without reclassifying ordinary prose as a heading. */
function headingKind(text: string): Kind {
  const known = classifySectionHeading(text);
  if (known === "requirements" || known === "responsibilities" || known === "preferred") return known;
  if (known === "skills") return "requirements";
  if (known === "about-role" || known === "team") return "intro";
  if (known === "benefits") return "benefits";
  if (known === "company" || known === "compensation" || isBoilerplateHeading(text)) return "skip";
  const folded = text.toLowerCase().replace(/[‘’]/g, "'").replace(/[:?\s]+$/, "");
  if (/^(?:is this role right for you\??\s*)?(?:in this role[, ]+)?you(?: will|'ll)(?: be responsible for)?$/.test(folded)
    || /^(?:(?:key|major|principal) )?accountabilities$/.test(folded)) return "responsibilities";
  if (/^do you have the skills that will enable you to succeed in this role\?\s*[-–—]?\s*we(?:'d| would) love to work with you if you(?: have)?$/.test(folded)
    || /^(?:what you need to succeed|what we need to see|what you need to see|about you|your qualifications|education and experience|skills and abilities|experience and qualifications|what you bring to the team)$/.test(folded)) return "requirements";
  if (/^(?:interview process|how to apply|application process|recruitment process)$/.test(folded)) return "skip";
  return "details";
}


const BLOCK_CHILDREN = "p,div,li,ul,ol,h1,h2,h3,h4,h5,h6,table,blockquote,pre";

/**
 * Employers separate paragraphs and headings with <br><br> inside a single <p>. textContent drops <br>, which fused
 * "…research teams." and "About the role" into one run. A run of two or more <br> becomes a paragraph boundary (so a
 * bold-only line is recognised as a heading); a lone <br> is a space.
 */
export function normalizeLineBreaks(doc: Document): void {
  for (const block of Array.from(doc.body.querySelectorAll("p,div,li"))) {
    if (!Array.from(block.childNodes).some((node) => node.nodeName === "BR")) continue;
    const children = Array.from(block.childNodes);
    const groups: Node[][] = [[]];
    for (let i = 0; i < children.length; ) {
      if (children[i].nodeName !== "BR") { groups[groups.length - 1].push(children[i]); i += 1; continue; }
      let j = i;
      while (j < children.length && (children[j].nodeName === "BR" || (children[j].nodeType === 3 && !(children[j].textContent || "").trim()))) j += 1;
      const breaks = children.slice(i, j).filter((node) => node.nodeName === "BR").length;
      if (breaks >= 2 && block.tagName !== "LI" && !block.querySelector(BLOCK_CHILDREN)) groups.push([]);
      else groups[groups.length - 1].push(doc.createTextNode(" "));
      i = j;
    }
    if (groups.length === 1) {
      block.replaceChildren(...groups[0]);
      continue;
    }
    for (const group of groups) {
      if (!group.some((node) => (node.textContent || "").trim())) continue;
      const paragraph = doc.createElement("p");
      paragraph.append(...group);
      block.parentNode?.insertBefore(paragraph, block);
    }
    block.remove();
  }
}

/** Balanced source excerpts, never generated claims. Qualification paragraphs and list items stay intact. */
export function summarizePosting(html: string, language?: string | null): string {
  if (!html || typeof DOMParser === "undefined") return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  normalizeLineBreaks(doc);
  const output = doc.createElement("div");
  const buckets: Record<Bucket, string[]> = { requirements: [], responsibilities: [], preferred: [], details: [], benefits: [] };
  const intros: string[] = [];
  const seen = new Set<string>();
  let kind: Kind = "intro";
  let companySection = false;
  const isBoilerplate = (text: string) => /^(?:join (?:a|our) (?:purpose[- ]driven|winning|inclusive)|champion a customer[- ]focused culture|we are an equal opportunity employer\b)/i.test(text);
  const append = (blocks: string[], text: string) => {
    // A separate exception can qualify the preceding requirement. Select the pair as one unit.
    if (/^(?:however\b|alternatively\b|except\b|unless\b|equivalent (?:experience|practical)\b|this requirement\b|instead\b|toutefois\b|cependant\b|une experience equivalente\b)/i.test(text)
      && blocks.length) blocks[blocks.length - 1] += ` ${text}`;
    else blocks.push(text);
  };
  const add = (bucket: Bucket, text: string) => append(buckets[bucket], text);
  for (const node of Array.from(doc.body.querySelectorAll("h1,h2,h3,h4,h5,h6,p,li,div,tr,blockquote,pre"))) {
    if (node.tagName === "LI" && node.parentElement?.closest("li")) continue;
    if (node.tagName !== "LI" && node.closest("li")) continue;
    if (node.tagName !== "TR" && node.closest("tr")) continue;
    if (node.tagName === "DIV" && node.querySelector("p,div,li,ul,ol,h1,h2,h3,h4,h5,h6,table,blockquote,pre")) continue;
    if (/^(BLOCKQUOTE|PRE)$/.test(node.tagName) && node.querySelector("p,div,li")) continue;
    let text = clean(node.tagName === "TR" ? Array.from(node.children).map((cell) => cell.textContent).join(" ") : node.textContent || "");
    if (!text) continue;
    // Some ATS question labels are bold-only paragraphs longer than the full-posting heading detector accepts.
    const boldOnly = /^(P|DIV)$/.test(node.tagName) && node.querySelector("strong,b")
      && clean(Array.from(node.querySelectorAll("strong,b")).filter((bold) => !bold.parentElement?.closest("strong,b")).map((bold) => bold.textContent).join(" ")) === text;
    const recognizedLabel = text.length <= 180 && headingKind(text) !== "details";
    if (/^H[1-6]$/.test(node.tagName) || (boldOnly && recognizedLabel)) {
      companySection = classifySectionHeading(text) === "company";
      const nextKind = headingKind(text);
      // A full-sentence heading can itself state a start date, eligibility condition, or role scope.
      const words = text.split(" ").length;
      if (nextKind === "details" && (isKeyCondition(text) || words >= 8 || (words >= 4 && /[.!?]$/.test(text)))) {
        if (!seen.has(text)) { seen.add(text); add("details", text); }
      }
      kind = nextKind;
      continue;
    }
    // IDs are metadata, not an overview. Remove only a labelled ID prefix, retaining any following role text.
    text = text.replace(/^(?:job\s+)?requisition\s+(?:id\s*[#:]*\s*)?[a-z0-9-]+\s*[:;,-]?\s*/i, "").trim();
    if (!text || isBoilerplate(text) || seen.has(text)) continue;
    // General company/legal material is omitted; applicant-specific constraints inside it are kept.
    // The company section is left out, except the sentences that state a condition for the applicant.
    if (companySection) {
      text = applicantConditionSentences(text);
      if (!text || seen.has(text)) continue;
    }
    if (kind === "skip" && !isKeyCondition(text)) continue;
    seen.add(text);
    if (kind === "intro" && node.tagName !== "LI") {
      // A following sentence can qualify the first (for example, accepting experience
      // instead of a degree). Treat introductory paragraphs as indivisible source blocks.
      append(intros, text);
      continue;
    }
    // An unlabelled list has its own budget; the introduction must never consume its first item.
    const bucket = kind === "intro" || kind === "skip" ? "details" : kind;
    add(bucket, text);
  }

  const labels = LABELS[language === "fr" ? "fr" : "en"];
  // One or two overview paragraphs, with the remaining unlabelled prose available as role details.
  const overview = intros.slice(0, 2);
  for (const paragraph of intros.slice(2)) add("details", paragraph);
  let budget = SUMMARY_CHARACTER_BUDGET;
  const selected: Record<Bucket, Set<number>> = { requirements: new Set(), responsibilities: new Set(), preferred: new Set(), details: new Set(), benefits: new Set() };
  const take = (bucket: Bucket, index: number) => {
    if (selected[bucket].has(index)) return true;
    const cost = buckets[bucket][index].length + (selected[bucket].size ? 0 : labels[bucket].length);
    if (cost > budget) return false;
    selected[bucket].add(index); budget -= cost; return true;
  };
  // Conditions are chosen before generic bullets, including those at the end of a section.
  // If they cannot fit without truncation, the caller safely falls back to Full Posting.
  for (const bucket of ORDER) {
    for (let i = 0; i < buckets[bucket].length; i += 1) {
      if (isKeyCondition(buckets[bucket][i]) && !take(bucket, i)) return "";
    }
  }
  const requiredOverview = overview.filter(isKeyCondition);
  if (requiredOverview.reduce((sum, item) => sum + item.length, 0) > budget) return "";
  // Reserve a representative requirement and responsibility before spending room on introductions.
  for (const bucket of ["requirements", "responsibilities"] as const) {
    if (buckets[bucket].length && !selected[bucket].size && !take(bucket, 0)) return "";
  }
  const chosenOverview = new Set<string>();
  for (const item of [...requiredOverview, ...overview]) {
    if (!chosenOverview.has(item) && item.length <= budget) { chosenOverview.add(item); budget -= item.length; }
  }
  if (requiredOverview.some((item) => !chosenOverview.has(item))) return "";
  // Keep source order, and make unselected overview paragraphs available if a smaller block fits later.
  for (const item of overview) if (!chosenOverview.has(item)) add("details", item);
  for (const item of overview) {
    if (chosenOverview.has(item)) { const p = doc.createElement("p"); p.textContent = item; output.appendChild(p); }
  }
  const positions: Record<Bucket, number> = { requirements: 0, responsibilities: 0, preferred: 0, details: 0, benefits: 0 };
  // Use all available room, balancing sections instead of imposing arbitrary four-bullet caps.
  while (ORDER.some((bucket) => positions[bucket] < buckets[bucket].length)) {
    for (const bucket of ORDER) {
      while (positions[bucket] < buckets[bucket].length) {
        const index = positions[bucket]++;
        if (!selected[bucket].has(index) && take(bucket, index)) break;
      }
    }
  }
  for (const bucket of ORDER) {
    if (!selected[bucket].size) continue;
    const heading = doc.createElement("h4"); heading.className = "job-section-heading"; heading.textContent = labels[bucket]; output.appendChild(heading);
    const list = doc.createElement("ul"); list.className = "job-summary-list"; output.appendChild(list);
    for (const index of [...selected[bucket]].sort((a, b) => a - b)) { const li = doc.createElement("li"); li.textContent = buckets[bucket][index]; list.appendChild(li); }
  }
  return output.innerHTML;
}
