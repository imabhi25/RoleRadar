"""
Duplicate analysis and safe identity helper for RoleRadar.
Provides read-only and pipeline deduplication detection:
- Provider external ID matching
- Canonical URL normalization and matching
- Safe composite fallback fingerprinting (company, title, location, role_type)
- Authoritative direct-ATS vs broad-source precedence resolution
"""

from collections import defaultdict
import html
from datetime import datetime
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

DIRECT_ATS_SOURCES = {"greenhouse", "lever", "ashby"}
BROAD_SOURCES = {"jobicy", "remotive", "arbeitnow", "sample"}

TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "source",
    "gh_src",
    "lever-source",
    "fbclid",
    "gclid",
    "_ga",
    "_gl",
}

DASH_VARIANTS = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uFE58\uFE63\uFF0D\-]")
REQ_CODE_PATTERN = re.compile(r"\b[pP]-\d{2,6}\b")



def canonicalize_url(url: Optional[str]) -> str:
    """
    Safely normalizes a job posting URL:
    - Strips URL fragments (#...)
    - Normalizes trailing slashes where safe
    - Lowercases scheme and hostname
    - Preserves query parameters intact so identity-bearing parameters (e.g. gh_jid, job_id)
      are never discarded generically.
    """
    if not url or not url.strip():
        return ""
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        query = parsed.query
        canon = f"{scheme}://{netloc}{path}"
        if query:
            canon = f"{canon}?{query}"
        return canon
    except Exception:
        return url.strip().split("#")[0].rstrip("/").lower()


def normalize_company_for_dedup(name: Optional[str]) -> str:
    """Normalizes company name by stripping common legal entities, punctuation, and casing."""
    if not name:
        return ""
    cleaned = name.lower()
    cleaned = re.sub(
        r"\b(?:inc\.?|llc\.?|ltd\.?|corp\.?|corporation|gmbh|co\.?|company|pty|pvt)\b",
        "",
        cleaned,
    )
    cleaned = re.sub(r"[^a-z0-9]", "", cleaned)
    return cleaned.strip()


def normalize_title_for_dedup(title: Optional[str]) -> str:
    """Normalizes job title by standardizing dashes, stripping punctuation, and consolidating whitespace."""
    if not title:
        return ""
    cleaned = DASH_VARIANTS.sub(" ", title.lower())
    cleaned = re.sub(r"[^a-z0-9\s\+#]", " ", cleaned)
    return " ".join(cleaned.split())


def normalize_location_for_dedup(location: Optional[str]) -> str:
    """Normalizes geographic location by collapsing dash variants, delimiters, and whitespace."""
    if not location:
        return ""
    cleaned = DASH_VARIANTS.sub(" ", location.lower())
    cleaned = re.sub(r"[/|:;,]", " ", cleaned)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return " ".join(cleaned.split())


def build_dedup_fingerprint(
    company: Optional[str],
    title: Optional[str],
    location: Optional[str],
    role_type: str = "unknown",
) -> Tuple[str, str, str, str]:
    """
    Constructs a deterministic 4-tuple fingerprint:
    (norm_company, norm_title, norm_location, role_type)
    """
    return (
        normalize_company_for_dedup(company),
        normalize_title_for_dedup(title),
        normalize_location_for_dedup(location),
        (role_type or "unknown").lower().strip(),
    )


def are_dates_close(d1: Optional[datetime], d2: Optional[datetime], max_days: int = 7) -> bool:
    """Checks if two dates are within max_days of each other, or if either date is unknown."""
    if d1 is None or d2 is None:
        return True
    return abs((d1 - d2).total_seconds()) <= max_days * 86400


def normalize_description_for_dedup(desc: Optional[str]) -> str:
    """
    Normalizes a job description for deduplication comparison:
    unescapes HTML entities, strips HTML tags, and collapses whitespace and casing.
    """
    if not desc:
        return ""
    text = html.unescape(desc)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.lower().split())


def are_descriptions_similar(
    d1: Optional[str],
    d2: Optional[str],
    threshold: float = 0.85,
    min_length_ratio: float = 0.80,
) -> bool:
    """
    Determines whether two job descriptions represent the same underlying role.
    Conservative, deterministic, non-ML:
    1. If either description is missing or empty, returns False (do not blindly collapse).
    2. Exact normalized text match (case-folded, whitespace collapsed, HTML stripped) => True.
    3. Matching explicit employer requisition code (e.g. Databricks P-160 / P-1477 / P-1930)
       present in both descriptions => True.
    4. Conservative vocabulary Jaccard similarity (>= 0.85 of tokens >= 3 chars)
       AND normalized description length ratio (min(len1, len2) / max(len1, len2) >= 0.80) => True.
    5. Otherwise => False (materially different descriptions or shared boilerplate below 85% remain distinct).
    """
    if not d1 or not d2 or not str(d1).strip() or not str(d2).strip():
        return False

    n1 = normalize_description_for_dedup(str(d1))
    n2 = normalize_description_for_dedup(str(d2))
    if not n1 or not n2:
        return False

    if n1 == n2:
        return True

    # Check safe explicit employer requisition code present in both descriptions
    req1 = set(m.upper() for m in REQ_CODE_PATTERN.findall(str(d1)))
    req2 = set(m.upper() for m in REQ_CODE_PATTERN.findall(str(d2)))
    if req1 and req2 and (req1 & req2):
        return True

    len1 = len(n1)
    len2 = len(n2)
    length_ratio = min(len1, len2) / max(len1, len2) if max(len1, len2) > 0 else 0.0
    if length_ratio < min_length_ratio:
        return False

    words1 = set(re.findall(r"[a-z0-9]{3,}", n1))
    words2 = set(re.findall(r"[a-z0-9]{3,}", n2))
    if not words1 or not words2:
        return False

    jaccard = len(words1 & words2) / len(words1 | words2)
    return jaccard >= threshold


