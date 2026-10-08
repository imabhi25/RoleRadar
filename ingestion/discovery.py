"""
ATS Discovery Layer for RoleRadar.
Inspects public company careers pages, identifies supported ATS links
(Greenhouse, Lever, Ashby), extracts company tokens, and compares against
existing target configurations.
"""

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import urllib.parse

from bs4 import BeautifulSoup
import requests

from ingestion.http_client import HardenedHttpClient, IngestionFetchError

logger = logging.getLogger("ingestion.discovery")

DEFAULT_TIMEOUT: Tuple[float, float] = (5.0, 15.0)
DISCOVERY_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "(RoleRadar ATS Discovery; +https://github.com/imabhi25/Jobber)"
)

# Provider-specific reserved path segments, filenames, and API artifacts
COMMON_RESERVED_TOKENS: Set[str] = {
    "users",
    "user",
    "v1",
    "v2",
    "v3",
    "v4",
    "api",
    "embed",
    "jobs",
    "job",
    "search",
    "apply",
    "application",
    "applications",
    "careers",
    "career",
    "privacy",
    "terms",
    "legal",
    "favicon.ico",
    "robots.txt",
    "assets",
    "static",
    "docs",
    "support",
    "help",
    "login",
    "auth",
    "account",
    "accounts",
    "app",
    "apps",
    "widget",
    "widgets",
    "boards",
    "board",
    "job-boards",
    "job_boards",
    "job-board",
    "job_board",
    "departments",
    "department",
    "offices",
    "office",
    "internal",
    "js",
    "json",
    "html",
}

GREENHOUSE_RESERVED: Set[str] = COMMON_RESERVED_TOKENS | {
    "job_app",
}

LEVER_RESERVED: Set[str] = COMMON_RESERVED_TOKENS

ASHBY_RESERVED: Set[str] = COMMON_RESERVED_TOKENS

# For backwards compatibility with external references
RESERVED_TOKENS: Set[str] = GREENHOUSE_RESERVED

# Invalid file extensions that can never be tokens
INVALID_EXTENSIONS = (
    ".js", ".json", ".html", ".htm", ".css", ".png",
    ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".txt", ".xml",
)

# Regex to validate valid company slugs/tokens
TOKEN_REGEX = re.compile(r"^[a-z0-9][a-z0-9_\-\.]*[a-z0-9]$|^[a-z0-9]$")

# Regex to scan HTML for raw ATS links (anchors, embedded scripts, config objects)
RAW_ATS_REGEXES = [
    re.compile(r"""(?:https?:)?//(?:[a-zA-Z0-9-]+\.)*greenhouse\.io/[^\s"'<>\\]+"""),
    re.compile(r"""(?:https?:)?//jobs\.lever\.co/[^\s"'<>\\]+"""),
    re.compile(r"""(?:https?:)?//jobs\.ashbyhq\.com/[^\s"'<>\\]+"""),
]


class DiscoveryStatus(str, Enum):
    FOUND_EXISTING = "FOUND_EXISTING"
    FOUND_NEW = "FOUND_NEW"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


@dataclass
class DiscoveryResult:
    company: str
    careers_url: str
    status: DiscoveryStatus
    provider: Optional[str] = None
    token: Optional[str] = None
    details: Optional[str] = None
    priority_countries: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company": self.company,
            "careers_url": self.careers_url,
            "status": self.status.value,
            "provider": self.provider,
            "token": self.token,
            "details": self.details,
            "priority_countries": self.priority_countries,
        }


@dataclass
class DiscoveryReport:
    results: List[DiscoveryResult]
    companies_checked: int = 0
    supported_ats_found: int = 0
    already_configured: int = 0
    new_candidates: int = 0
    unsupported: int = 0
    failed: int = 0


