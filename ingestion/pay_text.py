"""Pay ranges an employer wrote into the posting text, for postings whose ATS gave no usable structured pay.

Rules (nothing is inferred):

* A range needs two amounts and a money signal (a currency symbol or code), and the words just before it must be about
  pay ("salary range", "Pay Details", "Wage Notice"), not equity, bonuses, benefits or company funding.
* The currency is recorded only when the text names it (``CAD``, ``CA$``, ``£``). A bare ``$`` stays a bare ``$``.
* The pay period is recorded only when the text names it next to that range ("per year", "hourly", "/hr", "annually").
  A figure with no stated period stays periodless; it is never assumed to be annual or hourly.
* Ranges tied to different places or levels ("for the US ... for Canada", "I4 ... I5") are kept as separate ranges with
  the qualifying words; nothing is blended and no location is chosen for the reader.
* On-target-earnings ranges are labelled as such and are only used when the posting states no base range.
* Every range carries the sentence it came from, so the figure can always be checked against the posting.
"""
from __future__ import annotations

import html as html_lib
import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from ingestion.pay_rules import pay_range_problem
from ingestion.places import place_tokens

_CODES = r"USD|CAD|AUD|GBP|EUR|NZD"
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_SYMBOL = r"(?:US|CA|C|A|NZ|AU)?\$|£|€"
_SEP = r"(?:\s*(?:-|–|—|‒|to)\s*|\s+and\s+)"
_RANGE = re.compile(
    rf"(?<![\w$£€.,])(?:(?P<c0>{_CODES})\s*)?(?P<s1>{_SYMBOL})?\s*(?P<n1>{_NUM})\s*(?P<k1>[kK](?![a-z]))?\s*\(?(?P<c1>{_CODES})?\)?"
    rf"{_SEP}"
    rf"(?:(?P<c2>{_CODES})\s*)?(?P<s2>{_SYMBOL})?\s*(?P<n2>{_NUM})\s*(?P<k2>[kK](?![a-z]))?\s*\(?(?P<c3>{_CODES})?\)?(?![\w])",
    re.I,
)
_PAY_WORDS = re.compile(
    r"\b(?:pay|salary|salaries|compensation|wage|wages|base|rate|range|ote|earnings|remuneration|hourly|annual)\b", re.I
)
_NOT_PAY_WORDS = re.compile(
    r"\b(?:equity|stock|rsus?|bonus(?:es)?|sign[- ]?on|signing|allowance|reimburse\w*|grants?|funding|raised|valuation|revenue|budget|"
    r"benefits?|401|relocation|tuition|perks?|wellness|stipend|expenses?|discounts?|credits?|per diem|investment|series [a-z])\b",
    re.I,
)
_OTE = re.compile(r"\b(?:ote|on[- ]target|total cash|commission)\b", re.I)
_PERIODS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("year", re.compile(
        r"\bannual(?:ly)?\b(?!\s+(?:performance|bonus|incentive|review|equity|stock|grant|merit|increase|leave|vacation|pto|refresh|cycle|target|plan|rsu|compensation\s+review|salary\s+review))"
        r"|\bper\s+(?:year|annum)\b|/\s*(?:year|yr)\b|\ba\s+year\b|\byearly\b|\beach\s+year\b|\bp\.a\.", re.I)),
    ("hour", re.compile(r"\bhourly\b|\bper\s+hour\b|/\s*(?:hour|hr)\b|\ban\s+hour\b", re.I)),
    ("month", re.compile(r"\bmonthly\b|\bper\s+month\b|/\s*month\b|\ba\s+month\b", re.I)),
    ("week", re.compile(r"(?<!bi-)(?<!bi)\bweekly\b|\bper\s+week\b|/\s*week\b|\ba\s+week\b", re.I)),
    ("day", re.compile(r"\bdaily\b|\bper\s+day\b|/\s*day\b|\ba\s+day\b", re.I)),
)
_SEGMENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9$£€•-])")
_QUALIFIER = re.compile(
    r"^\s*(?:,\s*)?((?:for|in|within|located in|based in)\s+(?:the\s+)?"
    r"(?:Level\s+[0-9IVX]+|[A-Z][\w.&'-]*(?:,?\s+(?:and\s+)?[A-Z][\w.&'-]*){0,5}))(?=\s*(?:[.;,]|\band\b|\bplus\b|\+|$))")
