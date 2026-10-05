/**
 * Splits already-sanitized job description HTML into the role-specific body and a
 * collapsible "Company policies & disclosures" part.
 *
 * Only whole sections that start with a heading which is clearly boilerplate
 * (equal opportunity, AI usage, privacy, accommodation, legal notices) are moved.
 * Any heading that suggests role content (responsibilities, qualifications,
 * requirements, compensation, benefits, ...) is never collapsed.
 */

const BOILERPLATE_HEADING = new RegExp(
  [
    "equal\\s+(?:employment\\s+)?opportunit",
    "\\beeo\\b",
    "\\bai\\s+(?:usage|use|policy|disclosure|in\\s+(?:our\\s+)?(?:hiring|recruit))",
    "(?:use|usage)\\s+of\\s+(?:ai|artificial)",
    "artificial\\s+intelligence\\s+(?:usage|use|policy|disclosure)",
    "privacy\\s+(?:notice|policy|statement|disclosure)",
    "(?:applicant|candidate|job\\s+applicant)\\s+privacy",
    "data\\s+(?:privacy|protection)\\s+(?:notice|policy|statement)",
    "\\baccommodation",
    "\\baccessibility\\s+(?:statement|notice|accommodation)",
    "(?:legal|recruitment)\\s+(?:notice|disclosure|disclaimer)",
    "(?:diversity|inclusion|belonging)[^.]{0,40}(?:statement|commitment)",
    "\\bpay\\s+transparency\\s+(?:notice|statement)",
    "background\\s+check\\s+(?:notice|disclosure)",
    "\\be-?verify\\b",
    "\\bcandidate\\s+(?:notice|disclosure)s?\\b",
    "\\bdisclosures?\\b",
  ].join("|"),
  "i"
);

const ROLE_CONTENT_HEADING =
  /responsibilit|qualificat|requirement|compensation|salary|benefit|perks|about the (?:role|team|job|position)|what you|you(?:'|’)ll|your (?:role|impact)|skills|experience|nice to have|preferred|the role|who you are|overview|why (?:join|this)|how you/i;

/** Lower-cases nothing, only removes accents so French headings ("Responsabilités") match one ASCII vocabulary. */
const foldAccents = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/œ/g, "oe").replace(/Œ/g, "OE");

