"""
Simplify discovery for RoleRadar.

SimplifyJobs publishes community-maintained internship / new-grad listings as JSON
(``.github/scripts/listings.json`` in each repository). RoleRadar uses them purely as a
DISCOVERY source. Simplify is never the source of truth:

    Simplify listing
      -> discovery candidate (this module, table ``discovery_candidates``)
      -> identify company + resolve the employer / ATS URL
      -> verify the posting really exists on the official source
      -> only then can it be ingested by the normal official-source pipeline

A candidate is never inserted into ``job_postings`` here. The only write to
``job_postings`` this module can make is attaching a *real* Simplify listing URL as a
secondary apply route to a job that was already ingested from its official source.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
import json
import logging
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
import urllib.parse

from ingestion.clients import get_ats_client
from ingestion.clients.workday import parse_workday_job_url
from ingestion.company_resolver import normalize_company_name
from ingestion.discovery import parse_ats_url
from ingestion.http_client import HardenedHttpClient, IngestionFetchError
from ingestion.normalizer import (
    EARLY_CAREER_ROLE_TYPES,
    ELIGIBLE_COUNTRIES,
    canonicalize_apply_url,
    classify_role_type,
    extract_academic_term,
    is_simplify_job_url,
    is_swe_role,
    is_user_facing_location_eligible,
    normalize_job_locations,
)

logger = logging.getLogger("ingestion.simplify")

RAW_BASE = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"

# kind drives the role-type hint: an internship repo lists internships, a new-grad repo new grads.
SIMPLIFY_SOURCES: List[Dict[str, str]] = [
    {"repo": "SimplifyJobs/Summer2027-Internships", "branch": "dev", "path": ".github/scripts/listings.json", "kind": "internship"},
    {"repo": "SimplifyJobs/New-Grad-Positions", "branch": "dev", "path": ".github/scripts/listings.json", "kind": "new_grad"},
]

STATUSES = (
    "discovered", "already_known", "official_url_resolved", "verified", "unsupported_source",
    "official_not_found", "closed", "invalid", "deferred",
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

# Hosts that only aggregate/relay listings: never an employer's own posting.
AGGREGATOR_HOSTS = (
    "linkedin.com", "indeed.com", "glassdoor.", "ziprecruiter.com", "simplify.jobs", "wellfound.com",
    "angel.co", "monster.", "builtin.com", "handshake", "joinhandshake.com", "ripplematch.com",
    "otta.com", "workopolis.com", "jobbank.gc.ca", "talent.com", "adzuna.", "levels.fyi",
)

# Real ATS vendors RoleRadar has no adapter for yet.
UNSUPPORTED_ATS_HOSTS = {
    "icims.com": "icims", "taleo.net": "taleo", "oraclecloud.com": "oracle_hcm",
    "successfactors.com": "successfactors", "successfactors.eu": "successfactors",
    "smartrecruiters.com": "smartrecruiters", "workable.com": "workable", "jobvite.com": "jobvite",
    "adp.com": "adp", "ultipro.com": "ukg", "ukg.com": "ukg", "paylocity.com": "paylocity",
    "phenompeople.com": "phenom", "eightfold.ai": "eightfold", "avature.net": "avature",
    "brassring.com": "brassring", "dayforcehcm.com": "dayforce", "bamboohr.com": "bamboohr",
    "recruitee.com": "recruitee", "teamtailor.com": "teamtailor", "breezy.hr": "breezy",
    "applytojob.com": "jazzhr", "myworkdaysite.com": "workday_site", "rippling.com": "rippling",
    "dover.com": "dover", "gem.com": "gem", "pinpointhq.com": "pinpoint", "jobs.jobscore.com": "jobscore",
}

# Common Simplify location abbreviations.
LOCATION_ALIASES = {
    "sf": "San Francisco, CA", "nyc": "New York, NY", "la": "Los Angeles, CA",
    "dc": "Washington, DC", "remote in usa": "Remote - United States", "remote in us": "Remote - United States",
    "remote in canada": "Remote - Canada", "remote": "Remote",
}

SOFTWARE_CATEGORIES = {"software", "software engineering", "ai/ml/data", "data science, ai & machine learning"}


@dataclass
class DiscoveryCandidate:
    source_repo: str
    source_id: str
    company_name: str
    title: str
    location_text: str = ""
    locations: List[Dict[str, str]] = field(default_factory=list)
    role_type: Optional[str] = None
    term_season: Optional[str] = None
    term_year: Optional[int] = None
    discovered_url: Optional[str] = None
    simplify_url: Optional[str] = None
    official_url: Optional[str] = None
    official_url_verified: bool = False
    company_configured: bool = False
    provider: Optional[str] = None
    provider_identifier: Optional[str] = None
    provider_job_id: Optional[str] = None
    eligible_country: Optional[str] = None
    has_canada: bool = False
    status: str = "discovered"
    verification_status: str = "unverified"
    reason: Optional[str] = None
    matched_source_name: Optional[str] = None
    matched_source_job_id: Optional[str] = None
    category: Optional[str] = None
    active: bool = True
    duplicate_of: Optional[str] = None
    in_scope: bool = False   # active, software, US/Canada: eligible for official verification

    @property
    def candidate_key(self) -> str:
        return f"{self.source_repo}:{self.source_id}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["candidate_key"] = self.candidate_key
        return d


# =============================================================================
# Fetching & parsing
# =============================================================================

def fetch_listings(source: Dict[str, str], http_client: Optional[HardenedHttpClient] = None) -> List[Dict[str, Any]]:
    """Downloads a repository's listings.json. Raises IngestionFetchError on any failure."""
    client = http_client or HardenedHttpClient(timeout=(10.0, 90.0))
    payload = client.get_json(RAW_BASE.format(repo=source["repo"], branch=source["branch"], path=source["path"]))
    if not isinstance(payload, list):
        raise IngestionFetchError(f"Malformed Simplify listings for {source['repo']}: expected a JSON array")
    return payload


