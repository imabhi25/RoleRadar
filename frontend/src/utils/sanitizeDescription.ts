import { stripDecorativeEmoji } from "./stripEmoji";
import DOMPurify, { type Config } from "dompurify";

/**
 * Regex matching standard HTML element tags to distinguish genuine HTML markup
 * from plain text containing symbols like `<` (e.g. `salary > $100k < $150k` or `Map<String, Object>`).
 */
const HTML_TAG_DETECTION_REGEX =
  /<\s*\/?\s*(?:p|div|span|br|hr|h[1-6]|ul|ol|li|strong|b|em|i|u|s|strike|a|table|thead|tbody|tfoot|tr|th|td|blockquote|pre|code|section|article|header|footer|main|aside|details|summary|figure|figcaption)\b[^>]*>/i;

/**
 * Escapes HTML characters so that ordinary plain-text characters like `<` and `>`
 * are preserved as literal text rather than interpreted as markup.
 */
function escapeHtmlEntities(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Unescapes entity-encoded HTML strings (e.g. Greenhouse API returning &lt;h2&gt;...&lt;/h2&gt;).
 */
function unescapeIfEscapedHtml(raw: string): string {
  if (
    /&lt;\s*\/?\s*(?:p|div|span|h[1-6]|ul|ol|li|strong|b|em|i|a|table|section|article)\b/i.test(raw)
  ) {
    return raw
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, "&");
  }
  return raw;
}

/**
 * Some sources escape twice: the stored text holds "&amp;#xa;" (or "&amp;nbsp;"), so one round of decoding leaves the
 * literal "&#xa;" on screen. Decode those references to the characters they stand for. `<`, `>` and `&` are never
 * produced this way (they stay escaped), so this cannot introduce markup. A run of two or more line feeds is a
 * paragraph break, a single one is an ordinary space.
 */
const NAMED_DOUBLE_ESCAPED: Record<string, string> = {
  nbsp: "\u00a0", quot: '"', apos: "'", rsquo: "\u2019", lsquo: "\u2018", ldquo: "\u201c", rdquo: "\u201d",
  ndash: "\u2013", mdash: "\u2014", hellip: "\u2026", bull: "\u2022",
  // Structural characters stay escaped, so decoding can never create markup.
  amp: "&amp;", lt: "&lt;", gt: "&gt;",
};

export function decodeDoubleEscapedReferences(raw: string): string {
  if (!raw.includes("&amp;")) return raw;
  const decoded = raw
    .replace(/&amp;#(x[0-9a-f]{1,6}|\d{1,7});/gi, (whole, code: string) => {
      const point = code[0] === "x" || code[0] === "X" ? parseInt(code.slice(1), 16) : parseInt(code, 10);
      if (!Number.isFinite(point) || point === 38 || point === 60 || point === 62 || point > 0x10ffff) return whole;
      return String.fromCodePoint(point);
    })
    .replace(/&amp;([a-z]{2,8});/gi, (whole, name: string) => NAMED_DOUBLE_ESCAPED[name.toLowerCase()] ?? whole);
  // Line feeds only mean something as a separator once they are real characters.
  return decoded.replace(/(?:[ \t]*\n[ \t]*){2,}/g, "<br><br>");
}

/**
 * Safely converts Markdown formatting (bold, italic, links) into HTML markup
 * without modifying existing HTML tags or attributes.
 */