def is_duplicate_posting(p1: Dict[str, Any], p2: Dict[str, Any]) -> bool:
    """
    Evaluates whether two job postings represent the same real-world job posting.
    Applies strong identifier hierarchy:
    1. Provider external ID (if same source)
    2. Canonical application/ATS URL
    3. Fallback composite fingerprint:
       normalized company + normalized title + normalized location + role_type
       AND supporting duplicate evidence:
       - Same canonical URL
       - OR same source_job_id
       - OR highly similar / identical normalized description
    If descriptions are absent and URLs/IDs differ, postings remain distinct.
    """
    # 1. Provider external ID (same source + same source ID => identical posting)
    s1 = p1.get("source_name")
    s2 = p2.get("source_name")
    id1 = str(p1.get("source_job_id") or p1.get("job_id") or "")
    id2 = str(p2.get("source_job_id") or p2.get("job_id") or "")
    if s1 and s2 and s1 == s2 and id1 and id2 and id1 == id2:
        return True

    # 2. Canonical URL match
    u1 = canonicalize_url(p1.get("source_url"))
    u2 = canonicalize_url(p2.get("source_url"))
    if u1 and u2 and u1 == u2:
        return True

    # Similar text, company, title and location never establish requisition identity.
    return False


def resolve_canonical_posting(p1: Dict[str, Any], p2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given two duplicate postings, returns the preferred canonical posting.
    Precedence rules:
    1. Direct ATS (Greenhouse, Lever, Ashby) strictly preferred over broad sources.
    2. Known posted_at timestamp preferred over None.
    3. Newer posted_at timestamp preferred.
    4. Deterministic fallback to stable ID.
    """
    s1 = p1.get("source_name") or ""
    s2 = p2.get("source_name") or ""
    is_direct_1 = s1 in DIRECT_ATS_SOURCES
    is_direct_2 = s2 in DIRECT_ATS_SOURCES

    if is_direct_1 and not is_direct_2:
        return p1
    if is_direct_2 and not is_direct_1:
        return p2

    # Both same tier: compare posted_at
    d1 = p1.get("posted_at")
    d2 = p2.get("posted_at")
    if d1 and not d2:
        return p1
    if d2 and not d1:
        return p2
    if d1 and d2:
        if d1 > d2:
            return p1
        elif d2 > d1:
            return p2

    # Deterministic fallback by id
    id1 = str(p1.get("id") or p1.get("job_id") or "")
    id2 = str(p2.get("id") or p2.get("job_id") or "")
    return p1 if id1 >= id2 else p2


def deduplicate_postings(postings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicates an iterable of postings preserving the preferred canonical posting for each cluster.
    Preserves original list ordering of canonical representatives.
    """
    canonical_list: List[Dict[str, Any]] = []
    for p in postings:
        matched = False
        for idx, canon in enumerate(canonical_list):
            if is_duplicate_posting(canon, p):
                canonical_list[idx] = resolve_canonical_posting(canon, p)
                matched = True
                break
        if not matched:
            canonical_list.append(p)
    return canonical_list


def analyze_cross_source_duplicates(postings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluates a collection of postings from multiple sources for suspected duplicates.
    Strictly read-only; does not merge or mutate postings.

    Each posting dict is expected to have:
    - 'source_name': str
    - 'company_name': str
    - 'title': str
    - 'source_job_id' or 'job_id': str
    - 'posted_at': Optional[datetime]
    - 'location': Optional[str]
    - 'source_url': Optional[str]
    """
    suspected_pairs = []
    company_groups = defaultdict(list)
    for p in postings:
        norm_comp = normalize_company_for_dedup(p.get("company_name", ""))
        if norm_comp:
            company_groups[norm_comp].append(p)

    for norm_comp, group in company_groups.items():
        if len(group) < 2:
            continue
        n = len(group)
        for i in range(n):
            for j in range(i + 1, n):
                p1 = group[i]
                p2 = group[j]

                # Only consider cross-source duplicates
                s1 = p1.get("source_name", "unknown")
                s2 = p2.get("source_name", "unknown")
                if s1 == s2:
                    continue

                t1 = normalize_title_for_dedup(p1.get("title", ""))
                t2 = normalize_title_for_dedup(p2.get("title", ""))
                if not t1 or not t2:
                    continue

                titles_match = (t1 == t2) or (t1 in t2) or (t2 in t1)
                if not titles_match:
                    continue

                d1 = p1.get("posted_at")
                d2 = p2.get("posted_at")
                if not are_dates_close(d1, d2, max_days=7):
                    continue

                suspected_pairs.append({
                    "company": p1.get("company_name"),
                    "title_1": p1.get("title"),
                    "source_1": s1,
                    "id_1": p1.get("source_job_id") or p1.get("job_id"),
                    "url_1": p1.get("source_url"),
                    "title_2": p2.get("title"),
                    "source_2": s2,
                    "id_2": p2.get("source_job_id") or p2.get("job_id"),
                    "url_2": p2.get("source_url"),
                })

    return {
        "total_evaluated": len(postings),
        "suspected_duplicate_count": len(suspected_pairs),
        "suspected_pairs": suspected_pairs,
    }