def _clean_locations(raw_locations: Any) -> Tuple[List[Dict[str, str]], str]:
    labels = [str(x).strip() for x in raw_locations if isinstance(x, str) and x.strip()] if isinstance(raw_locations, list) else []
    normalized: List[Dict[str, str]] = []
    for label in labels:
        label = LOCATION_ALIASES.get(label.lower(), label)
        for loc in normalize_job_locations(label):
            if loc not in normalized:
                normalized.append(loc)
    return normalized, "; ".join(labels)


def simplify_listing_url(raw: Dict[str, Any]) -> Optional[str]:
    """
    The real Simplify listing URL. The Simplify README links every Simplify-sourced posting as
    https://simplify.jobs/p/<id>; community-submitted rows (other ``source`` values) have no
    Simplify posting, so no link is ever fabricated for them.
    """
    if raw.get("source") != "Simplify":
        return None
    listing_id = str(raw.get("id") or "")
    if not UUID_RE.match(listing_id):
        return None
    url = f"https://simplify.jobs/p/{listing_id}"
    return url if is_simplify_job_url(url) else None


def _role_type_for(title: str, kind: str) -> str:
    role = classify_role_type(title)
    if role in EARLY_CAREER_ROLE_TYPES:
        return role
    # Structured evidence: which list the posting was published in.
    return "internship" if kind == "internship" else "new_grad"


