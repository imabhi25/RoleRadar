"""
Extraction and sanitization utilities for RoleRadar.
Converts ATS HTML descriptions to clean plain text and extracts technical skills.
"""

import html
from pathlib import Path
import re
import sys
from typing import List, Optional, Set
from bs4 import BeautifulSoup

# Ensure project root is in sys.path to safely import Phase 1 constants/helpers
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import CANONICAL_SKILL_NAMES

# Technical skill regex patterns with word boundary protection to prevent false positives.
# Every pattern maps to a canonical skill name defined in CANONICAL_SKILL_NAMES.
SKILL_PATTERNS = [
    (re.compile(r"(?<![\w#+])c#(?![\w#+])", re.IGNORECASE), "C#"),
    (re.compile(r"\bruby\b", re.IGNORECASE), "Ruby"),
    (re.compile(r"\b(?:apache\s+)?kafka\b", re.IGNORECASE), "Kafka"),
    (re.compile(r"\bnode(?:\.js|js)\b", re.IGNORECASE), "Node.js"),
    (re.compile(r"(?<![\w])\.net\b", re.IGNORECASE), ".NET"),
    (re.compile(r"\bkotlin\b", re.IGNORECASE), "Kotlin"),
    (re.compile(r"\bscala\b", re.IGNORECASE), "Scala"),
    (re.compile(r"\bswift\b", re.IGNORECASE), "Swift"),
    (re.compile(r"\bredis\b", re.IGNORECASE), "Redis"),
    (re.compile(r"\bmongodb\b", re.IGNORECASE), "MongoDB"),
    (re.compile(r"\b(?:apache\s+)?spark\b", re.IGNORECASE), "Spark"),
    # C++ requires special punctuation boundary handling since '+' is non-word character
    (re.compile(r"(?:^|[^\w#+])c\+\+(?:[^\w#+]|$)", re.IGNORECASE), "C++"),
    # Go / Golang: match 'golang' or 'go' when qualified by credible programming/technical context
    (
        re.compile(
            # Exact standalone 'Go' (e.g. tag, single skill field, or bullet list item)
            r"(?:^|[\r\n])\s*[-•*]?\s*go\s*(?:$|[\r\n])|"
            # Golang is always Go
            r"\bgolang\b|"
            # Go followed by technical role/layer/concept on the same line
            r"\bgo[ \t]+(?:programming(?:[ \t]+language)?|language|lang|developers?|devs?|engineers?|backend|services?|microservices?|apis?|codebase|stack|frameworks?|libraries|packages?|tools?|tooling|modules?|concurrency|goroutines?|channels)\b|"
            # Go code (avoiding non-technical 'go code of conduct')
            r"\bgo[ \t]+code\b(?![ \t]+of\b)|"
            # Experience / proficiency with Go
            r"\b(?:experience|proficiency|proficient|knowledge|skills?)[ \t]+(?:in|with|of)[ \t]+(?:the[ \t]+)?go\b|"
            # Written / developed / backend in Go
            r"\b(?:written|writing|wrote|built|build|building|develop|developed|developing|use|using|used|coded|coding|programmed|programming|backend|services?|microservices?|systems?|applications?|apps?|apis?)[ \t]+in[ \t]+go\b|"
            # Using / with Go
            r"\b(?:using|with)[ \t]+go\b(?=[ \t]*(?:to[ \t]+(?:build|develop|create|implement|deploy|write|deliver)|and|or|,|/|\.|\n|$))|"
            # Go in technical list with neighbor languages/tech on same line (no multiline leak)
            r"\b(?:python|java|rust|c\+\+|ruby|typescript|javascript|kotlin|scala|c#|sql|docker|kubernetes|k8s|graphql|postgres|postgresql|aws|gcp|azure|linux|terraform|fastapi|pytorch|html|css)[ \t]*(?:,[ \t]*(?:and[ \t]+|or[ \t]+)?|[ \t]+(?:and|or|/)[ \t]+|[ \t]*/[ \t]*)go\b|"
            r"\bgo[ \t]*(?:,[ \t]*(?:and[ \t]+|or[ \t]+)?|[ \t]+(?:and|or|/)[ \t]+|[ \t]*/[ \t]*)(?:python|java|rust|c\+\+|ruby|typescript|javascript|kotlin|scala|c#|sql|docker|kubernetes|k8s|graphql|postgres|postgresql|aws|gcp|azure|linux|terraform|fastapi|pytorch|html|css)\b|"
            # Heading lists like 'Languages: Go' or 'Skills: Java, Go'
            r"\b(?:skills?|technologies|languages?|tech[ \t]+stack|stack)[ \t]*:[ \t]*(?:[a-zA-Z0-9+#/]+[ \t]*,[ \t]*)*go\b|"
            # Title syntax like 'Software Engineer - Go' or 'Backend Engineer (Go)'
            r"\b(?:software|systems?|backend|infrastructure|cloud|platform|data)[ \t]+engineers?[ \t]*[-–—/(,][ \t]*go\b",
            re.IGNORECASE,
        ),
        "Go",
    ),
    # Java (negative lookahead to ensure JavaScript is not matched as Java)
    (re.compile(r"\bjava\b(?![\w\-])", re.IGNORECASE), "Java"),
    # JavaScript
    (re.compile(r"\b(?:javascript|ecmascript)\b", re.IGNORECASE), "JavaScript"),
    # TypeScript
    (re.compile(r"\btypescript\b", re.IGNORECASE), "TypeScript"),
    # Python
    (re.compile(r"\bpython\b", re.IGNORECASE), "Python"),
    # PostgreSQL / Postgres
    (re.compile(r"\b(?:postgresql|postgres)\b", re.IGNORECASE), "PostgreSQL"),
    # React (supports React, React.js, ReactJS, React Native; excludes English verbs and LLM ReAct frameworks)
    (
        re.compile(
            r"\b(?:react(?:\.js|js)|react\s+native)\b|"
            r"\b(?:react)\b(?!\s+(?:to\b|quickly\b|promptly\b|effectively\b|appropriately\b|calmly\b|immediately\b|faster\b|in\s+real[- ]time\b|under\s+pressure\b))(?!\s+(?:frameworks?|prompting|agents?|patterns?)\b)",
            re.IGNORECASE,
        ),
        "React",
    ),
    # Docker
    (re.compile(r"\bdocker\b", re.IGNORECASE), "Docker"),
    # Kubernetes (k8s)
    (re.compile(r"\b(?:kubernetes|k8s)\b", re.IGNORECASE), "Kubernetes"),
    # AWS
    (re.compile(r"\b(?:aws|amazon\s+web\s+services)\b", re.IGNORECASE), "AWS"),
    # GCP
    (re.compile(r"\b(?:gcp|google\s+cloud(?:\s+platform)?)\b", re.IGNORECASE), "GCP"),
    # Azure
    (re.compile(r"\b(?:azure|microsoft\s+azure)\b", re.IGNORECASE), "Azure"),
    # SQL
    (re.compile(r"\bsql\b", re.IGNORECASE), "SQL"),
    # Linux
    (re.compile(r"\blinux\b", re.IGNORECASE), "Linux"),
    # PyTorch
    (re.compile(r"\bpytorch\b", re.IGNORECASE), "PyTorch"),
    # Terraform
    (re.compile(r"\bterraform\b", re.IGNORECASE), "Terraform"),
    # GraphQL
    (re.compile(r"\bgraphql\b", re.IGNORECASE), "GraphQL"),
    # Rust
    (re.compile(r"\b(?:rust|rustlang)\b", re.IGNORECASE), "Rust"),
    # FastAPI
    (re.compile(r"\b(?:fastapi|fast-api)\b", re.IGNORECASE), "FastAPI"),
    # HTML (negative lookbehind to avoid matching file extensions like .html or URL paths /html)
    (re.compile(r"(?<![\.\/])\b(?:html|html5)\b", re.IGNORECASE), "HTML"),
    # CSS
    (re.compile(r"\b(?:css|css3)\b", re.IGNORECASE), "CSS"),
]


