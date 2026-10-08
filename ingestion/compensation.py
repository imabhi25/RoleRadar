"""Structured compensation helpers shared by ATS adapters.

Only numbers the employer published are used; nothing is estimated or inferred. The summary string matches the
style already shown for Ashby postings ("CA$154K – CA$193K"), with an explicit suffix for non-annual pay.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ingestion.pay_rules import pay_range_problem
from ingestion.pay_text import extract_pay_ranges_from_html, usable_ranges
from ingestion.places import qualifier_scope

CURRENCY_PREFIX = {"USD": "$", "CAD": "CA$", "AUD": "A$", "GBP": "£", "EUR": "€", "NZD": "NZ$", "SGD": "S$", "CHF": "CHF ", "INR": "₹"}
_INTERVALS = (("year", r"year|annual"), ("month", r"month"), ("week", r"week"), ("day", r"\bday|daily"), ("hour", r"hour|hourly"))
_SUFFIX = {"hour": " / hour", "day": " / day", "week": " / week", "month": " / month", "year": ""}


def interval_from_text(text: Optional[str]) -> Optional[str]:
    """'per-year-salary' -> 'year', 'per-hour-wage' -> 'hour'; None when the source did not say."""
    value = (text or "").lower()
    for name, pattern in _INTERVALS:
        if re.search(pattern, value):
            return name
    return None


def _money(amount: float, currency: Optional[str], symbol: Optional[str] = None) -> str:
    prefix = CURRENCY_PREFIX.get(currency.upper(), f"{currency.upper()} ") if currency else (symbol or "")
    if amount >= 1_000_000:
        millions = amount / 1_000_000
        return f"{prefix}{millions:.2f}".rstrip("0").rstrip(".") + "M"
    if amount >= 1000:
        thousands = amount / 1000
        body = f"{thousands:.1f}".rstrip("0").rstrip(".") if thousands != int(thousands) else str(int(thousands))
        return f"{prefix}{body}K"
    body = f"{amount:.2f}".rstrip("0").rstrip(".") if amount != int(amount) else str(int(amount))
    return f"{prefix}{body}"


def build_compensation(
    currency: Optional[str],
    minimum: Optional[float],
    maximum: Optional[float],
    interval: Optional[str],
    source: str,
    note: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Structured compensation dict, or None when there is no usable published figure."""
    if not currency or not isinstance(currency, str):
        return None
    lo = minimum if isinstance(minimum, (int, float)) and minimum > 0 else None
    hi = maximum if isinstance(maximum, (int, float)) and maximum > 0 else None
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None and hi < lo:
        lo, hi = hi, lo
    low, high = (lo if lo is not None else hi), (hi if hi is not None else lo)
    summary = _money(low, currency) if low == high else f"{_money(low, currency)} – {_money(high, currency)}"
    if interval in _SUFFIX:
        summary += _SUFFIX[interval]
    result: Dict[str, Any] = {
        "compensationTierSummary": summary,
        "currency": currency.upper(),
        "min": low,
        "max": high,
        "source": source,
    }
    if interval:
        result["interval"] = interval
    if note:
        result["note"] = note
    return result


def text_mentions_amount(plain_text: str, amount: float) -> bool:
    """True when the text already states this figure, so a compensation section would only repeat it."""
    whole = int(round(amount))
    if whole >= 1000:
        return str(whole) in re.sub(r"[\s,]", "", plain_text)
    return bool(re.search(rf"[$£€]\s?{whole}(?:\.\d+)?\b", plain_text))


# --------------------------------------------------------------------------------------------------------------------
# One resolution step for every posting, at ingestion and in the backfill: what the source published is kept as it came,
# and anything derived from the posting text is added beside it, marked as such.
# --------------------------------------------------------------------------------------------------------------------
_SALARY_TYPES = {"salary", "basesalary", "hourly", "wage"}
_MONEY_IN_TEXT = re.compile(r"\d")