def parse_listing(raw: Any, source: Dict[str, str]) -> Optional[DiscoveryCandidate]:
    """
    Converts one raw Simplify listing into a candidate. Returns None for structurally
    malformed rows. Ineligible rows are returned with status 'closed' / 'invalid' and a reason.
    """
    if not isinstance(raw, dict):
        return None
    listing_id = str(raw.get("id") or "").strip()
    company = raw.get("company_name")
    title = raw.get("title")
    if not listing_id or not isinstance(company, str) or not company.strip() or not isinstance(title, str) or not title.strip():
        return None

    title = title.strip()
    locations, location_text = _clean_locations(raw.get("locations"))
    terms = [t for t in (raw.get("terms") or []) if isinstance(t, str) and t.strip() and t.strip().upper() != "N/A"]
    role_type = _role_type_for(title, source.get("kind", "internship"))
    term = extract_academic_term(title, structured_terms=terms)

    eligible_countries = [
        loc["country"] for loc in locations if loc["country"] in ELIGIBLE_COUNTRIES
        and is_user_facing_location_eligible(loc["location"], loc["country"])
    ]
    url = raw.get("url") if isinstance(raw.get("url"), str) and raw["url"].strip() else None

    cand = DiscoveryCandidate(
        source_repo=source["repo"],
        source_id=listing_id,
        company_name=company.strip(),
        title=title,
        location_text=location_text,
        locations=locations,
        role_type=role_type,
        term_season=term["season"] if term else None,
        term_year=term["year"] if term else None,
        discovered_url=url.strip() if url else None,
        simplify_url=simplify_listing_url(raw),
        eligible_country="Canada" if "Canada" in eligible_countries else (eligible_countries[0] if eligible_countries else None),
        has_canada="Canada" in eligible_countries,
        category=raw.get("category") if isinstance(raw.get("category"), str) else None,
        active=bool(raw.get("active")),
    )

    if raw.get("is_visible") is False:
        cand.status, cand.reason = "invalid", "hidden in Simplify (is_visible=false)"
    elif not cand.active:
        cand.status, cand.reason = "closed", "marked inactive in Simplify"
    elif not is_swe_role(title):
        cand.status, cand.reason = "invalid", "no software-engineering evidence in title"
    elif not eligible_countries:
        cand.status, cand.reason = "invalid", "no United States or Canada location"
    elif not cand.discovered_url:
        cand.status, cand.reason = "invalid", "listing has no employer URL"
    cand.in_scope = cand.status == "discovered"
    return cand


def parse_listings(raw_rows: Iterable[Any], source: Dict[str, str]) -> Tuple[List[DiscoveryCandidate], int]:
    """Parses rows; returns (candidates, malformed_row_count)."""
    out: List[DiscoveryCandidate] = []
    malformed = 0
    for row in raw_rows:
        cand = parse_listing(row, source)
        if cand is None:
            malformed += 1
        else:
            out.append(cand)
    return out, malformed


# =============================================================================
# Provider / official-URL detection
# =============================================================================

@dataclass
class UrlInfo:
    official: bool                       # employer or ATS page (not an aggregator)
    provider: Optional[str] = None       # greenhouse | lever | ashby | workday | amazon | <unsupported vendor> | custom
    identifier: Optional[str] = None     # board token / workday '<tenant>.<pod>/<site>' / amazon country
    job_id: Optional[str] = None         # id matching RawJobPosting.source_job_id when derivable
    supported: bool = False
    workday: Optional[Tuple[str, str, str, str]] = None