def sanitize_html_to_text(raw_html: Optional[str]) -> str:
    """
    Sanitizes raw HTML description into clean, readable, plain text.
    
    Removes malicious tags (script, style, iframe, etc.), converts block elements
    to line breaks, unescapes entities, and collapses excessive whitespace.
    Safely returns an empty string if input is None, empty, or whitespace.
    """
    if not raw_html or not raw_html.strip():
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove dangerous or non-content tags completely
    for tag in soup(["script", "style", "noscript", "iframe", "object", "embed", "svg"]):
        tag.decompose()

    # Prepend bullet marker to list items for clean text formatting
    for li in soup.find_all("li"):
        li_content = li.get_text().strip()
        if li_content:
            li.clear()
            li.string = f"- {li_content}"

    # Extract text with newline separator between blocks
    text = soup.get_text(separator="\n")

    # Unescape HTML entities (&amp;, &lt;, &gt;, &#39;, &nbsp;, etc.)
    text = html.unescape(text)
    # Convert non-breaking spaces to standard spaces
    text = text.replace("\xa0", " ")

    # Normalize newlines and whitespace
    lines = [line.strip() for line in text.splitlines()]
    
    # Collapse multiple consecutive blank lines into at most one blank line
    cleaned_lines: List[str] = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                cleaned_lines.append("")
                prev_blank = True
        else:
            cleaned_lines.append(line)
            prev_blank = False

    return "\n".join(cleaned_lines).strip()