# Place qualifiers written in front of the amounts. The words are kept verbatim; nothing is mapped to a location here.
_LEAD_QUALIFIERS = [
    re.compile(r"(?:[Ff]or|[Ii]n)\s+(?:the\s+)?(?:candidates|employees|hires|roles?|positions?|those)?\s*(?:that are\s+|who are\s+)?(?:located|based|residing|working)\s+in\s+(?:the\s+)?[A-Z][^,:;.]{1,70}"),
    re.compile(r"[Ii]n\s+the\s+[A-Z][\w.&' -]{1,40}?\s+(?:area|market|metro|region|zone)\b"),
    re.compile(r"[Ff]or\s+(?:the\s+)?[A-Z][\w.&'-]*(?:[ .-]+[A-Z][\w.&'-]*)*[ -]based\s+(?:roles|hires|employees|candidates|positions)"),
    re.compile(r"^(?:[Ii]n|[Ff]or)\s+(?:the\s+|any\s+eligible\s+)?[A-Z][^:;]{1,70}?(?=,\s+(?:the|we|our|base|pay|salary|compensation|unless|this|all|a|an|your)\b)"),
    re.compile(r"[Tt]he\s+(?:United States|US|U\.S\.|Canada|Canadian|[A-Z][a-z]+(?: [A-Z][a-z]+)*(?:, [A-Z]{2})?)(?=\s+(?:yearly|annual|base|hourly|salary|pay|compensation))"),
    re.compile(r"^[A-Z][\w.&' ,-]{1,40}?(?=:\s+(?:the|pay|salary|base|estimated))"),
]
_PREFIX_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 /&.,'-]{0,38}$")
_PARENS = re.compile(r"\([^)]*\)")
MAX_EVIDENCE = 400


_BLOCKS = ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "section", "article", "br", "blockquote", "dd", "dt"]