def detect_provider(url: Optional[str]) -> UrlInfo:
    if not url or not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        return UrlInfo(official=False)
    parsed = urllib.parse.urlsplit(url.strip())
    host = (parsed.netloc or "").lower().split(":")[0]
    query = urllib.parse.parse_qs(parsed.query)
    parts = [p for p in parsed.path.split("/") if p]

    if any(agg in host for agg in AGGREGATOR_HOSTS):
        return UrlInfo(official=False)

    wd = parse_workday_job_url(url)
    if wd:
        tenant, pod, site, path = wd
        return UrlInfo(True, "workday", f"{tenant}.{pod}/{site}", path.rstrip("/").rsplit("/", 1)[-1], True, wd)

    if host.endswith("amazon.jobs"):
        m = re.search(r"/jobs/(\d+)", parsed.path)
        return UrlInfo(True, "amazon", None, m.group(1) if m else None, bool(m))

    ats = parse_ats_url(url)
    if ats:
        provider, token = ats
        job_id: Optional[str] = None
        if provider == "greenhouse":
            m = re.search(r"/jobs/(\d+)", parsed.path)
            job_id = m.group(1) if m else (query.get("gh_jid") or query.get("token") or [None])[0]
            if job_id and not str(job_id).isdigit():
                job_id = None
            # embed URLs carry a job token, not a board token
            if "embed/job_app" in parsed.path:
                return UrlInfo(True, "greenhouse", None, job_id, True)
        else:
            uuids = [p for p in parts[1:] if UUID_RE.match(p)]
            job_id = uuids[0] if uuids else None
        return UrlInfo(True, provider, token, job_id, True)

    if "greenhouse.io" in host:  # embed/job_app?token=... and similar
        m = re.search(r"token=(\d+)", parsed.query)
        return UrlInfo(True, "greenhouse", None, m.group(1) if m else None, True)

    for suffix, vendor in UNSUPPORTED_ATS_HOSTS.items():
        if host == suffix or host.endswith("." + suffix) or suffix in host:
            return UrlInfo(True, vendor, None, None, False)

    gh_jid = (query.get("gh_jid") or [None])[0]
    if gh_jid and str(gh_jid).isdigit():
        # Employer-hosted page fronting a Greenhouse board (board token unknown).
        return UrlInfo(True, "greenhouse", None, str(gh_jid), True)
    return UrlInfo(True, "custom", None, None, False)


# =============================================================================
# Company matching
# =============================================================================

class TargetIndex:
    """Lookup of configured companies by ATS identity first, then by name/alias."""

    def __init__(self, targets: List[Dict[str, Any]]):
        self.by_identity: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.by_name: Dict[str, Dict[str, Any]] = {}
        for t in targets:
            ats = (t.get("ats") or "").strip().lower()
            ident = (t.get("identifier") or "").strip().lower()
            if ats and ident:
                self.by_identity[(ats, ident)] = t
                if ats == "workday":
                    self.by_identity[(ats, ident.split("/")[0])] = t  # tenant-level match
            for name in [t.get("name")] + list(t.get("aliases") or []):
                key = normalize_company_name(name or "")
                if key:
                    self.by_name.setdefault(key, t)

    def match(self, info: UrlInfo, company_name: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """Returns (target, how) where how is 'identity' or 'name' (or '' if none)."""
        if info.provider and info.identifier:
            ident = info.identifier.lower()
            hit = self.by_identity.get((info.provider, ident)) or (
                self.by_identity.get((info.provider, ident.split("/")[0])) if info.provider == "workday" else None
            )
            if hit:
                return hit, "identity"
        hit = self.by_name.get(normalize_company_name(company_name))
        if hit and (info.identifier is None or info.provider == hit.get("ats")):
            # A name match only stands in when the URL itself names no conflicting board.
            return hit, "name"
        return None, ""


# =============================================================================
# Verification against the official source
# =============================================================================

@dataclass
class BoardSnapshot:
    ok: bool
    complete: bool = False
    jobs: Dict[str, Any] = field(default_factory=dict)   # source_job_id -> RawJobPosting
    error: Optional[str] = None


def fetch_board_snapshot(provider: str, identifier: str, company_name: str) -> BoardSnapshot:
    """Default board fetcher for greenhouse/lever/ashby (public list endpoints)."""
    try:
        result = get_ats_client(provider).fetch_jobs(company_name, identifier)
    except (IngestionFetchError, ValueError) as err:
        return BoardSnapshot(False, error=str(err)[:200])
    complete = bool(result.fetch_complete and result.parse_error_count == 0)
    return BoardSnapshot(True, complete, {j.source_job_id: j for j in result.jobs if j.is_listed})


def verify_workday_posting(wd: Tuple[str, str, str, str], http_client: Optional[HardenedHttpClient] = None) -> Tuple[str, Optional[str]]:
    """
    Verifies one Workday posting through the tenant's public CXS detail endpoint.
    Returns (verification_status, official_url): 'verified' | 'not_found' | 'error'.
    """
    tenant, pod, site, path = wd
    client = http_client or HardenedHttpClient()
    url = f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}"
    try:
        payload = client.get_json(url)
    except IngestionFetchError as err:
        return ("not_found" if "HTTP 404" in str(err) else "error"), None
    info = payload.get("jobPostingInfo") if isinstance(payload, dict) else None
    if not isinstance(info, dict) or not info.get("title"):
        return "not_found", None
    if info.get("canApply") is False:
        return "not_found", None
    return "verified", f"https://{tenant}.{pod}.myworkdayjobs.com/{site}{path}"