def _interval_name(value: Any) -> Optional[str]:
    return interval_from_text(str(value)) if value not in (None, "", "NONE") else None


def structured_ranges(compensation: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every pay range in a source compensation dict (Greenhouse/Lever {min,max,ranges}, Ashby components) in one shape.
    Mirrors the parts walked by the jobber_pay_ranges SQL function, without requiring a currency or period."""
    if not isinstance(compensation, dict):
        return []
    parts: List[Dict[str, Any]] = []
    top = {k: v for k, v in compensation.items() if k != "ranges"}
    if isinstance(compensation.get("ranges"), list) and compensation["ranges"]:
        parts.extend({**top, **part} for part in compensation["ranges"] if isinstance(part, dict))
    elif "min" in compensation or "max" in compensation:
        parts.append(compensation)
    if isinstance(compensation.get("summaryComponents"), list):
        parts.extend(p for p in compensation["summaryComponents"] if isinstance(p, dict))
    for tier in compensation.get("compensationTiers") or []:
        if isinstance(tier, dict) and isinstance(tier.get("components"), list):
            parts.extend(p for p in tier["components"] if isinstance(p, dict))
    out = []
    for part in parts:
        kind = part.get("compensationType")
        if kind is not None and str(kind).lower() not in _SALARY_TYPES:
            continue
        lo = part.get("minValue", part.get("min"))
        hi = part.get("maxValue", part.get("max"))
        out.append({
            "min": lo if isinstance(lo, (int, float)) else None,
            "max": hi if isinstance(hi, (int, float)) else None,
            "currency": (part.get("currencyCode") or part.get("currency") or None),
            "interval": _interval_name(part.get("interval")),
        })
    return out


def structured_problem(compensation: Optional[Dict[str, Any]]) -> Optional[str]:
    """None when the source published at least one believable range, else the reason none can be used."""
    ranges = structured_ranges(compensation)
    if not ranges:
        return "no_amount"
    problems = [pay_range_problem(r["min"], r["max"], r["currency"], r["interval"]) for r in ranges]
    return None if any(p is None for p in problems) else problems[0]


def _text_range_entry(r: Dict[str, Any]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"min": r["min"], "max": r["max"]}
    for key in ("currency", "symbol", "interval", "label", "qualifier"):
        if r.get(key):
            entry[key] = r[key]
    if r.get("kind") == "ote":
        entry["kind"] = "ote"
    return entry


def compensation_from_text(ranges: List[Dict[str, Any]], locations: Optional[List[Dict[str, str]]] = None) -> Optional[Dict[str, Any]]:
    """Compensation dict from ranges the posting text states. Never blends ranges that differ in currency, period or place.

    A range written for a place ("for candidates based in the United States") keeps those words as ``qualifier`` and, when the job's
    locations are known, a ``scope`` saying how far the qualifier reaches over them (all / some / none / unclear). The display shows
    a qualified range as this job's pay only when its scope is "all".
    """
    use = usable_ranges(ranges)
    if not use:
        return None
    entries = [_text_range_entry(r) for r in use]
    if locations is not None:
        for entry in entries:
            if entry.get("qualifier"):
                entry["scope"] = qualifier_scope(entry["qualifier"], locations)
    groups = {(e.get("currency"), e.get("symbol") if not e.get("currency") else None, e.get("interval")) for e in entries}
    result: Dict[str, Any] = {"source": "posting_text", "ranges": entries, "evidence": use[0]["evidence"]}
    # One span only when it is honest: a single range, or several that all name the same currency and period.
    # Bare "$" ranges for different places ("for the US ... for Canada") may be different currencies: never merged.
    qualifiers = {e.get("qualifier") for e in entries}
    if len(groups) == 1 and (len(entries) == 1 or (all(e.get("currency") for e in entries) and qualifiers == {None})):
        currency, symbol, interval = next(iter(groups))
        low, high = min(e["min"] for e in entries), max(e["max"] for e in entries)
        result.update({"min": low, "max": high})
        if currency:
            result["currency"] = currency
        if symbol:
            result["symbol"] = symbol
        if interval:
            result["interval"] = interval
        summary = _money(low, currency, symbol) if low == high else f"{_money(low, currency, symbol)} – {_money(high, currency, symbol)}"
        if interval in _SUFFIX:
            summary += _SUFFIX[interval]
        if len(entries) > 1:
            summary += " · Multiple ranges"
        result["compensationTierSummary"] = summary
    else:
        parts = []
        for e in entries:
            text = _money(e["min"], e.get("currency"), e.get("symbol"))
            if e["min"] != e["max"]:
                text += f" – {_money(e['max'], e.get('currency'), e.get('symbol'))}"
            parts.append(text + (_SUFFIX.get(e.get("interval"), "")))
        result["compensationTierSummary"] = " · ".join(parts) + " · Multiple ranges"
    if any(r["kind"] == "ote" for r in use):
        result["note"] = "On-target earnings (base plus commission or bonus target), as stated in the posting."
    return result


def _non_pay_parts(summary: Any) -> List[str]:
    if not isinstance(summary, str):
        return []
    parts = [p.strip() for p in re.split(r"\s*[•·]\s*", summary) if p.strip()]
    return [p for p in parts if not (re.search(r"\d", p) and re.search(r"[$£€]|\b(?:USD|CAD|GBP|EUR|AUD)\b", p)) and p != "Multiple ranges"]


def unwrap_source_compensation(stored: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What the source itself published, from either a raw dict or one this module already resolved (idempotent)."""
    if not isinstance(stored, dict) or not stored:
        return None
    if stored.get("source") == "posting_text":
        original = stored.get("source_structured")
        return unwrap_source_compensation(original) if isinstance(original, dict) else None
    base = {k: v for k, v in stored.items() if k not in ("validation", "interval_source")}
    if stored.get("interval_source") == "posting_text":
        base.pop("interval", None)
    return base


def _enrich_interval(base: Dict[str, Any], ranges: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A figure the source published without a period takes the period the posting states next to the same figure."""
    if base.get("interval") or base.get("min") is None:
        return base
    top = base.get("max") or base["min"]
    matches = {r["interval"] for r in ranges if r.get("interval") and abs(r["min"] - base["min"]) < 0.5 and abs(r["max"] - top) < 0.5}
    if len(matches) != 1:
        return base
    interval = next(iter(matches))
    enriched = {**base, "interval": interval, "interval_source": "posting_text"}
    return enriched


def resolve_compensation(stored: Optional[Dict[str, Any]], raw_html: Optional[str], locations: Optional[List[Dict[str, str]]] = None) -> Optional[Dict[str, Any]]:
    """The compensation to store for a posting.

    1. A believable source range is kept as published (plus the period the posting states for it, when the source gave none).
    2. A placeholder or impossible source range ($1 - $2, $179,300,152) or a missing one is replaced by the ranges the posting
       text states, with the original kept under ``source_structured``.
    3. With nothing believable anywhere, an unusable source range is kept but marked ``validation``, so no display or filter
       treats it as pay and the published numbers are not lost.
    """
    base = unwrap_source_compensation(stored)
    text_ranges = extract_pay_ranges_from_html(raw_html) if raw_html and _MONEY_IN_TEXT.search(raw_html) else []
    problem = structured_problem(base) if base else "no_amount"
    if base and problem is None:
        return _enrich_interval(base, text_ranges) if text_ranges else base
    derived = compensation_from_text(text_ranges, locations)
    if derived:
        if base:
            derived["source_structured"] = base
            extras = _non_pay_parts(base.get("compensationTierSummary"))
            if extras:
                derived["compensationTierSummary"] += " · " + " · ".join(extras)
        return derived
    if base and problem != "no_amount":
        return {**base, "validation": {"status": problem}}
    return base