const FRENCH_BOILERPLATE_HEADING =
  /egalite\s+(?:des\s+chances|en\s+matiere\s+d'emploi)|equite\s+en\s+matiere\s+d'emploi|mesures?\s+d'adaptation|accommodements?|avis\s+de\s+confidentialite|politique\s+de\s+confidentialite|protection\s+des\s+(?:donnees|renseignements)|avis\s+juridique|divulgations?/i;
const FRENCH_ROLE_HEADING = /responsabilit|qualification|exigence|remuneration|salaire|avantage|competence|votre\s+(?:role|profil)|le\s+poste|a\s+propos\s+(?:du\s+poste|de\s+l'equipe)/i;

export function isBoilerplateHeading(text: string): boolean {
  const t = text.trim();
  if (!t || t.length > 120) return false;
  if (ROLE_CONTENT_HEADING.test(t)) return false;
  if (BOILERPLATE_HEADING.test(t)) return true;
  const folded = foldAccents(t).replace(/[‘’]/g, "'");
  return !FRENCH_ROLE_HEADING.test(folded) && FRENCH_BOILERPLATE_HEADING.test(folded);
}

export interface SplitDescription {
  mainHtml: string;
  policiesHtml: string;
}

const HEADING_TAGS = new Set(["H1", "H2", "H3", "H4", "H5", "H6"]);

export function splitPolicySections(html: string): SplitDescription {
  if (!html || typeof DOMParser === "undefined") return { mainHtml: html || "", policiesHtml: "" };
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  const main: string[] = [];
  const policies: string[] = [];
  let collapsing = false;

  // childNodes, not children: bare top-level text (Amazon/Workday often have it) must never be dropped.
  const scratch = doc.createElement("div");
  Array.from(doc.body.childNodes).forEach((node) => {
    let html = "";
    if (node.nodeType === 1) {
      const el = node as Element;
      if (HEADING_TAGS.has(el.tagName)) collapsing = isBoilerplateHeading(el.textContent || "");
      html = el.outerHTML;
    } else if (node.nodeType === 3) {
      scratch.textContent = node.textContent || "";
      html = scratch.innerHTML;
    }
    if (html) (collapsing ? policies : main).push(html);
  });

  // Never hide the whole description: if everything looks like boilerplate keep it visible.
  if (main.length === 0) return { mainHtml: html, policiesHtml: "" };
  return { mainHtml: main.join(""), policiesHtml: policies.join("") };
}


// ---------------------------------------------------------------------------
// Empty label / heading removal
// ---------------------------------------------------------------------------

const HEADING_RANK: Record<string, number> = { H1: 1, H2: 2, H3: 3, H4: 4, H5: 5, H6: 6 };
const BOLD_LABEL_RANK = 7;
const CONTENT_TAGS = "img, table, ul, ol, li, svg, video, iframe, picture, canvas";
const CONTAINER_TAGS = new Set(["DIV", "SECTION", "ARTICLE", "MAIN", "BODY"]);

function hasVisibleText(el: Element): boolean {
  return (el.textContent || "").replace(/[\s\u00a0\u200b]+/g, "") !== "";
}

/** A block that carries real content (text, list, table, image, ...). Whitespace, <br> and <hr> do not. */
function isMeaningful(el: Element): boolean {
  if (el.tagName === "HR" || el.tagName === "BR") return false;
  return hasVisibleText(el) || el.matches(CONTENT_TAGS) || el.querySelector(CONTENT_TAGS) !== null;
}

/**
 * A heading that is a full statement ("This role is for applicants actively looking to start before December 1,
 * 2026.") carries information of its own. Only short field labels ("Salary Range", "Benefits:") may be dropped for
 * being empty; a sentence never is, even when the next node is another heading.
 */
function isInformativeHeading(el: Element): boolean {
  const words = (el.textContent || "").replace(/[\s\u00a0]+/g, " ").trim().split(" ").filter(Boolean);
  if (words.length >= 8) return true;
  return words.length >= 4 && /[.!?]["')\u201d\u2019]?$/.test(words[words.length - 1]);
}

interface LabelInfo {
  rank: number;
  /** true for "<p><strong>Job Category:</strong> Engineering</p>": a label that already carries its value */
  selfContent: boolean;
}

/**
 * Heading-like nodes: h1-h6, a short bold-only paragraph ending in ":" (label without value), or a
 * paragraph that starts with a bold "Label:" and continues with text (label WITH value).
 */
function labelInfo(el: Element): LabelInfo | null {
  const heading = HEADING_RANK[el.tagName];
  if (heading) return { rank: heading, selfContent: false };
  if (el.tagName !== "P") return null;
  const first = el.firstElementChild;
  if (!first || !/^(STRONG|B)$/.test(first.tagName)) return null;
  const text = (el.textContent || "").replace(/[\s\u00a0]+/g, " ").trim();
  const boldText = (first.textContent || "").replace(/[\s\u00a0]+/g, " ").trim();
  if (!boldText.endsWith(":") || boldText.length > 80) return null;
  if (text === boldText) return { rank: BOLD_LABEL_RANK, selfContent: false };
  const bolds = Array.from(el.querySelectorAll("strong, b")).map((b) => b.textContent || "").join("").replace(/[\s\u00a0]+/g, " ").trim();
  return bolds === boldText && text.startsWith(boldText) ? { rank: BOLD_LABEL_RANK, selfContent: true } : null;
}

function cleanChildren(container: Element): void {
  // Recurse into wrapper blocks first so headings nested in <div>/<section> are handled too.
  Array.from(container.children).forEach((child) => {
    if (CONTAINER_TAGS.has(child.tagName) && child.querySelector("h1,h2,h3,h4,h5,h6,p,strong,b")) cleanChildren(child);
  });

  const nodes = Array.from(container.children);
  const infos = nodes.map(labelInfo);
  const remove = new Set<Element>();

  infos.forEach((info, index) => {
    if (!info || info.selfContent) return;
    if (isInformativeHeading(nodes[index])) return; // a statement, not an empty label: always kept
    // The section runs until the next heading/label of the same or higher rank.
    let end = index + 1;
    let meaningful = false;
    while (end < nodes.length) {
      const other = infos[end];
      if (other && other.rank <= info.rank) {
        // "Additional Job Details" followed by "Address:", "City:", ...: the heading titles a block of fields.
        const titlesFieldBlock = end === index + 1 && !/:\s*$/.test(nodes[index].textContent || "") && /:\s*$/.test((nodes[end].textContent || "").trim());
        if (titlesFieldBlock) meaningful = true;
        break;
      }
      if (!other && isMeaningful(nodes[end])) meaningful = true;
      if (other && other.selfContent) meaningful = true; // e.g. a labelled field nested under a heading
      if (other && isInformativeHeading(nodes[end])) meaningful = true; // a nested statement is content
      end += 1;
    }
    // Loose text that follows a label ("Address:" then "777 Bay St" as a bare text node) is its value.
    if (!meaningful) {
      const stop = end < nodes.length ? nodes[end] : null;
      for (let sibling = nodes[index].nextSibling; sibling && sibling !== stop; sibling = sibling.nextSibling) {
        if (sibling.nodeType === 3 && (sibling.textContent || "").replace(/[\s\u00a0\u200b]+/g, "") !== "") {
          meaningful = true;
          break;
        }
      }
    }
    if (!meaningful) {
      for (let i = index; i < end; i += 1) remove.add(nodes[i]);
    }
  });

  nodes.forEach((node, index) => {
    if (remove.has(node)) {
      node.remove();
    } else if (!infos[index] && node.tagName !== "HR" && !isMeaningful(node) && !CONTAINER_TAGS.has(node.tagName)) {
      node.remove(); // empty paragraphs, <br>-only blocks, whitespace
    }
  });

  // Dividers left dangling (leading, trailing or doubled) go too.
  Array.from(container.children).forEach((node, index, rest) => {
    if (node.tagName !== "HR") return;
    if (index === 0 || index === rest.length - 1 || rest[index - 1].tagName === "HR") node.remove();
  });
}

/**
 * Presentation cleanup for sanitized description HTML: removes headings / bold "Label:" lines whose
 * section has no content (e.g. "Salary Range:" followed by nothing or another heading), plus
 * empty paragraphs and their orphaned dividers. Populated sections and all real content are untouched;
 * the stored description is never modified.
 */
export function removeEmptySections(html: string): string {
  if (!html || typeof DOMParser === "undefined") return html || "";
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  cleanChildren(doc.body);
  return doc.body.innerHTML.trim();
}


// ---------------------------------------------------------------------------
// Section structure ("About the role", "Requirements", "Responsibilities", ...)
// ---------------------------------------------------------------------------

export type SectionKind =
  | "about-role"
  | "responsibilities"
  | "requirements"
  | "preferred"
  | "skills"
  | "compensation"
  | "benefits"
  | "team"
  | "company"
  | "other";

/**
 * Whole-heading vocabulary only (anchored). A heading that merely contains a keyword inside a longer
 * sentence is never classified, so ordinary prose cannot be mistaken for a section.
 * Order matters: "preferred qualifications" must win over "qualifications".
 */
const SECTION_PATTERNS: Array<[SectionKind, RegExp]> = [
  ["preferred", /^(?:preferred|desired|desirable|bonus|nice[- ]to[- ]haves?|additional|ideal)(?:\s+(?:qualifications?|skills?|experience|requirements?|points?|attributes?))?$|^(?:what|things)\s+(?:will\s+)?(?:make|sets?)\s+you\s+stand\s+out$|^(?:it(?:'s| is)\s+a\s+)?bonus\s+if(?:\s+you)?$|^extra\s+credit$/],
  ["requirements", /^(?:(?:minimum|basic|required|key|job|core)\s+)?(?:requirements?|qualifications?)(?:\s+(?:and|&)\s+(?:skills?|experience|requirements?|qualifications?))?$|^(?:minimum|basic|required)\s+(?:skills?|experience)$|^(?:what|who)\s+you(?:'ll)?\s+(?:bring|need|have)$|^who\s+you\s+are$|^what\s+you\s+need(?:\s+to\s+(?:succeed|be\s+successful|have))?$|^you\s+(?:may|might|would|could)\s+be\s+(?:a\s+)?(?:good|great)\s+fit(?:\s+if)?$|^what\s+we(?:'re|\s+are)\s+looking\s+for$|^must[- ]haves?$|^you\s+have$|^you(?:'ll)?\s+(?:bring|need)$|^skills?\s+(?:and|&)\s+(?:qualifications?|experience)$/],
  ["responsibilities", /^(?:(?:key|core|primary|main|job|role)\s+)?(?:responsibilities|duties)(?:\s+include)?$|^what\s+you(?:'ll|\s+will)\s+(?:do|be\s+doing|work\s+on|own)$|^what\s+you\s+(?:do|will\s+do)$|^what\s+will\s+you\s+(?:do|be\s+doing|work\s+on)$|^(?:the\s+)?day[- ]to[- ]day$|^in\s+this\s+(?:role|position|internship),?\s+you(?:'ll|\s+will)(?:\s+have\s+the\s+opportunity\s+to|\s+be\s+(?:able\s+to|responsible\s+for))?$|^your\s+(?:role|impact|responsibilities)$|^you(?:'ll|\s+will)$/],
  ["about-role", /^(?:about\s+(?:the|this|your)\s+(?:role|job|position|opportunity|internship)|(?:the\s+)?(?:role|position|opportunity)|(?:role|job|position)\s+(?:summary|overview|description)|(?:summary|overview|job\s+description|description|position\s+summary|role\s+overview))$/],
  ["skills", /^(?:(?:technical|key)\s+)?skills(?:\s+(?:and|&)\s+(?:technologies|tools))?$|^(?:tech(?:nology)?\s+stack|tools\s+(?:and|&)\s+technologies)$/],
  ["compensation", /^(?:compensation(?:\s+(?:and|&)\s+benefits)?|salary(?:\s+range)?|pay(?:\s+range)?|base\s+pay(?:\s+range)?|salary\s+(?:and|&)\s+benefits|total\s+rewards|compensation\s+range)$/],
  ["benefits", /^(?:benefits(?:\s+(?:and|&)\s+perks)?|perks(?:\s+(?:and|&)\s+benefits)?|what\s+we\s+offer|(?:our|the)\s+benefits|why\s+(?:you(?:'ll)?\s+love\s+working\s+here|join\s+us)|life\s+at\s+\S+|what(?:'s|\s+is)\s+in\s+it\s+for\s+you)$/],
  ["team", /^about\s+(?:the|our|this)\s+(?:[a-z0-9&/ -]{1,40}\s)?(?:team|department|group|org(?:anization)?)$|^(?:the|our|meet\s+the)\s+team$/],
  ["company", /^about\s+(?:the\s+company|us|our\s+company)$|^who\s+(?:we\s+are|are\s+we)$|^(?:our\s+)?(?:mission|company)$|^company\s+(?:overview|description|culture|values|mission|history)$|^(?:our|the\s+company)\s+(?:values|culture|story|history|vision|mission)$|^what\s+we\s+do$/],
];

/**
 * French equivalents of the same whole-heading vocabulary, matched on accent-folded text ("Responsabilités" ->
 * "responsabilites"). Same order rule as above, same anchoring: a longer sentence is never classified.
 */
const FRENCH_SECTION_PATTERNS: Array<[SectionKind, RegExp]> = [
  ["preferred", /^(?:(?:qualifications?|competences|exigences|experience)\s+(?:souhaitee?s?|appreciee?s?|supplementaires?)|atouts?|un\s+atout|ce\s+qui\s+serait\s+un\s+plus)$/],
  ["requirements", /^(?:exigences?|qualifications?|conditions?)(?:\s+(?:minimales?|requises?|de\s+base|essentielles?))?$|^(?:competences|experience)\s+(?:requises?|exigees?)$|^ce\s+que\s+vous\s+(?:apportez|devez\s+avoir)$|^votre\s+profil$|^profil\s+recherche$|^qui\s+vous\s+etes$|^ce\s+que\s+nous\s+recherchons$/],
  ["responsibilities", /^(?:principales\s+)?(?:responsabilites|taches|fonctions|attributions)(?:\s+principales)?$|^vos\s+(?:responsabilites|taches|fonctions|missions)$|^(?:vos\s+)?missions?$|^ce\s+que\s+vous\s+(?:ferez|allez\s+faire|accomplirez)$|^roles?\s+et\s+responsabilites$|^votre\s+(?:role|mission|impact)$|^dans\s+ce\s+role,?\s+vous$|^au\s+quotidien$|^(?:une\s+)?journee\s+type$/],
  ["about-role", /^(?:a\s+propos\s+(?:du|de\s+ce|de\s+cet?)\s+(?:poste|role|emploi|stage)|presentation\s+du\s+poste|description\s+du\s+poste|apercu\s+du\s+poste|sommaire\s+du\s+poste|le\s+poste|le\s+role)$/],
  ["skills", /^competences(?:\s+techniques)?$/],
  ["compensation", /^(?:remuneration|salaire|echelle\s+salariale|fourchette\s+salariale|remuneration\s+et\s+avantages(?:\s+sociaux)?)$/],
  ["benefits", /^(?:avantages(?:\s+sociaux)?|ce\s+que\s+nous\s+offrons|pourquoi\s+nous\s+rejoindre)$/],
  ["team", /^a\s+propos\s+(?:de\s+l'|de\s+notre\s+|de\s+la\s+|du\s+)?(?:equipe|departement|groupe)(?:\s+[a-z0-9&/ -]{1,30})?$|^(?:notre|l')\s*equipe$/],
  ["company", /^a\s+propos\s+(?:de\s+nous|de\s+notre\s+(?:entreprise|societe)|de\s+l'entreprise|de\s+la\s+societe)$|^qui\s+sommes[- ]nous$|^notre\s+(?:mission|entreprise|societe)$|^(?:notre|nos)\s+(?:valeurs|culture|histoire|vision)$|^ce\s+que\s+nous\s+faisons$/],
];

/** Normalizes a heading for classification: lower-case, straight quotes, no decoration/trailing colon. */
function normalizeHeading(text: string): string {
  return foldAccents(text)
    .replace(/[‘’]/g, "'")
    .replace(/[\s\u00a0]+/g, " ")
    .replace(/^[^a-z0-9]+|[^a-z0-9]+$/gi, "")
    .toLowerCase()
    .trim();
}

/** Returns the section kind for a heading, or null when the heading is not a known section title. */
export function classifySectionHeading(text: string, companyName?: string | null): SectionKind | null {
  const t = normalizeHeading(text);
  if (!t || t.length > 60) return null;
  // "About Wealthsimple" is only a company section when it names the posting's own company.
  if (companyName) {
    const name = normalizeHeading(companyName);
    if (name && (t === `about ${name}` || t === `who is ${name}` || t === `${name} overview` || t === `a propos d'${name}` || t === `a propos de ${name}` || t === `a propos d ${name}`)) return "company";
  }
  for (const [kind, pattern] of SECTION_PATTERNS) {
    if (pattern.test(t)) return kind;
  }
  for (const [kind, pattern] of FRENCH_SECTION_PATTERNS) {
    if (pattern.test(t)) return kind;
  }
  return null;
}

const CONTAINER_UNWRAP = new Set(["DIV", "SECTION", "ARTICLE", "MAIN"]);

/**
 * Greenhouse wraps parts of a posting in presentation-only containers (<div class="content-intro">,
 * "content-conclusion", "content-pay-transparency"). The wrapper hides the headings and paragraphs inside it from
 * section detection, so a company introduction inside it could never be recognised. Unwrap them in place: same
 * nodes, same order, no wrapper.
 */
function unwrapAtsWrappers(root: Element): void {
  root.querySelectorAll(":scope > div.content-intro, :scope > div.content-conclusion, :scope > div.content-pay-transparency").forEach((wrapper) => {
    wrapper.replaceWith(...Array.from(wrapper.childNodes));
  });
  unwrapPlainContainers(root);
}

const BLOCK_CHILD = /^(?:P|UL|OL|H[1-6]|DIV|TABLE|BLOCKQUOTE|SECTION)$/;

/**
 * A top-level <div>/<section> that only groups blocks (paragraphs, lists, headings) and has no text of its own is
 * layout, not content: lift its children into the parent so section and intro detection can see the headings and
 * paragraphs inside it. Nodes keep their order; nothing is added or removed. Repeated for nested wrappers.
 */
function unwrapPlainContainers(root: Element): void {
  for (let pass = 0; pass < 3; pass += 1) {
    let changed = false;
    Array.from(root.children).forEach((child) => {
      if (child.tagName !== "DIV" && child.tagName !== "SECTION") return;
      const nodes = Array.from(child.childNodes);
      const loneText = nodes.some((n) => n.nodeType === 3 && (n.textContent || "").trim() !== "");
      const blocks = nodes.filter((n) => n.nodeType === 1 && BLOCK_CHILD.test((n as Element).tagName));
      if (loneText || blocks.length === 0 || child.matches("section.job-section")) return;
      child.replaceWith(...nodes);
      changed = true;
    });
    if (!changed) break;
  }
}

/**
 * Groups already-sanitized description HTML into consistent sections:
 * <section class="job-section" data-section="requirements"><h4 class="job-section-heading">…</h4>…</section>.
 *
 * Deliberately conservative:
 * - A section is a heading plus every following node up to the next heading, in source order; nothing is
 *   moved, reordered, merged, summarized or dropped (except divider-only leftovers).
 * - Grouping only happens when at least one heading is a *known* section title. Otherwise the input is
 *   returned untouched so unfamiliar layouts are never guessed at.
 * - Content before the first heading stays as an ungrouped intro; no heading is invented for it.
 * - Headings that are not known titles keep their source text and get data-section="other".
 */
export function structureDescription(html: string, companyName?: string | null): string {
  if (!html || typeof DOMParser === "undefined") return html || "";
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  unwrapAtsWrappers(doc.body);

  let root: Element = doc.body;
  // Employers often wrap the whole posting in one <div>; look inside it (content is preserved either way).
  while (root.children.length === 1 && CONTAINER_UNWRAP.has(root.children[0].tagName) && root.childNodes.length === 1) {
    root = root.children[0];
  }

  const isHeading = (n: Node): n is Element => n.nodeType === 1 && /^H[1-6]$/.test((n as Element).tagName);
  const nodes = Array.from(root.childNodes);
  const headings = nodes.filter(isHeading);
  if (headings.length === 0) return html;
  const kinds = headings.map((h) => classifySectionHeading(h.textContent || "", companyName));
  if (!kinds.some((k) => k !== null)) return html;

  const out = doc.createElement("div");
  let current: Element | null = null;
  let hIndex = 0;
  for (const node of nodes) {
    if (isHeading(node)) {
      const kind = kinds[hIndex++] ?? null;
      const section = doc.createElement("section");
      section.className = "job-section";
      section.setAttribute("data-section", kind ?? "other");
      // Semantic outline: the job title is the pane's h2, "About the Company/Job" are h3, employer sections h4.
      const h4 = doc.createElement("h4");
      h4.className = "job-section-heading";
      if (node.id) h4.id = node.id;
      h4.innerHTML = node.innerHTML;
      section.appendChild(h4);
      out.appendChild(section);
      current = section;
    } else if (current) {
      current.appendChild(node);
    } else {
      out.appendChild(node);
    }
  }

  // A divider that only separates sections is decoration once sections have their own rhythm.
  out.querySelectorAll("section.job-section > hr:last-child").forEach((hr) => hr.remove());
  return out.innerHTML;
}


// ---------------------------------------------------------------------------
// Heading presentation: one semantic level, no shouted ALL-CAPS
// ---------------------------------------------------------------------------

const MINOR_WORDS = new Set(["a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with", "vs"]);

/**
 * Words that stay upper-case inside a shouted heading. A rule handles most (tokens with "&" or digits such as R&D
 * or 401K, and consonant-only tokens such as SQL, HTML, SRE); this short list covers the vowel-bearing ones that
 * ordinary-word title-casing would otherwise turn into "Icymi" or "Api".
 */
const ACRONYMS = new Set([
  "AI", "ML", "API", "APIS", "AWS", "GCP", "FAQ", "FAQS", "ICYMI", "HR", "IT", "QA", "UX", "UI", "EEO", "DEI", "ESG",
  "CEO", "CTO", "CFO", "ETL", "SaaS", "SDK", "CI", "CD", "IOT", "AR", "VR", "USA", "UK", "PTO", "RSU", "RRSP", "TFSA",
]);

function isAcronymToken(word: string): boolean {
  if (/[&\d]/.test(word)) return true;
  if (word.length >= 2 && !/[AEIOUY]/i.test(word)) return true;
  return ACRONYMS.has(word.toUpperCase());
}

/**
 * "ABOUT THE ROLE" -> "About the Role", "ICYMI" -> "ICYMI", "WHAT WE BUILD WITH AI" -> "What We Build with AI".
 * Mixed-case headings are left exactly as written. Ordinary words are never promoted to acronyms.
 */
export function normalizeAllCapsHeading(text: string): string {
  if (!/[A-Z]/.test(text) || /[a-z]/.test(text)) return text;
  let index = 0;
  return text.replace(/[A-Za-z0-9][A-Za-z0-9&'’]*/g, (word) => {
    const first = index === 0;
    index += 1;
    if (isAcronymToken(word)) return word.toUpperCase() === "SAAS" ? "SaaS" : word.toUpperCase();
    const lower = word.toLowerCase();
    return !first && MINOR_WORDS.has(lower) ? lower : lower.charAt(0).toUpperCase() + lower.slice(1);
  });
}

/**
 * Presentation pass for description fragments: every employer heading becomes one <h4 class="job-section-heading">
 * (the pane owns h2/h3) and ALL-CAPS headings are title-cased. Heading words are otherwise untouched.
 */
export function presentHeadings(html: string): string {
  if (!html || typeof DOMParser === "undefined") return html || "";
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  doc.body.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((heading) => {
    const h4 = doc.createElement("h4");
    h4.className = "job-section-heading";
    if (heading.id) h4.id = heading.id;
    h4.innerHTML = heading.innerHTML;
    const walker = doc.createTreeWalker(h4, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      node.textContent = normalizeAllCapsHeading(node.textContent || "");
    }
    heading.replaceWith(h4);
  });
  return doc.body.innerHTML;
}

// ---------------------------------------------------------------------------
// Redundant job-title headings
// ---------------------------------------------------------------------------

/** Case, spacing and trivial punctuation differences are ignored; any real wording difference is kept. */
export function normalizeTitleText(text: string): string {
  return text
    .replace(/[‘’]/g, "'")
    .replace(/[\s\u00a0]+/g, " ")
    .replace(/[^a-z0-9&+#' ]+/gi, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/**
 * Removes headings that merely repeat the page's job title (the pane already shows it as the h2).
 * Only the heading element goes; everything beneath it stays. A heading that differs in any word
 * ("Senior Data Scientist - Risk") is kept. A leading bold-only line that equals the title counts as a heading.
 */
export function removeTitleHeadings(html: string, title?: string | null): string {
  const target = title ? normalizeTitleText(title) : "";
  if (!html || !target || typeof DOMParser === "undefined") return html || "";
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  let changed = false;
  doc.body.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((heading) => {
    if (normalizeTitleText(heading.textContent || "") === target) {
      heading.remove();
      changed = true;
    }
  });
  let root: Element = doc.body;
  while (root.children.length === 1 && CONTAINER_TAGS.has(root.children[0].tagName) && root.childNodes.length === 1) root = root.children[0];
  const first = root.firstElementChild;
  if (first && first.tagName === "P" && first.children.length === 1 && /^(STRONG|B)$/.test(first.children[0].tagName)
    && normalizeTitleText(first.textContent || "") === target) {
    first.remove();
    changed = true;
  }
  return changed ? doc.body.innerHTML.trim() : html;
}

// ---------------------------------------------------------------------------
// Company intro vs. job content
// ---------------------------------------------------------------------------

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const COMPANY_VERBS =
  "is|are|was|has|have|builds?|offers?|provides?|helps?|makes?|exists|operates|serves|powers|believes|started|began|currently|empowers|delivers|creates|develops|combines|enables|works|runs";

const compact = (text: string) => text.replace(/[\s\u00a0]+/g, " ").trim();

/** "Wealthsimple is Canada's leading financial innovator..." / "At Acme, we ...": the paragraph is about the company. */
function nameAlternatives(companyName: string): string[] {
  return Array.from(
    new Set([companyName, companyName.replace(/[,.]?\s+(inc|llc|ltd|limited|corp|corporation|co|company|technologies|labs|pbc)\.?$/i, "")])
  )
    .map((n) => n.trim())
    .filter(Boolean)
    .map(escapeRegExp);
}

/** "<Company> is looking for / seeking / hiring ...": the sentence that opens the JOB, whatever the section above it was called. */
function opensJobAboutCompany(text: string, companyName: string): boolean {
  const names = nameAlternatives(companyName);
  if (names.length === 0) return false;
  const name = `(?:${names.join("|")})`;
  return new RegExp(`^(?:at\\s+)?${name}(?:[’']s)?\\s+(?:is|are|was)\\s+(?:now\\s+|currently\\s+|also\\s+|excited\\s+to\\s+be\\s+)?(?:looking|seeking|hiring|recruiting|searching|in\\s+search|in\\s+need|on\\s+the\\s+(?:hunt|lookout)|accepting|offering\\s+(?:an?|the)\\s+(?:internship|co-?op|role|position))\\b`, "i").test(compact(text));
}

function startsAboutCompany(text: string, companyName: string, allowLeadIn = true): boolean {
  // One short opening line ("Ready to do the most impactful work of your career?") may precede "At <Company>, we ...".
  if (allowLeadIn) {
    const lead = compact(text).match(/^[^.!?]{3,160}[.!?]\s+(?=\S)/);
    if (lead && startsAboutCompany(compact(text).slice(lead[0].length), companyName, false)) return true;
  }
  const names = nameAlternatives(companyName);
  if (names.length === 0) return false;
  const name = `(?:${names.join("|")})`;
  const re = new RegExp(`^(?:at\\s+)?${name}(?:[’']s)?\\b\\s*(?:,|—|–|-|(?:${COMPANY_VERBS})\\b)`, "i");
  // "NVIDIA is seeking…", "Thomson Reuters is looking for…" open the JOB, not the company story.
  return re.test(compact(text)) && !opensJobAboutCompany(text, companyName);
}

/** Phrases that open role/team content: the company introduction is over. Generic, never employer-specific. */
const JOB_SIGNAL = [
  /^we(?:'|’)re\s+(?:currently\s+)?(?:hiring|looking|seeking|searching|recruiting)\b/i,
  /^we\s+are\s+(?:currently\s+)?(?:hiring|looking|seeking|searching|recruiting)\b/i,
  /^(?:we\s+)?(?:seek|need|are\s+in\s+need\s+of)\s+(?:an?|the)\b/i,
  /^as\s+(?:an?|the|our)\s/i,
  /^in\s+this\s+(?:role|position|internship|co-?op|opportunity)\b/i,
  /^(?:this|the)\s+(?:role|position|opportunity|internship|co-?op|job)\b/i,
  /^you(?:'|’)ll\b/i,
  /^you\s+(?:will|are|have|can|may|would)\b/i,
  /^you(?:'|’)re\b/i,
  /^your\s+(?:role|impact|responsibilit|work|team|day)/i,
  /^about\s+the\s+(?:role|team|job|position|opportunity)\b/i,
  /^(?:responsibilities|requirements|qualifications|what\s+you)\b/i,
  /^(?:available\s+)?locations?\s*[:|]/i,
];

/**
 * Language about THIS opening: hiring verbs and "this role". It never belongs to a company introduction, so a
 * paragraph containing it is job text even when it opens with the company name.
 */
const HIRING_LANGUAGE =
  /\b(?:we(?:'|’)re\s+(?:currently\s+)?(?:hiring|looking|seeking)|we\s+are\s+(?:currently\s+)?(?:hiring|looking|seeking)|(?:this|the)\s+(?:role|position|job|internship|co-?op|opportunity)\b|the\s+successful\s+candidate)/i;
/** Inside a section that starts as company text, the first block that addresses the reader also ends the introduction. */
const READER_LANGUAGE = /\b(?:you(?:'|’)ll|you\s+will)\b/i;

function isJobSignal(text: string, jobTitle: string, companyName?: string): boolean {
  const t = compact(text);
  if (JOB_SIGNAL.some((re) => re.test(t))) return true;
  if (companyName && opensJobAboutCompany(t, companyName)) return true;
  return jobTitle !== "" && normalizeTitleText(t).includes(jobTitle);
}

/**
 * A company-wide statement that does not name the company: "We believe ...", "Our mission is ...". Only first person
 * plural, never addressing the reader ("you"/"your") and never mentioning the role, hiring or candidates.
 */
function isCompanyWideStatement(text: string, companyName: string): boolean {
  const t = compact(text);
  if (t.length < 20 || /\b(?:you|your|you(?:'|’)ll|role|position|candidate|hiring|hire|apply|applicant|job|internship)\b/i.test(t)) return false;
  if (/^(?:we|our)\b/i.test(t)) return true;
  // "Founded in 2019, Acme has become ..." / "Since 2012, Acme ...": company history that names the company.
  const names = nameAlternatives(companyName);
  return /^(?:founded|established|launched|since|today|with\s+(?:offices|customers|more\s+than))\b/i.test(t) && names.length > 0 && new RegExp(`\\b(?:${names.join("|")})\\b`, "i").test(t);
}

/** A short bold-only line ("Who we are") used as a heading. */
function boldOnlyHeading(el: Element): string | null {
  if (el.tagName !== "P" || el.children.length !== 1 || !/^(STRONG|B)$/.test(el.children[0].tagName)) return null;
  const text = compact(el.textContent || "");
  return text !== "" && text.length <= 60 && compact(el.children[0].textContent || "") === text ? text : null;
}

/**
 * Moves a LEADING company introduction out of the job description, and only when that is unambiguous:
 * - the intro must contain at least one confident company signal: a section/heading that is a company title
 *   ("About us", "Who we are", "About <Company>", company values/culture), or a paragraph opening with
 *   "<Company> is/are/has ..." / "At <Company>, ...";
 * - it runs up to the first job signal ("We're hiring", "As a ...", "In this role", "You will", "About the team",
 *   responsibilities/requirements, the exact job title) or the first section that is anything else;
 * - inside that range, loose text is kept with the company when it is a short lead-in hook before the first company
 *   paragraph, or a company-wide "we/our" statement after it; anything else ends the intro;
 * - if nothing confident is found, or that would leave no job content at all, nothing moves.
 * Text is never rewritten. A generic company heading ("Who are we?") is absorbed into the "About the Company"
 * heading; an employer tagline heading ("Build something people love") is kept as a sub-heading.
 */
export function separateCompanyIntro(
  html: string,
  companyName?: string | null,
  jobTitle?: string | null
): { companyHtml: string; jobHtml: string } {
  const none = { companyHtml: "", jobHtml: html || "" };
  if (!html || !companyName || typeof DOMParser === "undefined") return none;
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  const title = jobTitle ? normalizeTitleText(jobTitle) : "";
  // Employers often wrap the whole posting in one <div>; look inside it (content is preserved either way).
  let root: Element = doc.body;
  while (root.children.length === 1 && CONTAINER_TAGS.has(root.children[0].tagName) && root.childNodes.length === 1) root = root.children[0];
  const nodes = Array.from(root.childNodes).filter((n) => !(n.nodeType === 3 && !(n.textContent || "").trim()));
  if (nodes.length === 0) return none;

  const isSection = (n: Node): n is Element => n.nodeType === 1 && (n as Element).matches("section.job-section");
  const isHeading = (n: Node): n is Element => n.nodeType === 1 && /^H[1-6]$/.test((n as Element).tagName);

  const taken: Node[] = [];
  const headingsToDrop: Element[] = [];
  let confident = false;
  let hookRun: Node[] = []; // short lead-in blocks waiting for a company paragraph to confirm them
  let underCompanyHeading = false;

  scan: for (const node of nodes) {
    const el = node.nodeType === 1 ? (node as Element) : null;
    const text = compact(node.textContent || "");

    if (isSection(node)) {
      const kind = node.getAttribute("data-section");
      // A leading notice that is only a statement ("This role is for applicants actively looking to start before
      // December 1, 2026.") belongs to the job and stays where it is; the introduction after it can still be found.
      const noticeHeading = node.querySelector(":scope > h4.job-section-heading");
      if (taken.length === 0 && kind === "other" && noticeHeading && node.children.length === 1 && isInformativeHeading(noticeHeading)) continue;
      // Employers use <p> or <div> for body text; the first block that carries text decides.
      const firstBlock = Array.from(node.children).find((c) => (c.tagName === "P" || c.tagName === "DIV") && compact(c.textContent || "") !== "");
      const isCompany =
        kind === "company" ||
        (kind === "other" && firstBlock !== undefined && startsAboutCompany(firstBlock.textContent || "", companyName));
      if (!isCompany) break scan;
      // Only the introduction moves: the section is cut at its first job signal ("<Company> is looking for…",
      // "As a…", "You will…"), and everything from there on stays with the job, in order.
      const body = Array.from(node.children).filter((c) => !c.matches("h4.job-section-heading"));
      const cut = body.findIndex((c) => {
        const t = compact(c.textContent || "");
        return isJobSignal(t, title, companyName) || HIRING_LANGUAGE.test(t) || READER_LANGUAGE.test(t);
      });
      if (cut === 0) break scan; // the section's first block is already the job
      if (cut > 0) {
        const heading = node.querySelector(":scope > h4.job-section-heading");
        const intro = node.cloneNode(false) as Element;
        if (heading) intro.appendChild(heading);
        body.slice(0, cut).forEach((c) => intro.appendChild(c));
        const remainder = Array.from(node.childNodes);
        node.replaceWith(intro, ...remainder);
        if (kind === "company" && heading) headingsToDrop.push(heading);
        taken.push(...hookRun, intro);
        hookRun = [];
        confident = true;
        break scan;
      }
      if (kind === "company") headingsToDrop.push(node.querySelector(":scope > h4.job-section-heading") as Element);
      taken.push(...hookRun, node);
      hookRun = [];
      confident = true;
      underCompanyHeading = false;
      continue;
    }

    if (el && isHeading(el)) {
      const kind = classifySectionHeading(el.textContent || "", companyName);
      if (kind !== "company") break scan;
      headingsToDrop.push(el);
      taken.push(...hookRun, el);
      hookRun = [];
      confident = true;
      underCompanyHeading = true;
      continue;
    }

    const boldHeading = el ? boldOnlyHeading(el) : null;
    if (el && boldHeading) {
      const kind = classifySectionHeading(boldHeading, companyName);
      if (kind !== "company") break scan;
      headingsToDrop.push(el);
      taken.push(...hookRun, el);
      hookRun = [];
      confident = true;
      underCompanyHeading = true;
      continue;
    }

    // Loose block (paragraph, list, ...). A paragraph that opens with the company name but then addresses the reader
    // or describes this opening ("...We are looking for a Senior Data Scientist...") is job text.
    if (HIRING_LANGUAGE.test(text) || READER_LANGUAGE.test(text) || isJobSignal(text, title, companyName)) break scan;
    if (startsAboutCompany(text, companyName)) {
      taken.push(...hookRun, node);
      hookRun = [];
      confident = true;
      continue;
    }
    if (isJobSignal(text, title, companyName)) break scan;
    if (underCompanyHeading) {
      taken.push(node);
      continue;
    }
    if (confident) {
      if (isCompanyWideStatement(text, companyName)) {
        taken.push(node);
        continue;
      }
      break scan;
    }
    // Before any company paragraph: only a short lead-in hook may precede it.
    if (el && el.tagName === "P" && text.length <= 220) {
      hookRun.push(node);
      continue;
    }
    break scan;
  }

  if (!confident || taken.length === 0 || taken.length >= nodes.length) return none;

  // Headings that only announce "About the Company" are absorbed; everything else moves verbatim.
  const dropped = new Set<Node>(headingsToDrop.filter(Boolean));
  headingsToDrop.forEach((h) => h?.remove());
  const companyHtml = taken
    .filter((n) => !dropped.has(n))
    .map((n) => (isSection(n) ? n.innerHTML : n.nodeType === 1 ? (n as Element).outerHTML : n.textContent || ""))
    .join("");
  taken.forEach((n) => (n.parentNode ? n.parentNode.removeChild(n) : undefined));
  const jobHtml = root.innerHTML.trim();
  if (!compact(jobHtml.replace(/<[^>]*>/g, " ")) || !companyHtml.trim()) return none;
  return { companyHtml, jobHtml };
}

// ---------------------------------------------------------------------------
// Team / background introduction before the role itself
// ---------------------------------------------------------------------------

/** Section kinds that begin the role itself: "What you'll do", "Responsibilities", "About the role", requirements. */
const ROLE_START_KINDS = new Set(["responsibilities", "about-role", "requirements"]);

/**
 * Moves a LEADING block of team sections ("About the team" + its paragraphs) out of the job body so the page reads
 * About the Company, the team introduction, then "About the Job" starting at the role's own heading ("What you'll
 * do", "Responsibilities", "Votre rôle"...). Team content is never classed as company background; it keeps its own
 * heading and wording.
 *
 * Deliberately conservative, in line with the rest of this module:
 * - input is the structured job HTML (sections from `structureDescription`);
 * - it only acts when EVERY top-level node before the first role-start section is a team section, so loose intro
 *   paragraphs, unfamiliar headings or unstructured text always leave the description exactly as it is;
 * - nothing is rewritten, reordered or dropped: the nodes are split, in order, into two fragments.
 */
export function separateTeamIntro(html: string): { teamHtml: string; jobHtml: string } {
  const none = { teamHtml: "", jobHtml: html || "" };
  if (!html || typeof DOMParser === "undefined") return none;
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  let root: Element = doc.body;
  while (root.children.length === 1 && CONTAINER_TAGS.has(root.children[0].tagName) && root.childNodes.length === 1) root = root.children[0];
  const nodes = Array.from(root.childNodes).filter((n) => !(n.nodeType === 3 && !(n.textContent || "").trim()));
  const kindOf = (n: Node) => (n.nodeType === 1 && (n as Element).matches("section.job-section") ? (n as Element).getAttribute("data-section") : null);
  const boundary = nodes.findIndex((n) => ROLE_START_KINDS.has(kindOf(n) ?? ""));
  if (boundary <= 0) return none;
  const leading = nodes.slice(0, boundary);
  if (!leading.every((n) => kindOf(n) === "team")) return none;
  const teamHtml = leading.map((n) => (n as Element).innerHTML).join("");
  leading.forEach((n) => n.parentNode?.removeChild(n));
  const jobHtml = root.innerHTML.trim();
  if (!teamHtml.trim() || !compact(jobHtml.replace(/<[^>]*>/g, " "))) return none;
  return { teamHtml, jobHtml };
}

const REDUNDANT_JOB_HEADING = /^(?:about\s+(?:the\s+)?(?:job|role|position)|(?:job\s+)?description|a\s+propos\s+du\s+poste)$/;

/**
 * The page already titles this part "About the Job"; an employer heading that says exactly the same thing at the very
 * start would show it twice. Only that one heading element goes; everything beneath it stays.
 */
export function removeRedundantJobHeading(html: string): string {
  if (!html || typeof DOMParser === "undefined") return html || "";
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  let root: Element = doc.body;
  while (root.children.length === 1 && CONTAINER_TAGS.has(root.children[0].tagName) && root.childNodes.length === 1) root = root.children[0];
  const first = root.firstElementChild;
  if (!first) return html;
  const heading = first.matches("section.job-section") ? first.firstElementChild : first;
  if (!heading || !/^H[1-6]$/.test(heading.tagName)) return html;
  const text = foldAccents((heading.textContent || "").toLowerCase()).replace(/[\s\u00a0]+/g, " ").replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, "");
  if (!REDUNDANT_JOB_HEADING.test(text)) return html;
  if (first === heading) heading.remove();
  else if (heading.nextElementSibling || heading.nextSibling) heading.remove();
  else first.remove();
  return doc.body.innerHTML.trim();
}