def verify_amazon_posting(job_id: str, http_client: Optional[HardenedHttpClient] = None) -> Tuple[str, Optional[str]]:
    """Verifies an amazon.jobs posting by fetching its own job page."""
    client = http_client or HardenedHttpClient()
    url = f"https://www.amazon.jobs/en/jobs/{job_id}"
    try:
        resp = client.get(url, headers={"Accept-Encoding": "gzip, deflate"})
    except IngestionFetchError as err:
        return ("not_found" if "HTTP 404" in str(err) else "error"), None
    return ("verified", url) if f"/jobs/{job_id}" in resp.url else ("not_found", None)


def _same_job(job_id: Optional[str], snapshot: BoardSnapshot) -> Optional[Any]:
    return snapshot.jobs.get(job_id) if job_id else None


def resolve_candidates(
    candidates: List[DiscoveryCandidate],
    targets: List[Dict[str, Any]],
    *,
    fetch_board: Callable[[str, str, str], BoardSnapshot] = fetch_board_snapshot,
    verify_workday: Callable[[Tuple[str, str, str, str]], Tuple[str, Optional[str]]] = verify_workday_posting,
    verify_amazon: Callable[[str], Tuple[str, Optional[str]]] = verify_amazon_posting,
    known_jobs: Optional[Set[Tuple[str, str]]] = None,
    max_boards: int = 250,
    max_direct_checks: int = 600,
    workers: int = 8,
) -> Dict[str, Any]:
    """
    Mutates candidates in place: resolves the official URL, verifies the posting against the
    official source, and assigns a discovery status. Candidates that are not 'discovered' (already
    closed / invalid) are left untouched. Never touches the database.

    Returns run stats: boards attempted / failed, direct checks, deferred counts.
    """
    index = TargetIndex(targets)
    known_jobs = known_jobs or set()
    stats = {"boards_attempted": 0, "boards_failed": [], "direct_checks": 0, "deferred_budget": 0}

    board_plan: Dict[Tuple[str, str], List[DiscoveryCandidate]] = {}
    direct_plan: List[DiscoveryCandidate] = []
    workday_urls: Dict[int, Tuple[str, str, str, str]] = {}

    seen_identity: Dict[Tuple[str, str, str], str] = {}
    seen_urls: Dict[str, str] = {}

    for cand in candidates:
        if cand.status != "discovered":
            continue
        info = detect_provider(cand.discovered_url)
        cand.provider, cand.provider_identifier, cand.provider_job_id = info.provider, info.identifier, info.job_id

        # Duplicates: same official requisition or the same canonical URL seen twice.
        canon = canonicalize_apply_url(cand.discovered_url)
        ident_key = (info.provider or "", (info.identifier or "").lower(), info.job_id or "")
        prior = seen_urls.get(canon) or (seen_identity.get(ident_key) if info.job_id else None)
        if prior:
            cand.status, cand.reason, cand.duplicate_of = "already_known", f"duplicate of {prior}", prior
            continue
        seen_urls[canon] = cand.candidate_key
        if info.job_id:
            seen_identity[ident_key] = cand.candidate_key

        target, how = index.match(info, cand.company_name)
        cand.company_configured = target is not None

        if not info.official:
            cand.status, cand.reason = "official_not_found", "listing URL is an aggregator, not the employer or its ATS"
            continue
        cand.official_url = cand.discovered_url  # resolved (not yet verified)

        if info.provider == "workday" and info.workday:
            direct_plan.append(cand)
            workday_urls[id(cand)] = info.workday
            continue
        if info.provider == "amazon":
            if info.job_id:
                direct_plan.append(cand)
            else:
                cand.status, cand.reason = "official_url_resolved", "amazon.jobs URL without a job id"
            continue

        if info.provider in ("greenhouse", "lever", "ashby"):
            board = None
            if info.identifier:
                board = (info.provider, info.identifier.lower())
            elif target and target.get("ats") == info.provider:
                board = (info.provider, str(target["identifier"]).lower())
            if board and info.job_id:
                board_plan.setdefault(board, []).append(cand)
            elif board:
                cand.status, cand.reason = "official_url_resolved", "official URL has no recognisable job id to verify"
            else:
                cand.status, cand.reason = "official_url_resolved", f"{info.provider} URL without a board token; company not configured"
            continue

        # Vendors and custom career sites without an adapter.
        cand.status = "unsupported_source"
        cand.reason = (
            f"{info.provider} careers platform has no RoleRadar adapter" if info.provider != "custom"
            else "company-hosted careers page without a structured source"
        )

    # --- verify token boards (Canada-first, budgeted)
    def board_priority(item):
        cands = item[1]
        return (0 if any(c.has_canada for c in cands) else 1, -len(cands))

    ordered_boards = sorted(board_plan.items(), key=board_priority)
    to_fetch = ordered_boards[:max_boards]
    for board, cands in ordered_boards[max_boards:]:
        for c in cands:
            c.status, c.reason = "deferred", "verification budget exceeded for this run"
            stats["deferred_budget"] += 1

    def fetch(item):
        (provider, ident), cands = item
        return item, fetch_board(provider, ident, cands[0].company_name)

    stats["boards_attempted"] = len(to_fetch)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (board, cands), snap in pool.map(fetch, to_fetch):
            if not snap.ok:
                stats["boards_failed"].append({"board": f"{board[0]}:{board[1]}", "error": snap.error})
                for c in cands:
                    c.verification_status = "error"
                    c.status = "official_not_found"
                    c.reason = f"official board could not be fetched ({(snap.error or 'error')[:80]})"
                continue
            for c in cands:
                job = _same_job(c.provider_job_id, snap)
                if job is not None:
                    _mark_verified(c, board[0], c.provider_job_id, job.company_apply_url or job.source_url, known_jobs)
                elif snap.complete:
                    c.status, c.verification_status = "closed", "not_found"
                    c.reason = "posting is not on the employer's complete official listing"
                else:
                    c.status, c.verification_status = "official_not_found", "not_found"
                    c.reason = "posting not found in a partial official snapshot"

    # --- verify direct (per-posting) sources
    direct_plan = direct_plan[:]
    budgeted = direct_plan[:max_direct_checks]
    for c in direct_plan[max_direct_checks:]:
        c.status, c.reason = "deferred", "verification budget exceeded for this run"
        stats["deferred_budget"] += 1

    def check(c: DiscoveryCandidate):
        if c.provider == "workday":
            return c, verify_workday(workday_urls[id(c)])
        return c, verify_amazon(c.provider_job_id or "")

    stats["direct_checks"] = len(budgeted)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for c, (state, official) in pool.map(check, budgeted):
            if state == "verified":
                _mark_verified(c, c.provider, c.provider_job_id, official, known_jobs)
            elif state == "not_found":
                c.status, c.verification_status = "closed", "not_found"
                c.reason = "official posting no longer exists"
            else:
                c.status, c.verification_status = "deferred", "error"
                c.reason = "official posting check failed; retry next run"
    return stats