def html_to_blocks(raw_html: Optional[str]) -> str:
    """Plain text with a line break at every block boundary only. Inline tags (<strong>, <span>) do not split a sentence,
    which ``sanitize_html_to_text`` does (it breaks at every text node and would cut "$200,700 - $250,900" in two)."""
    if not raw_html or not raw_html.strip():
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "object", "embed", "svg"]):
        tag.decompose()
    for tag in soup.find_all(_BLOCKS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = html_lib.unescape(soup.get_text(separator="")).replace("\xa0", " ").replace("\u200b", "")
    return "\n".join(re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines() if line.strip())


def _amount(number: str, k: Optional[str]) -> float:
    value = float(number.replace(",", ""))
    return value * 1000 if k else value


def _currency(symbol: Optional[str], *codes: Optional[str]) -> Optional[str]:
    for code in codes:
        if code:
            return code.upper()
    if symbol:
        sym = symbol.upper().rstrip("$")
        explicit = {"US": "USD", "CA": "CAD", "C": "CAD", "A": "AUD", "AU": "AUD", "NZ": "NZD"}
        if symbol == "£":
            return "GBP"
        if symbol == "€":
            return "EUR"
        return explicit.get(sym)
    return None


def _period(text: str) -> Optional[str]:
    found = {name for name, pattern in _PERIODS if pattern.search(text)}
    return next(iter(found)) if len(found) == 1 else None


def _segments(text: str) -> List[str]:
    segments: List[str] = []
    for line in re.split(r"\n+", text):
        line = line.strip()
        if line:
            segments.extend(part.strip() for part in _SEGMENT_END.split(line) if part.strip())
    return segments


def _lead_is_pay(lead: str) -> bool:
    """The last topic word before the amounts decides: "salary range ... is" is pay, "equity ... bonus" is not."""
    cleaned = _PARENS.sub(" ", lead)
    last_pay = last_other = -1
    for m in _PAY_WORDS.finditer(cleaned):
        last_pay = m.start()
    for m in _NOT_PAY_WORDS.finditer(cleaned):
        last_other = m.start()
    return last_pay >= 0 and last_pay > last_other


def _geo_qualifier(before: str, after: str, heading: str) -> Optional[str]:
    """The place qualifier the employer wrote for this range, verbatim, or None. A qualifier is recognised by its shape
    ("for candidates based in X", "in the X area", "For X-based roles", "In X,", "X:") or, failing that, by naming a known place."""
    lead = before.strip()
    for pattern in _LEAD_QUALIFIERS:
        m = pattern.search(lead)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip(" :,;")
    trailing = _QUALIFIER.match(after)
    if trailing and not re.match(r"(?:for|in|within)\s+Level\b", trailing.group(1)):
        return re.sub(r"\s+", " ", trailing.group(1)).strip(" .,;:")
    if heading and place_tokens(heading) and len(heading) <= 70:
        return re.sub(r"\s+", " ", heading).strip(" :,;")           # a line above: "United States Salary Range", "US employees (any location):"
    if lead and place_tokens(lead) and len(lead) <= 120:
        return re.sub(r"\s+", " ", re.sub(r"\s+(?:estimated|expected|base|pay|salary|range).*$", "", lead, flags=re.I)).strip(" :,;-") or None
    return None


def extract_pay_ranges_from_html(raw_html: Optional[str]) -> List[Dict[str, Any]]:
    return extract_pay_ranges(html_to_blocks(raw_html))


def extract_pay_ranges(plain_text: str) -> List[Dict[str, Any]]:
    """Explicit pay ranges in a posting's plain text (see module docstring). Empty when there is none."""
    segments = _segments(plain_text or "")
    found: List[Dict[str, Any]] = []
    last_accepted = -10
    for index, segment in enumerate(segments):
        # Label or lead-in lines directly above this one ("Annual Base Salary", "Canadian employees (any location):"),
        # back to the previous line that already holds figures.
        lead_lines: List[str] = []
        k = index - 1
        while k >= 0 and len(lead_lines) < 3 and not re.search(r"\d", segments[k]) and len(segments[k]) <= 240:
            lead_lines.insert(0, segments[k])
            k -= 1
        previous_context = " ".join(lead_lines)
        follows_accepted = k == last_accepted
        cursor = 0
        accepted_in_segment = 0
        for match in _RANGE.finditer(segment):
            if not any(match.group(g) for g in ("s1", "s2", "c0", "c1", "c2", "c3")):
                continue  # "3 - 5" or "2020 - 2025": no money signal
            lo = _amount(match.group("n1"), match.group("k1"))
            hi = _amount(match.group("n2"), match.group("k2"))
            before = segment[cursor:match.start()]
            clean_before = _PARENS.sub(" ", before)
            continuation = (
                accepted_in_segment > 0 and len(before) <= 110 and not _SEGMENT_END.search(before) and not _NOT_PAY_WORDS.search(clean_before)
            )
            # The amounts may sit on their own line under a lead-in sentence or label.
            under_label = (
                accepted_in_segment == 0 and len(before.strip()) <= 60 and not _NOT_PAY_WORDS.search(clean_before)
                and (_lead_is_pay(previous_context) or (follows_accepted and bool(lead_lines)))
            )
            if not (_lead_is_pay(before) or continuation or under_label):
                cursor = match.end()
                continue
            if lo <= 0 or hi <= 0:
                cursor = match.end()
                continue
            after = segment[match.end():match.end() + 28]
            local = f"{before[-160:]} {match.group(0)} {after}"
            local_period_text = _PARENS.sub(" ", local)
            period = _period(local_period_text) or (_period(previous_context) if under_label else None)
            if period is None and continuation and found:
                # "Annual Base Salary $A - $B for the US and $C - $D for Canada": the lead-in governs both ranges.
                period = found[-1]["interval"]
            currency = _currency(match.group("s2") or match.group("s1"), match.group("c0"), match.group("c1"), match.group("c2"), match.group("c3"))
            symbol = (match.group("s2") or match.group("s1") or "").upper() or None
            lo, hi = (hi, lo) if lo > hi else (lo, hi)
            geo = _geo_qualifier(before, segment[match.end():], lead_lines[-1] if (under_label and lead_lines) else "")
            level = re.match(r"\s*(?:,\s*)?(for\s+Level\s+[0-9IVX]+)", segment[match.end():])
            label = level.group(1) if level else None
            if not label:
                # "Level 2:", "I5", "Canadian employees (any location):" in front of the amounts name the range.
                tail = re.sub(r"^[\s:,;–—-]+|[\s:,;–—-]+$", "", before).strip()
                if not tail and under_label and lead_lines:
                    tail = re.sub(r"[\s:,;–—-]+$", "", lead_lines[-1]).strip()
                if tail and _PREFIX_LABEL.match(tail) and not _PAY_WORDS.search(tail) and not _NOT_PAY_WORDS.search(tail) and not re.fullmatch(r"(?:and|or|&|is|are|of|between)", tail, re.I):
                    if place_tokens(tail):
                        geo = geo or tail
                    else:
                        label = tail                                  # a level, role or zone: "Level 4", "I5", "Zone A"
            ote = bool(_OTE.search(_PARENS.sub(" ", before[-120:])))
            found.append({
                "min": lo, "max": hi, "currency": currency, "symbol": symbol, "interval": period,
                "kind": "ote" if ote else "base", "label": label, "qualifier": geo,
                "evidence": segment[:MAX_EVIDENCE].strip(),
            })
            accepted_in_segment += 1
            last_accepted = index
            cursor = match.end()
    # Identical statements (one per language, or repeated) are one range.
    unique: List[Dict[str, Any]] = []
    for item in found:
        key = (item["min"], item["max"], item["currency"], item["interval"], item["kind"])
        if not any((u["min"], u["max"], u["currency"], u["interval"], u["kind"]) == key for u in unique):
            unique.append(item)
    return unique


def usable_ranges(ranges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Base ranges, or on-target-earnings ranges when there is no base range, minus anything that cannot be real pay."""
    sane = [r for r in ranges if pay_range_problem(r["min"], r["max"], r.get("currency"), r.get("interval")) is None]
    base = [r for r in sane if r["kind"] == "base"]
    return base or sane