function convertMarkdownToHtml(text: string): string {
  // Convert markdown bold: **text** -> <strong>text</strong>
  let formatted = text.replace(/(?<!\*)\*\*([^*\n\r]+?)\*\*(?!\*)/g, "<strong>$1</strong>");

  // Convert markdown italic: *text* -> <em>text</em> (avoiding standalone bullet asterisks)
  formatted = formatted.replace(/(?<![*\w])\*([^*\n\r]+?)\*(?![*\w])/g, "<em>$1</em>");

  // Convert markdown links: [label](url) -> <a href="url" target="_blank" rel="noopener noreferrer">label</a>
  formatted = formatted.replace(
    /\[([^\]\n\r]+)\]\(((?:https?:\/\/|mailto:)[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  return formatted;
}

export interface ParsedSection {
  id: string;
  label: string;
  rawHeading: string;
}

export interface ParsedJobDescription {
  html: string;
  sections: ParsedSection[];
}

/**
 * Derives a clean, concise Jump To navigation label from a raw employer heading string.
 * Maps headings to recognizable standard archetypes while preserving employer meaning.
 */
export function deriveSectionLabel(text: string, companyName?: string | null): string {
  if (!text) return "Section";
  const clean = text
    .replace(/^[:?#*_\-\s]+/, "")
    .replace(/[:?#*_\-\s]+$/, "")
    .replace(/[\u2018\u2019]/g, "'")
    .trim();

  const lower = clean.toLowerCase();

  // Equal Opportunity / Diversity
  if (
    lower.includes("equal opportunity") ||
    lower.includes("equal employment") ||
    lower.includes("eeo") ||
    lower.includes("diversity & inclusion") ||
    lower.includes("diversity and inclusion")
  ) {
    return "Equal Opportunity";
  }

  // Compensation / Salary
  if (
    lower.includes("salary") ||
    lower.includes("compensation") ||
    lower.includes("pay & benefits") ||
    lower.includes("pay and benefits")
  ) {
    return "Compensation";
  }

  // Benefits / Perks / What we offer
  if (
    lower.includes("benefit") ||
    lower.includes("perk") ||
    lower.includes("what we offer")
  ) {
    return "Benefits";
  }

  // Preferred / Bonus / Nice to have
  if (
    lower.includes("preferred") ||
    lower.includes("nice to have") ||
    lower.includes("bonus")
  ) {
    return "Preferred";
  }

  // Technologies / Tech Stack
  if (
    lower.includes("technologies we use") ||
    lower.includes("tech stack") ||
    lower.includes("technologies") ||
    lower.includes("our stack")
  ) {
    return "Technologies";
  }

  // Values / What We Value
  if (
    lower.includes("what we value") ||
    lower.includes("our values") ||
    lower === "values"
  ) {
    return "Values";
  }

  // Responsibilities / What You'll Do / The Opportunity
  if (
    lower.includes("responsibilit") ||
    lower.includes("what you'll do") ||
    lower.includes("what you will do") ||
    lower.includes("what you'll be doing") ||
    lower.includes("what you will achieve") ||
    lower.includes("the opportunity") ||
    lower.includes("in this role") ||
    lower.includes("as part of this role")
  ) {
    return "Responsibilities";
  }

  // Requirements / Qualifications / What We Look For
  if (
    lower.includes("requirement") ||
    lower.includes("qualification") ||
    lower.includes("what you'll need") ||
    lower.includes("what you need") ||
    lower.includes("what we look for") ||
    lower.includes("what we're looking for") ||
    lower.includes("what we require") ||
    lower.includes("who you are") ||
    lower.includes("your background") ||
    lower.includes("skills you'll need") ||
    lower.includes("skills & experience") ||
    lower.includes("skills and experience") ||
    lower.includes("thrive in this role")
  ) {
    return "Requirements";
  }

  // Interview Process / How to Apply
  if (
    lower.includes("interview") ||
    lower.includes("how to apply") ||
    lower.includes("how we hire") ||
    lower.includes("hiring process")
  ) {
    return "Interview Process";
  }

  // The Role / About the Role
  if (
    lower === "the role" ||
    lower === "about the role" ||
    lower === "about the job" ||
    lower === "the position" ||
    lower === "about the position"
  ) {
    return "The Role";
  }

  // Team
  if (lower.includes("team") || lower.includes("our team")) {
    return "About the Team";
  }

  // About Company / Who We Are / Overview
  if (
    lower.includes("who we are") ||
    lower.includes("about us") ||
    lower.includes("about the company") ||
    lower.includes("company overview") ||
    lower.includes("our mission") ||
    lower.includes("our story") ||
    lower.includes("life at") ||
    lower.startsWith("about ")
  ) {
    if (lower.includes("life at")) {
      return clean.length <= 25 ? clean : "Life at " + (companyName || "Company");
    }
    return "About";
  }

  // Default fallback: clean heading shortened to <= 22 chars
  if (clean.length <= 22) {
    return clean;
  }
  return clean.slice(0, 20).trim() + "…";
}

/**
 * Evaluates whether text represents a recognizable section heading.
 * Returns the derived jump label and raw heading text, or null if not a heading.
 */
export function matchSectionHeading(
  text: string,
  companyName?: string | null
): { label: string; rawHeading: string } | null {
  if (!text) return null;
  const trimmed = text.trim();

  // Genuine standalone headings are concise (<= 75 chars)
  if (trimmed.length === 0 || trimmed.length > 75) return null;

  // Genuine standalone headings do not end with a sentence period
  if (trimmed.endsWith(".") && !trimmed.endsWith("...")) return null;

  const clean = trimmed
    .replace(/^[:?#*_\-\s]+/, "")
    .replace(/[:?#*_\-\s]+$/, "")
    .replace(/[\u2018\u2019]/g, "'")
    .trim();

  if (!clean) return null;

  // Reject ordinary conversational sentences
  const words = clean.split(/\s+/);
  if (
    words.length > 7 &&
    (clean.includes(",") || clean.toLowerCase().startsWith("we ") || clean.toLowerCase().startsWith("you "))
  ) {
    return null;
  }

  // A short line is not automatically a heading. Require heading syntax or
  // recognized section vocabulary; preserve ordinary employer prose as prose.
  const explicit = /^#{1,6}\s|^\*\*.+\*\*$|^__.+__$/.test(trimmed);
  const known = /^(?:about(?:\s|$)|who we are|what (?:you|we)|why (?:you|join)|the (?:role|team|position)|responsibilities|requirements|qualifications|benefits|compensation|salary|perks|nice to have|preferred qualifications|minimum qualifications|interview process|how (?:to apply|we hire)|our (?:team|mission|values)|equal opportunity)/i.test(clean);
  if (!explicit && !known) return null;
  const label = deriveSectionLabel(clean, companyName);
  return { label, rawHeading: trimmed };
}

export function isRecognizableHeading(
  text: string,
  companyName?: string | null
): boolean {
  return matchSectionHeading(text, companyName) !== null;
}

/**
 * Converts a plain-text job description into semantic HTML.
 * Handles Markdown, standalone headings, bulleted lists, and numbered lists.
 */
function convertPlainTextToHtml(plainText: string, companyName?: string | null): string {
  const normalized = plainText.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  if (!normalized) return "";

  const lines = normalized.split("\n").map((l) => l.trim());
  const htmlParts: string[] = [];
  let currentBullets: string[] = [];
  let currentNumbered: string[] = [];
  let currentParagraph: string[] = [];

  const flushParagraph = () => {
    if (currentParagraph.length > 0) {
      const paragraphHtml = currentParagraph
        .map((p) => convertMarkdownToHtml(escapeHtmlEntities(p)))
        .join("<br />");
      htmlParts.push(`<p>${paragraphHtml}</p>`);
      currentParagraph = [];
    }
  };

  const flushBullets = () => {
    if (currentBullets.length > 0) {
      const lis = currentBullets
        .map((b) => `<li>${convertMarkdownToHtml(escapeHtmlEntities(b))}</li>`)
        .join("");
      htmlParts.push(`<ul>${lis}</ul>`);
      currentBullets = [];
    }
  };

  const flushNumbered = () => {
    if (currentNumbered.length > 0) {
      const lis = currentNumbered
        .map((n) => `<li>${convertMarkdownToHtml(escapeHtmlEntities(n))}</li>`)
        .join("");
      htmlParts.push(`<ol>${lis}</ol>`);
      currentNumbered = [];
    }
  };

  const flushAll = () => {
    flushParagraph();
    flushBullets();
    flushNumbered();
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line) {
      flushAll();
      continue;
    }

    // Check for bullet list item: - , • , * , – , —
    const bulletMatch = line.match(/^[-•*–—]\s+(.*)$/);
    if (bulletMatch) {
      flushParagraph();
      flushNumbered();
      currentBullets.push(bulletMatch[1]);
      continue;
    }

    // Check for numbered list item: 1. , 1)
    const numberedMatch = line.match(/^\d+[.)]\s+(.*)$/);
    if (numberedMatch) {
      flushParagraph();
      flushBullets();
      currentNumbered.push(numberedMatch[1]);
      continue;
    }

    // Check if line is a standalone heading
    if (isRecognizableHeading(line, companyName)) {
      flushAll();
      const cleanTitle = convertMarkdownToHtml(escapeHtmlEntities(line.replace(/^#{1,6}\s+/, "")));
      htmlParts.push(`<h2>${cleanTitle}</h2>`);
      continue;
    }

    // Regular line in paragraph
    flushBullets();
    flushNumbered();
    currentParagraph.push(line);
  }

  flushAll();
  return htmlParts.join("");
}

// Configure DOMPurify hook to ensure all links safely open in a new tab with noopener/noreferrer
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.hasAttribute("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

const DOMPURIFY_CONFIG: Config = {
  RETURN_TRUSTED_TYPE: false,
  ALLOWED_TAGS: [
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "strike",
    "a",
    "span",
    "div",
    "blockquote",
    "pre",
    "code",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
  ],
  ALLOWED_ATTR: [
    "id",
    "href",
    "title",
    "target",
    "rel",
    "class",
    "colspan",
    "rowspan",
    "align",
  ],
  // Explicitly forbid executable, framing, or tracking tags
  FORBID_TAGS: [
    "script",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "style",
    "noscript",
    "meta",
    "link",
    "svg",
    "img", // Forbids tracking pixels/images
  ],
  FORBID_ATTR: ["style"],
  ALLOWED_URI_REGEXP:
    /^(?:(?:(?:f|ht)tps?|mailto|tel|callto|cid|xmpp):|[^a-z]|[-a-z+.]+(?:[^-a-z+.:]|$))/i,
};

/**
 * Checks whether an element is a recognizable section heading.
 */
function isHeadingElement(el: Element, companyName?: string | null): boolean {
  const tag = el.tagName.toUpperCase();
  const isSemanticHeading = ["H1", "H2", "H3", "H4", "H5", "H6"].includes(tag);
  const text = el.textContent?.replace(/\u00a0/g, " ").trim() || "";

  if (!text || text.length > 75) return false;

  if (isSemanticHeading) {
    return true;
  }

  // Check standalone P or DIV elements
  if (tag === "P" || tag === "DIV") {
    // Standalone headings don't have block children
    if (el.querySelector("p, div, ul, ol, li, table, blockquote, pre")) {
      return false;
    }

    // Must not end with a sentence period
    if (text.endsWith(".") && !text.endsWith("...")) {
      return false;
    }

    // Check if styled with strong/b or matches recognizable heading pattern
    const isBold = Boolean(
      el.querySelector("strong, b") ||
      (el.firstElementChild && ["STRONG", "B"].includes(el.firstElementChild.tagName))
    );

    const matchesPattern = matchSectionHeading(text, companyName) !== null;

    if (isBold || matchesPattern) {
      const words = text.split(/\s+/);
      if (words.length > 8 && text.includes(",")) {
        return false;
      }
      return true;
    }
  }

  return false;
}

/**
 * Wraps bare, orphan <li> elements (e.g. from Lever ATS) in a <ul> container.
 */
function wrapOrphanListItems(doc: Document): void {
  const bareLis = Array.from(doc.body.querySelectorAll("li")).filter(
    (li) => !li.closest("ul, ol")
  );

  if (bareLis.length === 0) return;

  let currentGroup: Element[] = [];

  const flushGroup = () => {
    if (currentGroup.length > 0) {
      const ul = doc.createElement("ul");
      const first = currentGroup[0];
      first.parentNode?.insertBefore(ul, first);
      for (const li of currentGroup) {
        ul.appendChild(li);
      }
      currentGroup = [];
    }
  };

  for (let i = 0; i < bareLis.length; i++) {
    const li = bareLis[i];
    if (currentGroup.length === 0) {
      currentGroup.push(li);
    } else {
      const prev = currentGroup[currentGroup.length - 1];
      let nextSib = prev.nextSibling;
      while (nextSib && nextSib.nodeType === 3 && !nextSib.textContent?.trim()) {
        nextSib = nextSib.nextSibling;
      }
      if (nextSib === li) {
        currentGroup.push(li);
      } else {
        flushGroup();
        currentGroup.push(li);
      }
    }
  }
  flushGroup();
}

/**
 * Converts pseudo-bullet sibling elements (e.g. <div>• &nbsp;Item</div>) into semantic <ul><li>.
 */
function convertPseudoBulletSiblings(doc: Document): void {
  const elements = Array.from(doc.body.querySelectorAll("p, div"));
  const bulletRegex = /^[\s\u00a0]*[-•*–—]\s*(.*)$/;

  let currentGroup: { el: Element; content: string }[] = [];

  const flushGroup = () => {
    if (currentGroup.length >= 2) {
      const ul = doc.createElement("ul");
      const first = currentGroup[0].el;
      first.parentNode?.insertBefore(ul, first);
      for (const item of currentGroup) {
        const li = doc.createElement("li");
        li.innerHTML = item.content;
        ul.appendChild(li);
        item.el.remove();
      }
    }
    currentGroup = [];
  };

  for (const el of elements) {
    if (!el.parentNode) continue;
    // Don't process elements with nested block children
    if (el.querySelector("p, div, ul, ol, li, table")) {
      flushGroup();
      continue;
    }

    const text = el.textContent?.replace(/\u00a0/g, " ").trim() || "";
    const match = text.match(bulletRegex);

    if (match && match[1]) {
      // Strip bullet character from innerHTML
      const cleanedInner = el.innerHTML
        .replace(/^[\s\u00a0]*(?:&bull;|&nbsp;|[-•*–—]|<span[^>]*>[-•*–—]<\/span>)\s*/i, "")
        .trim();

      if (currentGroup.length === 0) {
        currentGroup.push({ el, content: cleanedInner || match[1] });
      } else {
        const prev = currentGroup[currentGroup.length - 1].el;
        let nextSib = prev.nextSibling;
        while (nextSib && nextSib.nodeType === 3 && !nextSib.textContent?.trim()) {
          nextSib = nextSib.nextSibling;
        }
        if (nextSib === el) {
          currentGroup.push({ el, content: cleanedInner || match[1] });
        } else {
          flushGroup();
          currentGroup.push({ el, content: cleanedInner || match[1] });
        }
      }
    } else {
      flushGroup();
    }
  }
  flushGroup();
}

/**
 * Converts inline pseudo-bullets separated by <br> tags within a <p> or <div> into <ul><li> / <ol><li>.
 */
function convertInlineBrPseudoBullets(doc: Document): void {
  const elements = Array.from(doc.body.querySelectorAll("p, div"));

  for (const el of elements) {
    if (!el.parentNode) continue;
    if (!el.innerHTML.includes("<br") && !el.innerHTML.includes("<BR")) continue;

    const parts = el.innerHTML.split(/<br\s*\/?>/i).map((p) => p.trim());
    const hasBulletLines = parts.some((p) =>
      /^[\s\u00a0]*[-•*–—]\s+/.test(p.replace(/<[^>]+>/g, "").replace(/\u00a0/g, " ").trim())
    );
    const hasNumberedLines = parts.some((p) =>
      /^\d+[.)]\s+/.test(p.replace(/<[^>]+>/g, "").replace(/\u00a0/g, " ").trim())
    );

    if (hasBulletLines || hasNumberedLines) {
      const container = doc.createElement("div");
      let currentList: HTMLUListElement | HTMLOListElement | null = null;
      let currentP: HTMLParagraphElement | null = null;

      const flushP = () => {
        if (currentP) {
          container.appendChild(currentP);
          currentP = null;
        }
      };

      const flushList = () => {
        if (currentList) {
          container.appendChild(currentList);
          currentList = null;
        }
      };

      for (const part of parts) {
        if (!part) {
          flushP(); // a blank line between two plain lines is a paragraph break
          continue;
        }
        const plain = part.replace(/<[^>]+>/g, "").replace(/\u00a0/g, " ").trim();

        const bulletMatch = plain.match(/^[-•*–—]\s+(.*)$/);
        if (bulletMatch) {
          flushP();
          if (!currentList || currentList.tagName !== "UL") {
            flushList();
            currentList = doc.createElement("ul");
          }
          const li = doc.createElement("li");
          li.innerHTML = part.replace(/^(\s*<[^>]+>)*\s*[-•*–—]\s*/, "");
          currentList.appendChild(li);
          continue;
        }

        const numMatch = plain.match(/^\d+[.)]\s+(.*)$/);
        if (numMatch) {
          flushP();
          if (!currentList || currentList.tagName !== "OL") {
            flushList();
            currentList = doc.createElement("ol");
          }
          const li = doc.createElement("li");
          li.innerHTML = part.replace(/^(\s*<[^>]+>)*\s*\d+[.)]\s*/, "");
          currentList.appendChild(li);
          continue;
        }

        flushList();
        if (!currentP) {
          currentP = doc.createElement("p");
          currentP.innerHTML = part;
        } else {
          currentP.innerHTML += "<br />" + part;
        }
      }

      flushP();
      flushList();

      if (container.children.length > 0) {
        el.replaceWith(...Array.from(container.children));
      }
    }
  }
}

/**
 * Removes empty headings and standalone tracking / decorative artifacts.
 */
function cleanEmptyHeadingsAndArtifacts(doc: Document): void {
  const headings = Array.from(doc.body.querySelectorAll("h1, h2, h3, h4, h5, h6"));
  for (const h of headings) {
    const text = h.textContent?.replace(/\u00a0/g, " ").trim() || "";
    if (text.length === 0) {
      h.remove();
    }
  }

  // Remove empty paragraphs that only contain whitespace or empty spans. A span holding only a space or a
  // non-breaking space is often the ONLY separator between two words ("a<span>&nbsp;</span><b>Staff Engineer</b>"),
  // so it becomes one space instead of disappearing.
  const paras = Array.from(doc.body.querySelectorAll("p, div, span"));
  for (const p of paras) {
    if (!p.parentNode) continue;
    if (p.children.length === 0 && !p.textContent?.trim()) {
      if (p.tagName === "SPAN" && (p.textContent || "").length > 0) {
        p.replaceWith(doc.createTextNode(" "));
      } else {
        p.remove();
      }
    }
  }
}

function firstTextNode(el: Element): Text | null {
  const walker = el.ownerDocument.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: (n) => ((n.textContent || "").trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP) });
  return walker.nextNode() as Text | null;
}

function lastTextNode(el: Element): Text | null {
  const walker = el.ownerDocument.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: (n) => ((n.textContent || "").trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP) });
  let last: Text | null = null;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) last = n as Text;
  return last;
}

/** Recruiter/ATS tracking tags ("#LI-Remote", "#LI-JS5", "#LI-Hybrid"). Only the LinkedIn-style tag form is matched,
 *  so ordinary hashtags that carry meaning ("#Remote", "#BlackLivesMatter") are never touched. */
const ATS_TAG = /(^|[\s,;(\u200b])#LI-(?: (?=[A-Za-z]*\d|[A-Z]{2,}))?[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*(?=[\s,;.)\u200b]|$)/gi;
const MARKDOWN_BOLD = /\*{2,3}[ \t]*([^*\n\r]+?)[ \t]*\*{2,3}/g;

/**
 * Repairs text that leaked into the page as plain characters, without touching markup or words:
 * - ATS tags are removed (and the separators that only existed for them);
 * - "**bold**" inside HTML becomes <strong>, exactly as it already does for plain-text descriptions.
 */
function repairTextArtifacts(doc: Document): void {
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  const textNodes: Text[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) textNodes.push(node as Text);

  for (const node of textNodes) {
    const parent = node.parentElement;
    if (!parent || parent.closest("a, code, pre")) continue;
    let value = node.data;

    if (/#LI-/i.test(value)) {
      const stripped = value.replace(ATS_TAG, "$1");
      // Commas/semicolons left dangling between removed tags ("#LI-a, #LI-b") go with them.
      value = /^[\s,;\u200b]*$/.test(stripped) ? "" : stripped.replace(/[ \t]{2,}/g, " ").replace(/[\s,;]+$/, (m) => (m.includes("\n") ? "" : m.replace(/[,;]/g, "")));
      node.data = value;
    }

    if (value.includes("**") && MARKDOWN_BOLD.test(value)) {
      MARKDOWN_BOLD.lastIndex = 0;
      const fragment = doc.createDocumentFragment();
      let last = 0;
      for (const match of value.matchAll(MARKDOWN_BOLD)) {
        if (match.index! > last) fragment.appendChild(doc.createTextNode(value.slice(last, match.index)));
        const strong = doc.createElement("strong");
        strong.textContent = match[1];
        fragment.appendChild(strong);
        last = match.index! + match[0].length;
      }
      if (last < value.length) fragment.appendChild(doc.createTextNode(value.slice(last)));
      node.replaceWith(fragment);
    }
    MARKDOWN_BOLD.lastIndex = 0;
  }

  // Emphasis markers that wrap several inline nodes ("**This is hybrid, see <a>our office</a>.**") or that were left
  // unpaired ("***Please note ...") cannot be matched inside one text node. They are markup leaking as characters.
  doc.body.querySelectorAll("p, li").forEach((block) => {
    const text = (block.textContent || "").trim();
    if (!text.includes("*")) return;
    const first = firstTextNode(block);
    const last = lastTextNode(block);
    if (!first || !last) return;
    const opens = /^\s*\*{2,3}\s*/.test(first.data);
    const closes = /\s*\*{2,3}\s*$/.test(last.data);
    const stars = (text.match(/\*/g) || []).length;
    const markerStars = (text.match(/^\s*\*+/)?.[0].replace(/\s/g, "").length || 0) + (text.match(/\*+\s*$/)?.[0].replace(/\s/g, "").length || 0);
    if (stars !== markerStars) return; // other asterisks in the text: not a clean wrapper
    if (opens) first.data = first.data.replace(/^\s*\*{2,3}\s*/, "");
    if (closes && last !== first) last.data = last.data.replace(/\s*\*{2,3}\s*$/, "");
    else if (closes && opens) first.data = first.data.replace(/\s*\*{2,3}\s*$/, "");
    else if (closes) last.data = last.data.replace(/\s*\*{2,3}\s*$/, "");
    if (opens && closes && !block.querySelector("strong, b") && block.firstChild) {
      const strong = doc.createElement("strong");
      while (block.firstChild) strong.appendChild(block.firstChild);
      block.appendChild(strong);
    }
  });

  // A paragraph or line that held nothing but tracking tags is now empty.
  doc.body.querySelectorAll("p, div, li, span").forEach((el) => {
    if (el.children.length === 0 && !(el.textContent || "").replace(/[\s\u200b]/g, "") && el.tagName !== "SPAN") el.remove();
  });
}

const BLOCK_TAGS = new Set([
  "P", "DIV", "UL", "OL", "LI", "H1", "H2", "H3", "H4", "H5", "H6", "TABLE", "BLOCKQUOTE", "PRE", "HR", "SECTION",
  "ARTICLE", "HEADER", "FOOTER", "MAIN", "ASIDE", "DETAILS", "FIGURE", "FORM", "DL",
]);

/**
 * Some tenants (RBC Workday) wrap every label in a dozen or more nested <div>s ("<div><div><p><b>Address:</b></p></div></div>"
 * followed by the value as loose text). A <div> whose only content is one block element is pure layout, so it is
 * replaced by that element. Without this the label looks like an orphan with no content of its own and its value
 * loses its meaning.
 */
function collapseSingleChildWrappers(doc: Document): void {
  const singleBlock = /^(?:DIV|P|UL|OL|TABLE|H[1-6]|BLOCKQUOTE|SECTION)$/;
  let changed = true;
  while (changed) {
    changed = false;
    doc.body.querySelectorAll("div").forEach((div) => {
      if (!div.parentNode) return;
      const nodes = Array.from(div.childNodes).filter((n) => !(n.nodeType === 3 && !(n.textContent || "").trim()) && n.nodeType !== 8);
      if (nodes.length === 1 && nodes[0].nodeType === 1 && singleBlock.test((nodes[0] as Element).tagName)) {
        div.replaceWith(nodes[0]);
        changed = true;
      }
    });
  }
}

/**
 * Bare text (plus <br> line breaks and inline tags) directly under the body, as Amazon and some Workday tenants
 * publish, becomes ordinary paragraphs. Nothing is removed; this only gives later passes (list detection, section
 * detection, empty-node cleanup) a real block to work on instead of loose <br> elements they would discard.
 */
function wrapTopLevelInlineRuns(doc: Document): void {
  const nodes = Array.from(doc.body.childNodes);
  const hasBareText = nodes.some((n) => n.nodeType === 3 && (n.textContent || "").trim() !== "");
  if (!hasBareText) return;
  let run: Node[] = [];
  const flush = () => {
    if (run.length === 0) return;
    const meaningful = run.some((n) => (n.nodeType === 3 ? (n.textContent || "").trim() !== "" : (n as Element).tagName !== "BR"));
    if (meaningful) {
      const p = doc.createElement("p");
      run[0].parentNode!.insertBefore(p, run[0]);
      run.forEach((n) => p.appendChild(n));
    } else {
      run.forEach((n) => n.parentNode?.removeChild(n));
    }
    run = [];
  };
  for (const node of nodes) {
    const isBlock = node.nodeType === 1 && BLOCK_TAGS.has((node as Element).tagName);
    if (isBlock) flush();
    else run.push(node);
  }
  flush();
}

/**
 * Disambiguates jump navigation labels to prevent duplicate ambiguous pills like [About] [About].
 */
function disambiguateLabels(sections: ParsedSection[]): void {
  const labelCounts: Record<string, number> = {};
  for (const s of sections) {
    labelCounts[s.label] = (labelCounts[s.label] || 0) + 1;
  }

  for (const s of sections) {
    if (labelCounts[s.label] > 1) {
      // Differentiate using clean words from the raw heading
      const cleanRaw = s.rawHeading
        .replace(/^[:?#*_\-\s]+/, "")
        .replace(/[:?#*_\-\s]+$/, "")
        .trim();

      if (cleanRaw.length <= 22) {
        s.label = cleanRaw;
      } else {
        const words = cleanRaw.split(/\s+/).slice(0, 3).join(" ");
        s.label = words.length <= 22 ? words : words.slice(0, 20) + "…";
      }
    }
  }
}

/**
 * Inspects a sanitized HTML document tree:
 * 1. Removes empty headings and tracking tags
 * 2. Wraps bare/orphan <li> tags in <ul>
 * 3. Converts pseudo-bullets into semantic lists
 * 4. Normalizes section headings to semantic <h2> with anchor IDs
 * 5. Extracts structured sections for Jump To navigation with disambiguated labels
 */
function processAndExtractSections(
  cleanHtml: string,
  companyName?: string | null
): ParsedJobDescription {
  if (typeof DOMParser === "undefined") {
    return { html: cleanHtml, sections: [] };
  }

  const parser = new DOMParser();
  const doc = parser.parseFromString(`<body>${cleanHtml}</body>`, "text/html");

  // Step 0: layout-only wrapper chains are flattened, loose top-level text becomes paragraphs, and leaked
  // ATS tags / **bold** markers are repaired
  collapseSingleChildWrappers(doc);
  wrapTopLevelInlineRuns(doc);
  repairTextArtifacts(doc);

  // Step 1: Clean empty headings and tracking artifacts
  cleanEmptyHeadingsAndArtifacts(doc);

  // Step 2: Wrap orphan <li> tags in <ul>
  wrapOrphanListItems(doc);

  // Step 3: Convert sibling pseudo-bullet elements into semantic <ul><li>
  convertPseudoBulletSiblings(doc);

  // Step 4: Convert inline <br> pseudo-bullets into semantic lists
  convertInlineBrPseudoBullets(doc);

  // Step 5: Identify section headings and assign anchor IDs
  const sections: ParsedSection[] = [];
  let sectionIndex = 0;

  const candidateElements = Array.from(doc.body.querySelectorAll("h1, h2, h3, h4, h5, h6, p, div"));

  for (const el of candidateElements) {
    if (!el.parentNode) continue;

    if (isHeadingElement(el, companyName)) {
      const text = el.textContent?.replace(/\u00a0/g, " ").trim() || "";
      if (!text) continue;

      const id = `section-${sectionIndex++}`;
      const h2 = doc.createElement("h2");
      h2.id = id;
      h2.className = "job-section-heading";
      // Preserve the source employer's exact heading text and styling
      h2.innerHTML = el.innerHTML;
      el.replaceWith(h2);

      const label = deriveSectionLabel(text, companyName);
      sections.push({
        id,
        label,
        rawHeading: text,
      });
    }
  }

  // Step 6: Disambiguate any duplicate labels
  disambiguateLabels(sections);

  return {
    html: doc.body.innerHTML,
    sections,
  };
}

/**
 * Sanitizes, normalizes, and extracts structured sections from a job description.
 *
 * @param rawDescription The raw description from the API (HTML, plain text, null, or undefined).
 * @param companyName Optional company name for context-aware heading matching (e.g. "About Ramp").
 * @returns ParsedJobDescription containing safe sanitized HTML and extracted sections.
 */
export function parseAndSanitizeJobDescription(
  rawDescription: string | null | undefined,
  companyName?: string | null
): ParsedJobDescription {
  if (!rawDescription || !rawDescription.trim()) {
    return { html: "", sections: [] };
  }

  // Unescape entity-encoded HTML tags if present (e.g. &lt;h2&gt;)
  const unescaped = decodeDoubleEscapedReferences(unescapeIfEscapedHtml(rawDescription.trim()));
  const isHtml = HTML_TAG_DETECTION_REGEX.test(unescaped);

  // If plain text, convert newlines, markdown, and pseudo-structures to HTML
  const preprocessed = isHtml
    ? unescaped
    : convertPlainTextToHtml(unescaped, companyName);

  // Sanitize with DOMPurify
  const sanitized = DOMPurify.sanitize(preprocessed, DOMPURIFY_CONFIG);
  const cleanHtml = typeof sanitized === "string" ? sanitized : String(sanitized);

  // Decorative emoji are dropped for display (before heading detection, so "🌴 Benefits" is just "Benefits")
  const withoutEmoji = stripDecorativeEmoji(cleanHtml);

  // Extract sections and normalize presentation
  return processAndExtractSections(withoutEmoji, companyName);
}

/**
 * Legacy wrapper returning just the sanitized HTML string.
 */
export function sanitizeJobDescription(
  rawDescription: string | null | undefined,
  companyName?: string | null
): string {
  return parseAndSanitizeJobDescription(rawDescription, companyName).html;
}