def sanitize_html_description(raw_html: Optional[str]) -> str:
    """
    Sanitizes raw HTML job description to preserve safe semantic rich HTML:
    paragraphs, links, lists, headings, formatting while stripping malicious
    tags (script, iframe, style, etc.), event handlers (onclick, onload, etc.),
    and unsafe link protocols (javascript:, data:).
    If input is plain text (no HTML tags), returns the stripped text.
    """
    if not raw_html or not raw_html.strip():
        return ""

    # If raw_html contains entity-escaped HTML, unescape it
    if "&lt;" in raw_html and "&gt;" in raw_html and not re.search(r"<\s*\/?[a-zA-Z][^>]*>", raw_html):
        raw_html = html.unescape(raw_html)

    # If the input doesn't contain HTML tags, return cleanly stripped text
    if not re.search(r"<\s*\/?[a-zA-Z][^>]*>", raw_html):
        return raw_html.strip()

    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove dangerous, non-content, or tracking tags completely
    for tag in soup(["script", "style", "noscript", "iframe", "object", "embed", "svg", "form", "input", "button", "meta", "link", "base", "img"]):
        tag.decompose()

    allowed_tags = {
        "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li", "strong", "b", "em", "i", "u", "s", "strike",
        "a", "blockquote", "pre", "code", "div", "span",
        "table", "thead", "tbody", "tfoot", "tr", "th", "td"
    }

    for tag in soup.find_all(True):
        if tag.name not in allowed_tags:
            tag.unwrap()
            continue

        # Strip all event handlers and dangerous attributes
        attrs = dict(tag.attrs)
        for attr in attrs:
            if attr.lower().startswith("on") or attr.lower() in ("style", "src", "action", "formaction", "xlink:href"):
                del tag.attrs[attr]

        if tag.name == "a":
            href = (tag.get("href") or "").strip()
            # Allow safe schemes only
            if href.lower().startswith(("http://", "https://", "mailto:", "/", "#")):
                tag["href"] = href
                tag["target"] = "_blank"
                tag["rel"] = "noopener noreferrer"
            else:
                del tag["href"]
            # Remove any non-whitelisted attributes from <a>
            for attr in list(tag.attrs):
                if attr not in ("href", "target", "rel", "title"):
                    del tag[attr]
        else:
            # For non-link tags, strip attributes except id and class
            for attr in list(tag.attrs):
                if attr not in ("id", "class", "colspan", "rowspan"):
                    del tag[attr]

    return str(soup).strip()



def extract_skills(text: Optional[str]) -> List[str]:
    """
    Extracts, normalizes, and deduplicates technical skills from a text string.
    
    Matches against canonical technology patterns, prevents false positives
    (e.g., C/Go word collisions), and returns a deterministically sorted list.
    """
    if not text or not text.strip():
        return []

    matched_skills: Set[str] = set()

    for pattern, canonical_name in SKILL_PATTERNS:
        if pattern.search(text):
            # Verify canonical_name exists in canonical knowledge base
            canonical = CANONICAL_SKILL_NAMES.get(canonical_name.lower(), canonical_name)
            matched_skills.add(canonical)

    return sorted(list(matched_skills))