def _mark_verified(c: DiscoveryCandidate, provider: Optional[str], job_id: Optional[str], official_url: Optional[str], known_jobs: Set[Tuple[str, str]]) -> None:
    c.verification_status = "verified"
    c.official_url_verified = True
    c.official_url = official_url or c.official_url
    c.matched_source_name, c.matched_source_job_id = provider, job_id
    if provider and job_id and (provider, job_id) in known_jobs:
        c.status, c.reason = "already_known", "already ingested from its official source"
    else:
        c.status = "verified"
        c.reason = (
            "verified on the employer's official source" if c.company_configured
            else "verified on the employer's official source; company is not in the registry, so it is not public"
        )


# =============================================================================
# Persistence (discovery_candidates only) and Simplify URL attachment
# =============================================================================

def persist_candidates(cur, candidates: List[DiscoveryCandidate]) -> int:
    """Upserts candidates into discovery_candidates. NEVER writes to job_postings."""
    written = 0
    for c in candidates:
        cur.execute(
            """
            INSERT INTO discovery_candidates (
                candidate_key, source_repo, source_id, company_name, title, location_text, locations,
                role_type, term_season, term_year, discovered_url, simplify_url, official_url,
                official_url_verified, company_configured, provider, provider_identifier, eligible_country,
                status, verification_status, status_reason, matched_source_name, matched_source_job_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (candidate_key) DO UPDATE SET
                title = EXCLUDED.title, location_text = EXCLUDED.location_text, locations = EXCLUDED.locations,
                role_type = EXCLUDED.role_type, term_season = EXCLUDED.term_season, term_year = EXCLUDED.term_year,
                discovered_url = EXCLUDED.discovered_url, simplify_url = EXCLUDED.simplify_url,
                official_url = EXCLUDED.official_url, official_url_verified = EXCLUDED.official_url_verified,
                company_configured = EXCLUDED.company_configured, provider = EXCLUDED.provider,
                provider_identifier = EXCLUDED.provider_identifier, eligible_country = EXCLUDED.eligible_country,
                status = EXCLUDED.status, verification_status = EXCLUDED.verification_status,
                status_reason = EXCLUDED.status_reason, matched_source_name = EXCLUDED.matched_source_name,
                matched_source_job_id = EXCLUDED.matched_source_job_id,
                last_seen_at = NOW(), updated_at = NOW()
            """,
            (
                c.candidate_key, c.source_repo, c.source_id, c.company_name[:500], c.title, c.location_text,
                json.dumps(c.locations), c.role_type, c.term_season, c.term_year, c.discovered_url,
                c.simplify_url, c.official_url, c.official_url_verified, c.company_configured,
                (c.provider or None), c.provider_identifier, c.eligible_country, c.status,
                c.verification_status, c.reason, c.matched_source_name, c.matched_source_job_id,
            ),
        )
        written += 1
    return written