def validate_ats_token(provider: str, token: Optional[str]) -> Optional[str]:
    """
    Centralized validator for ATS company tokens across all discovery paths.
    Enforces provider-specific rules, excludes API/path artifacts, file names,
    version prefixes, URL fragments, and malformed strings.

    Returns:
        Clean lowercase token string if valid, or None.
    """
    if not token or not isinstance(token, str):
        return None

    cleaned = token.strip().lower()

    # Reject if empty or length out of bounds (standard slug bounds: 2-64 chars)
    if not (2 <= len(cleaned) <= 64):
        return None

    # Reject slashes, URL query/fragment delimiters
    if any(char in cleaned for char in ("/", "\\", "?", "=", "&", "#")):
        return None

    # Reject pure numbers
    if cleaned.isdigit():
        return None

    # Reject version strings (e.g. v1, v2, v3, v12)
    if re.match(r"^v\d+$", cleaned):
        return None

    # Reject obvious file names
    if cleaned.endswith(INVALID_EXTENSIONS):
        return None

    prov_lower = provider.strip().lower()
    if prov_lower == "greenhouse":
        if cleaned in GREENHOUSE_RESERVED:
            return None
        # Greenhouse slugs are alphanumeric with underscores, hyphens, and optional dots
        if not re.match(r"^[a-z0-9][a-z0-9_\-\.]*[a-z0-9]$|^[a-z0-9]$", cleaned):
            return None

    elif prov_lower == "lever":
        if cleaned in LEVER_RESERVED:
            return None
        if not re.match(r"^[a-z0-9][a-z0-9_\-\.]*[a-z0-9]$|^[a-z0-9]$", cleaned):
            return None

    elif prov_lower == "ashby":
        if cleaned in ASHBY_RESERVED:
            return None
        # Ashby slugs allow alphanumeric, underscores, hyphens, and dots (e.g. mistral.ai, runway-ml, linear)
        if not re.match(r"^[a-z0-9][a-z0-9_\-\.]*[a-z0-9]$|^[a-z0-9]$", cleaned):
            return None

    else:
        return None

    return cleaned


def is_valid_token(token: Optional[str], provider: str = "greenhouse") -> bool:
    """Wrapper around validate_ats_token for backwards compatibility."""
    return validate_ats_token(provider, token) is not None


