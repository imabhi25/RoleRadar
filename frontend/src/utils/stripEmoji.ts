/**
 * Display-only removal of decorative emoji from job descriptions.
 *
 * Plain symbols that carry meaning are kept: (c) (r) (tm), arrows, check marks, geometric bullets and
 * ASCII punctuation. Stored descriptions are never modified; this runs on rendered HTML only.
 */

// Extended_Pictographic also matches some text-like symbols we want to keep, so those are excluded up front.
const KEEP = "\\u00A9\\u00AE\\u2122\\u2713\\u2714\\u2022\\u2190-\\u21FF\\u25A0-\\u25FF";
const EMOJI_UNIT = `(?:(?![${KEEP}])\\p{Extended_Pictographic}|\\p{Regional_Indicator})(?:\\uFE0F|\\p{Emoji_Modifier})?`;
const EMOJI_SEQUENCE = `(?:[0-9#*]\\uFE0F?\\u20E3|${EMOJI_UNIT}(?:\\u200D${EMOJI_UNIT})*)`;
// A run of emoji plus the whitespace hugging it, so removal never leaves double spaces.
const EMOJI_RUN = new RegExp(`\\s*(?:${EMOJI_SEQUENCE}\\s*)+|(?:\\uFE0F|\\u200D|\\u20E3)`, "gu");

/** Removes decorative emoji from plain text, keeping the words and sensible spacing around them. */
export function stripEmojiText(text: string): string {
  if (!text) return text;
  return text.replace(EMOJI_RUN, (match, offset: number, whole: string) => {
    const before = whole[offset - 1];
    const after = whole[offset + match.length];
    if (!before || !after) return "";
    return /\s/.test(match) && !/[.,;:!?)\]}]/.test(after) ? " " : "";
  });
}

const BLOCK_TAGS = new Set(["P", "LI", "H1", "H2", "H3", "H4", "H5", "H6", "DIV", "TD", "TH", "BLOCKQUOTE", "SECTION"]);
const KEEP_EMPTY = "img, hr, br, table, ul, ol, svg, video, iframe, picture, canvas";

function removeIfEmpty(el: Element | null): void {
  while (el && el.tagName !== "BODY") {
    const empty = (el.textContent || "").replace(/[\s\u00a0\u200b]+/g, "") === "" && !el.matches(KEEP_EMPTY) && !el.querySelector(KEEP_EMPTY);
    if (!empty) return;
    const parent = el.parentElement;
    el.remove();
    el = parent;
  }
}

/** Strips decorative emoji from every text node of an HTML fragment and tidies nodes left empty. */
export function stripDecorativeEmoji(html: string): string {
  if (!html || typeof DOMParser === "undefined") return html || "";
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  const textNodes: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) textNodes.push(n as Text);

  let changed = false;
  const touchedParents: Element[] = [];
  textNodes.forEach((node) => {
    const original = node.nodeValue || "";
    let cleaned = stripEmojiText(original);
    if (cleaned === original) return;
    changed = true;
    // an emoji at the very start of a block leaves stray leading whitespace behind
    const parent = node.parentElement;
    if (parent && BLOCK_TAGS.has(parent.tagName) && parent.firstChild === node) cleaned = cleaned.replace(/^\s+/, "");
    node.nodeValue = cleaned;
    if (parent) touchedParents.push(parent);
  });
  if (!changed) return html;

  touchedParents.forEach((parent) => {
    if (parent.isConnected) removeIfEmpty(parent);
  });
  // "<strong>emoji</strong> 20 days": the text after a removed inline node starts with a stray space
  doc.body.querySelectorAll(Array.from(BLOCK_TAGS).map((t) => t.toLowerCase()).join(",")).forEach((block) => {
    const first = block.firstChild;
    if (first && first.nodeType === Node.TEXT_NODE) first.nodeValue = (first.nodeValue || "").replace(/^\s+/, "");
  });
  return doc.body.innerHTML;
}