def attach_simplify_urls(cur, candidates: List[DiscoveryCandidate]) -> int:
    """
    Adds a candidate's genuine Simplify listing URL as a secondary route to the matching job that
    was ALREADY ingested from its official source. Only updates existing rows; never inserts.
    """
    attached = 0
    for c in candidates:
        if not (c.official_url_verified and c.simplify_url and c.matched_source_name and c.matched_source_job_id):
            continue
        if not is_simplify_job_url(c.simplify_url):
            continue
        cur.execute(
            """
            UPDATE job_postings SET simplify_url = %s, updated_at = NOW()
            WHERE source_name = %s AND source_job_id = %s AND is_active = TRUE
              AND (simplify_url IS NULL OR simplify_url <> %s)
            """,
            (c.simplify_url, c.matched_source_name, c.matched_source_job_id, c.simplify_url),
        )
        attached += cur.rowcount
    return attached


def load_known_jobs(cur) -> Set[Tuple[str, str]]:
    cur.execute("SELECT source_name, source_job_id FROM job_postings WHERE source_job_id IS NOT NULL AND is_active = TRUE")
    return {(r[0], r[1]) for r in cur.fetchall()}


# =============================================================================
# Orchestration & report
# =============================================================================

def build_report(candidates: List[DiscoveryCandidate], stats: Dict[str, Any], failed_sources: List[Dict[str, str]],
                 malformed: int, raw_total: int, companies_attempted: int) -> Dict[str, Any]:
    from collections import Counter

    status = Counter(c.status for c in candidates)
    active_relevant = [c for c in candidates if c.in_scope]
    canada = [c for c in active_relevant if c.has_canada]
    return {
        "raw_listings": raw_total,
        "malformed_rows": malformed,
        "candidates_parsed": len(candidates),
        "active_swe_us_ca_candidates": len(active_relevant),
        "canadian_candidates": len(canada),
        "by_role_type": dict(Counter(c.role_type for c in active_relevant)),
        "canadian_by_role_type": dict(Counter(c.role_type for c in canada)),
        "by_term": dict(Counter(f"{c.term_season} {c.term_year}" for c in active_relevant if c.term_season)),
        "by_status": dict(status),
        "official_urls_resolved": sum(1 for c in active_relevant if c.official_url),
        "verified_through_official_source": sum(1 for c in active_relevant if c.official_url_verified),
        "verified_canadian": sum(1 for c in canada if c.official_url_verified),
        "rejected_or_closed": sum(1 for c in candidates if c.status in ("invalid", "closed")),
        "rejected_invalid": sum(1 for c in candidates if c.status == "invalid"),
        "closed_in_simplify": sum(1 for c in candidates if c.status == "closed" and not c.in_scope),
        "closed_on_official_source": sum(1 for c in active_relevant if c.status == "closed"),
        "duplicates": sum(1 for c in candidates if c.duplicate_of),
        "simplify_urls_available": sum(1 for c in active_relevant if c.simplify_url),
        "company_already_configured": sum(1 for c in active_relevant if c.company_configured),
        "companies_attempted": companies_attempted,
        "boards_attempted": stats.get("boards_attempted", 0),
        "direct_checks": stats.get("direct_checks", 0),
        "failed_sources": failed_sources + [
            {"source": f["board"], "error": f["error"] or ""} for f in stats.get("boards_failed", [])
        ],
        "deferred_over_budget": stats.get("deferred_budget", 0),
        "registry_recommendations": _registry_recommendations(candidates),
    }