def parse_ats_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Parses a URL and extracts (provider, token) if it matches a supported ATS.
    All extracted candidate tokens are strictly validated through validate_ats_token().

    Supported ATS:
    - Greenhouse: boards.greenhouse.io, job-boards.greenhouse.io
    - Lever: jobs.lever.co
    - Ashby: jobs.ashbyhq.com

    Returns:
        (provider, token) tuple if matched and valid, or None.
    """
    if not url or not isinstance(url, str):
        return None

    cleaned_url = url.strip()
    if cleaned_url.startswith("//"):
        cleaned_url = "https:" + cleaned_url

    try:
        parsed = urllib.parse.urlsplit(cleaned_url)
    except Exception:
        return None

    host = (parsed.netloc or "").lower()
    if ":" in host:
        host = host.split(":")[0]

    # --- 1. Greenhouse ---
    if "greenhouse.io" in host:
        # Check query parameters first (e.g. embed/job_board?for=stripe or ?token=stripe)
        query_params = urllib.parse.parse_qs(parsed.query)
        if "for" in query_params and query_params["for"]:
            candidate = query_params["for"][0].strip().lower()
            valid_tok = validate_ats_token("greenhouse", candidate)
            if valid_tok:
                return ("greenhouse", valid_tok)
        if "token" in query_params and query_params["token"]:
            candidate = query_params["token"][0].strip().lower()
            valid_tok = validate_ats_token("greenhouse", candidate)
            if valid_tok:
                return ("greenhouse", valid_tok)

        # Check path segments
        path_parts = [urllib.parse.unquote(p).strip().lower() for p in parsed.path.strip("/").split("/") if p]
        if path_parts:
            first_part = path_parts[0]
            if first_part == "embed":
                if len(path_parts) > 1:
                    valid_tok = validate_ats_token("greenhouse", path_parts[1])
                    if valid_tok:
                        return ("greenhouse", valid_tok)
            elif first_part in {"api", "v1", "v2", "v3", "boards"}:
                # API route like /v1/boards/{token}/jobs or /api/v1/boards/{token}
                for part in path_parts:
                    valid_tok = validate_ats_token("greenhouse", part)
                    if valid_tok:
                        return ("greenhouse", valid_tok)
            else:
                valid_tok = validate_ats_token("greenhouse", first_part)
                if valid_tok:
                    return ("greenhouse", valid_tok)

    # --- 2. Lever ---
    if "jobs.lever.co" in host or ("lever.co" in host and "jobs" in host):
        path_parts = [urllib.parse.unquote(p).strip().lower() for p in parsed.path.strip("/").split("/") if p]
        if path_parts:
            valid_tok = validate_ats_token("lever", path_parts[0])
            if valid_tok:
                return ("lever", valid_tok)

    # --- 3. Ashby ---
    if "jobs.ashbyhq.com" in host or "ashbyhq.com" in host:
        path_parts = [urllib.parse.unquote(p).strip().lower() for p in parsed.path.strip("/").split("/") if p]
        if path_parts:
            valid_tok = validate_ats_token("ashby", path_parts[0])
            if valid_tok:
                return ("ashby", valid_tok)

    return None


def extract_ats_candidates_from_html(html: str, base_url: str = "") -> List[Tuple[str, str]]:
    """
    Scans HTML content and extracts all (provider, token) candidates found in
    links, iframes, scripts, data attributes, and embedded source texts.
    """
    if not html or not isinstance(html, str):
        return []

    candidates: List[Tuple[str, str]] = []

    # 1. Structured DOM extraction with BeautifulSoup
    try:
        soup = BeautifulSoup(html, "html.parser")
        dom_urls: Set[str] = set()

        for tag in soup.find_all(["a", "link"]):
            href = tag.get("href")
            if href:
                dom_urls.add(href.strip())

        for tag in soup.find_all(["iframe", "script"]):
            src = tag.get("src")
            if src:
                dom_urls.add(src.strip())

        # Check data-* attributes on all elements (common in SPA/JS widgets)
        for tag in soup.find_all(True):
            for attr_name, attr_val in tag.attrs.items():
                if attr_name.startswith("data-") and isinstance(attr_val, str) and (
                    "greenhouse" in attr_val or "lever.co" in attr_val or "ashbyhq" in attr_val
                ):
                    dom_urls.add(attr_val.strip())

        for raw_url in dom_urls:
            full_url = urllib.parse.urljoin(base_url, raw_url) if base_url else raw_url
            match = parse_ats_url(full_url)
            if match:
                candidates.append(match)
    except Exception as err:
        logger.debug("Error during BeautifulSoup DOM traversal: %s", err)

    # 2. Raw regex scan to catch inline script variables or unparsed JSON configurations
    for regex in RAW_ATS_REGEXES:
        for match_str in regex.findall(html):
            cleaned = match_str.rstrip("'\">);,")
            if cleaned in dom_urls:
                continue
            full_url = urllib.parse.urljoin(base_url, cleaned) if base_url else cleaned
            match = parse_ats_url(full_url)
            if match:
                candidates.append(match)

    return candidates


def select_primary_candidate(candidates: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
    """
    Selects the primary (provider, token) from a list of candidates.
    Uses frequency count; in case of ties, preserves the earliest observed match.
    """
    if not candidates:
        return None

    counts = Counter(candidates)
    # Counter.most_common() preserves order of first occurrence for ties in Python 3.7+
    best, _ = counts.most_common(1)[0]
    return best


def detect_unsupported_ats(html: str) -> Optional[str]:
    """Checks if common unsupported ATS systems are present for richer diagnostics."""
    lower_html = html.lower()
    if "myworkdayjobs.com" in lower_html or "workday" in lower_html:
        return "Workday"
    if "taleo.net" in lower_html:
        return "Taleo"
    if "icims.com" in lower_html:
        return "iCIMS"
    if "smartrecruiters.com" in lower_html:
        return "SmartRecruiters"
    if "bamboohr.com" in lower_html:
        return "BambooHR"
    return None


def discover_company_ats(
    company: str,
    careers_url: str,
    priority_countries: Optional[List[str]] = None,
    client: Optional[HardenedHttpClient] = None,
    timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
    target_index: Optional[Dict[str, Set[str]]] = None,
) -> DiscoveryResult:
    """
    Inspects a public company careers page and identifies supported ATS sources.

    Args:
        company: Name of the company.
        careers_url: Public URL to inspect.
        priority_countries: Optional list of priority countries.
        client: Optional HardenedHttpClient instance.
        timeout: Request timeout tuple.
        target_index: Optional dict mapping lowercase ats -> set of lowercase identifiers.

    Returns:
        DiscoveryResult with status, provider, token, and diagnostics.
    """
    countries = priority_countries or ["United States", "Canada"]

    # Validate careers URL scheme
    if not careers_url or not isinstance(careers_url, str):
        return DiscoveryResult(
            company=company,
            careers_url=careers_url or "",
            status=DiscoveryStatus.FAILED,
            details="Invalid URL",
            priority_countries=countries,
        )

    parsed_url = urllib.parse.urlsplit(careers_url.strip())
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return DiscoveryResult(
            company=company,
            careers_url=careers_url,
            status=DiscoveryStatus.FAILED,
            details="Invalid URL scheme",
            priority_countries=countries,
        )

    # Manage HTTP client lifecycle
    owns_client = client is None
    http = client or HardenedHttpClient(user_agent=DISCOVERY_USER_AGENT, timeout=timeout)

    try:
        try:
            response = http.get(careers_url, timeout=timeout)
        except IngestionFetchError as err:
            err_msg = str(err)
            if "HTTP 404" in err_msg:
                detail = "HTTP 404"
            elif "HTTP 403" in err_msg:
                detail = "HTTP 403"
            elif "HTTP 500" in err_msg:
                detail = "HTTP 500"
            elif "Network error" in err_msg or "timed out" in err_msg.lower():
                detail = "Connection timeout"
            else:
                detail = err_msg.split(":")[-1].strip()[:30] if ":" in err_msg else "HTTP error"
            return DiscoveryResult(
                company=company,
                careers_url=careers_url,
                status=DiscoveryStatus.FAILED,
                details=detail,
                priority_countries=countries,
            )
        except Exception as err:
            return DiscoveryResult(
                company=company,
                careers_url=careers_url,
                status=DiscoveryStatus.FAILED,
                details=f"Error: {type(err).__name__}",
                priority_countries=countries,
            )

        # 1. Check if the careers URL redirected directly to a supported ATS
        final_url = getattr(response, "url", careers_url)
        redirect_ats = parse_ats_url(final_url)
        discovered_ats: Optional[Tuple[str, str]] = redirect_ats

        # 2. If not redirected to an ATS, inspect HTML contents
        if not discovered_ats:
            html = getattr(response, "text", "") or ""
            candidates = extract_ats_candidates_from_html(html, base_url=final_url)
            discovered_ats = select_primary_candidate(candidates)

        # 3. Determine status if ATS was found
        if discovered_ats:
            provider, raw_tok = discovered_ats
            valid_tok = validate_ats_token(provider, raw_tok)
            if not valid_tok:
                discovered_ats = None
            else:
                token = valid_tok
                provider = provider.lower()

        if discovered_ats:
            is_existing = is_existing_target(provider, token, target_index)
            status = DiscoveryStatus.FOUND_EXISTING if is_existing else DiscoveryStatus.FOUND_NEW
            return DiscoveryResult(
                company=company,
                careers_url=careers_url,
                status=status,
                provider=provider,
                token=token,
                priority_countries=countries,
            )

        # 4. No supported ATS found
        unsupported_hint = detect_unsupported_ats(getattr(response, "text", "") or "")
        details = f"Unsupported ATS: {unsupported_hint}" if unsupported_hint else "No supported ATS detected"
        return DiscoveryResult(
            company=company,
            careers_url=careers_url,
            status=DiscoveryStatus.UNSUPPORTED,
            details=details,
            priority_countries=countries,
        )

    finally:
        if owns_client:
            http.close()


def load_company_watchlist(watchlist_path: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """Loads and returns company entries from config/company_watchlist.json."""
    path = Path(watchlist_path) if watchlist_path else Path(__file__).resolve().parent.parent / "config" / "company_watchlist.json"
    if not path.exists():
        raise FileNotFoundError(f"Watchlist configuration file not found at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Watchlist file {path} must contain a JSON array of companies")

    return data


def normalize_ats_identity(provider: Optional[str], token: Optional[str]) -> Tuple[str, str]:
    """
    Normalizes provider and token for reliable identity matching.
    Trims and lowercases both while preserving all internal characters and punctuation.
    """
    norm_provider = (provider or "").strip().lower()
    norm_token = (token or "").strip().lower()
    return norm_provider, norm_token


def is_existing_target(
    provider: Optional[str],
    token: Optional[str],
    target_index: Optional[Union[Dict[str, Set[str]], Set[Tuple[str, str]]]] = None,
) -> bool:
    """
    Determines if a discovered ATS source matches an already-configured target.
    Matching is strictly based on (provider, normalized_token) identity.
    Company name is explicitly NOT used to determine existing status.
    """
    if not provider or not token or not target_index:
        return False

    norm_provider, norm_token = normalize_ats_identity(provider, token)
    if not norm_provider or not norm_token:
        return False

    if isinstance(target_index, dict):
        configured_tokens = target_index.get(norm_provider, set())
        return norm_token in configured_tokens
    elif isinstance(target_index, set):
        return (norm_provider, norm_token) in target_index

    return False


def build_target_index(target_companies: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """
    Builds lookup index from config/target_companies.json for rapid (provider, token) matching.
    Returns dict mapping lowercase provider -> set of lowercase token identifiers.
    Company name is intentionally excluded to ensure matching is based purely on ATS identity.
    """
    index: Dict[str, Set[str]] = {}
    for target in target_companies:
        ats = (target.get("ats") or target.get("provider") or "").strip().lower()
        ident = (target.get("identifier") or target.get("token") or "").strip().lower()

        if ats and ident:
            if ats not in index:
                index[ats] = set()
            index[ats].add(ident)

    return index


def run_discovery(
    watchlist: Optional[List[Dict[str, Any]]] = None,
    target_companies: Optional[List[Dict[str, Any]]] = None,
    client: Optional[HardenedHttpClient] = None,
    timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
    on_progress: Optional[Callable[[DiscoveryResult], None]] = None,
) -> DiscoveryReport:
    """
    Runs the discovery pipeline across all enabled companies in the watchlist.

    Args:
        watchlist: Optional list of company dicts (defaults to loading config/company_watchlist.json).
        target_companies: Optional list of target company dicts (defaults to config/target_companies.json).
        client: Optional HardenedHttpClient instance.
        timeout: Timeout tuple for requests.
        on_progress: Optional callback invoked with each DiscoveryResult as it completes.

    Returns:
        DiscoveryReport with complete results and aggregated metrics.
    """
    root = Path(__file__).resolve().parent.parent

    if watchlist is None:
        watchlist = load_company_watchlist(root / "config" / "company_watchlist.json")

    if target_companies is None:
        targets_file = root / "config" / "target_companies.json"
        if targets_file.exists():
            with open(targets_file, "r", encoding="utf-8") as f:
                target_companies = json.load(f)
        else:
            target_companies = []

    target_index = build_target_index(target_companies)

    # Filter to enabled companies only
    enabled_entries = [e for e in watchlist if e.get("enabled", True)]

    owns_client = client is None
    http = client or HardenedHttpClient(user_agent=DISCOVERY_USER_AGENT, timeout=timeout)

    report = DiscoveryReport(results=[])

    try:
        for entry in enabled_entries:
            company = entry.get("company", "Unknown")
            careers_url = entry.get("careers_url", "")
            priority_countries = entry.get("priority_countries", ["United States", "Canada"])

            res = discover_company_ats(
                company=company,
                careers_url=careers_url,
                priority_countries=priority_countries,
                client=http,
                timeout=timeout,
                target_index=target_index,
            )

            report.results.append(res)
            report.companies_checked += 1

            if res.status == DiscoveryStatus.FOUND_EXISTING:
                report.supported_ats_found += 1
                report.already_configured += 1
            elif res.status == DiscoveryStatus.FOUND_NEW:
                report.supported_ats_found += 1
                report.new_candidates += 1
            elif res.status == DiscoveryStatus.UNSUPPORTED:
                report.unsupported += 1
            elif res.status == DiscoveryStatus.FAILED:
                report.failed += 1

            if on_progress:
                on_progress(res)

    finally:
        if owns_client:
            http.close()

    return report


def export_new_candidates(report: DiscoveryReport, output_path: Union[str, Path]) -> int:
    """
    Exports only newly discovered supported ATS candidates (FOUND_NEW) to a JSON file.
    Does NOT modify production target configuration.

    Returns:
        Number of candidates exported.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    candidates = [
        {
            "name": r.company,
            "ats": r.provider,
            "identifier": r.token,
            "company": r.company,
            "provider": r.provider,
            "token": r.token,
            "careers_url": r.careers_url,
            "priority_countries": r.priority_countries,
        }
        for r in report.results
        if r.status == DiscoveryStatus.FOUND_NEW
    ]

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2)

    return len(candidates)