def _registry_recommendations(candidates: List[DiscoveryCandidate]) -> List[Dict[str, Any]]:
    from collections import defaultdict

    groups: Dict[Tuple[str, str, str], List[DiscoveryCandidate]] = defaultdict(list)
    for c in candidates:
        if c.status == "verified" and not c.company_configured and c.provider in ("greenhouse", "lever", "ashby", "workday"):
            groups[(c.company_name, c.provider or "", c.provider_identifier or "")].append(c)
    rows = [
        {"company": k[0], "ats": k[1], "identifier": k[2], "verified_postings": len(v), "canadian_postings": sum(1 for c in v if c.has_canada)}
        for k, v in groups.items()
    ]
    rows.sort(key=lambda r: (-r["canadian_postings"], -r["verified_postings"], r["company"]))
    return rows[:40]


def run_simplify_discovery(
    targets: List[Dict[str, Any]],
    sources: Optional[List[Dict[str, str]]] = None,
    http_client: Optional[HardenedHttpClient] = None,
    listings_override: Optional[Dict[str, List[Any]]] = None,
    known_jobs: Optional[Set[Tuple[str, str]]] = None,
    **resolve_kwargs: Any,
) -> Tuple[List[DiscoveryCandidate], Dict[str, Any]]:
    """
    Fetches every Simplify source, parses candidates and resolves them against official sources.
    A source that fails to download is reported and skipped; the rest still run.
    """
    candidates: List[DiscoveryCandidate] = []
    failed_sources: List[Dict[str, str]] = []
    malformed_total = raw_total = 0
    for source in sources or SIMPLIFY_SOURCES:
        try:
            rows = (listings_override or {}).get(source["repo"])
            if rows is None:
                rows = fetch_listings(source, http_client)
        except IngestionFetchError as err:
            logger.error("Simplify source %s failed: %s", source["repo"], err)
            failed_sources.append({"source": source["repo"], "error": str(err)[:200]})
            continue
        parsed, malformed = parse_listings(rows, source)
        raw_total += len(rows)
        malformed_total += malformed
        candidates.extend(parsed)

    stats = resolve_candidates(candidates, targets, known_jobs=known_jobs, **resolve_kwargs)
    report = build_report(candidates, stats, failed_sources, malformed_total, raw_total, len(targets))
    return candidates, report
