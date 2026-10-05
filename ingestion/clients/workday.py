"""
Workday careers adapter for RoleRadar.

Workday-hosted career sites (banks, large tech) all expose the same public
"CXS" JSON endpoints that power their own careers pages:

  POST https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs   (paged list)
  GET  https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}  (detail)

One reusable adapter therefore serves many employers. A company is configured as

  {"name": "RBC", "ats": "workday", "identifier": "rbc.wd3/RBCGLOBAL1"}

where the identifier is "<tenant>.<pod>/<site>" copied from the employer's careers URL.

Safety: the returned FetchResult only claims to be a complete snapshot
(fetch_complete=True) when every list page was fetched, no requisition was duplicated
or missing, the result set was not at Workday's 2000-row ceiling, and every detail
request succeeded. Anything less leaves fetch_complete=False / parse_error_count>0,
which makes the pipeline suppress tombstoning.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.http_client import IngestionFetchError
from ingestion.workday_locations import canonical_country_name, is_home_word, normalize_workday_location
from ingestion.normalizer import (
    STUDENT_ENGINEER_REGEX,
    TECHNICAL_PROGRAM_REGEX,
    is_swe_role,
)

logger = logging.getLogger("ingestion.clients.workday")

IDENTIFIER_RE = re.compile(r"^(?P<tenant>[a-z0-9][a-z0-9_-]*)\.(?P<pod>wd\d+)/(?P<site>[A-Za-z0-9_.-]+)$", re.IGNORECASE)
MULTI_LOCATION_RE = re.compile(r"^\d+\s+locations?$", re.IGNORECASE)


def parse_workday_identifier(identifier: str) -> Tuple[str, str, str]:
    """Splits '<tenant>.<pod>/<site>' into (tenant, pod, site); raises ValueError if malformed."""
    match = IDENTIFIER_RE.match((identifier or "").strip())
    if not match:
        raise ValueError(
            f"Invalid Workday identifier {identifier!r}: expected '<tenant>.<pod>/<site>' (e.g. 'rbc.wd3/RBCGLOBAL1')"
        )
    return match.group("tenant").lower(), match.group("pod").lower(), match.group("site")


def parse_workday_job_url(url: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parses a Workday job URL into (tenant, pod, site, external_path), or None.
    Handles optional locale segments: /en-US/<site>/job/... and /<site>/job/...
    """
    m = re.match(
        r"^https?://(?P<tenant>[a-z0-9_-]+)\.(?P<pod>wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?(?P<site>[A-Za-z0-9_.-]+)(?P<path>/job/[^?#]+)",
        (url or "").strip(),
        re.IGNORECASE,
    )
    if not m:
        return None
    return m.group("tenant").lower(), m.group("pod").lower(), m.group("site"), m.group("path")


_ISO3_SUFFIX = re.compile(r",\s*(CAN|USA)\s*$")


def _clean_label(label: str) -> str:
    """'Toronto, ON, CAN' -> 'Toronto, ON, Canada' (Workday appends ISO-3 country codes)."""
    return _ISO3_SUFFIX.sub(lambda m: ", Canada" if m.group(1) == "CAN" else ", United States", label.strip())


def _parse_start_date(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class WorkdayClient(BaseATSClient):
    """Reusable client for Workday CXS career sites."""

    PAGE_SIZE = 20            # Workday rejects larger pages
    MAX_RESULTS = 2000        # Workday truncates result sets at 2000; treat a total at the ceiling as incomplete
    MAX_PAGES = 200
    DETAIL_WORKERS = 8
    LIST_WORKERS = 4

    def _api_base(self, tenant: str, pod: str, site: str) -> str:
        return f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"

    def _needs_detail(self, title: str, locations_text: str) -> bool:
        """Fetch details for every software/student role exposed by global browsing."""
        return bool(is_swe_role(title) or STUDENT_ENGINEER_REGEX.search(title) or TECHNICAL_PROGRAM_REGEX.search(title))

    # ------------------------------------------------------------------ list phase

    @staticmethod
    def _facet_values(response: Dict[str, Any], predicate) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        for facet in response.get("facets") or []:
            param = facet.get("facetParameter") if isinstance(facet, dict) else None
            if isinstance(param, str) and predicate(param):
                return param, [v for v in facet.get("values") or [] if isinstance(v, dict) and v.get("id")]
        return None, []

    def _collect(self, list_url: str, applied: Dict[str, List[str]], first_page: Optional[Dict[str, Any]] = None):
        """
        Pages through one facet slice. Returns (items, total, raw_count, complete, parse_errors)
        where complete means every page was fetched, no requisition repeated, and the slice
        was safely below Workday's result ceiling.
        """
        page = first_page
        if page is None:
            page = self.http_client.post_json(
                list_url, {"appliedFacets": applied, "limit": self.PAGE_SIZE, "offset": 0, "searchText": ""}
            )
        if not isinstance(page, dict) or not isinstance(page.get("jobPostings"), list) or not isinstance(page.get("total"), int):
            raise IngestionFetchError("Malformed Workday response: expected 'total' and 'jobPostings'.")
        total = page["total"]  # only trustworthy on the first page of a slice
        complete = total < self.MAX_RESULTS
        items: List[Dict[str, Any]] = []
        seen = set()
        parse_errors = 0
        raw_count = 0
        # Workday sometimes lists a requisition twice: once fully and once as a stub carrying
        # only its requisition id. A stub is harmless if that id is listed in full elsewhere.
        stub_req_ids: List[str] = []
        unresolved_stubs: List[str] = []
        full_req_ids = set()

        dup_seen = False
        first_page_paths = {
            it.get("externalPath") for it in page["jobPostings"] if isinstance(it, dict) and it.get("externalPath")
        }

        def absorb(payload: Dict[str, Any]) -> None:
            nonlocal parse_errors, dup_seen
            for item in payload.get("jobPostings") or []:
                path = item.get("externalPath") if isinstance(item, dict) else None
                title = item.get("title") if isinstance(item, dict) else None
                bullets = item.get("bulletFields") if isinstance(item, dict) else None
                req_id = str(bullets[0]) if isinstance(bullets, list) and bullets else None
                if not isinstance(path, str) or not path.startswith("/job/") or not isinstance(title, str) or not title.strip():
                    if req_id and not path and not title:
                        stub_req_ids.append(req_id)
                    else:
                        parse_errors += 1
                elif path in seen:
                    dup_seen = True
                else:
                    seen.add(path)
                    items.append(item)
                    if req_id:
                        full_req_ids.add(req_id)

        raw_count += len(page["jobPostings"])
        absorb(page)
        offsets = list(range(self.PAGE_SIZE, total, self.PAGE_SIZE))
        if len(offsets) + 1 > self.MAX_PAGES:
            offsets = offsets[: self.MAX_PAGES - 1]
            complete = False

        def fetch_page(off: int) -> Optional[Dict[str, Any]]:
            try:
                res = self.http_client.post_json(
                    list_url, {"appliedFacets": applied, "limit": self.PAGE_SIZE, "offset": off, "searchText": ""}
                )
            except IngestionFetchError as err:
                logger.error("Workday page at offset %d failed (%s); slice is partial", off, err)
                return None
            return res if isinstance(res, dict) and isinstance(res.get("jobPostings"), list) else None

        # Fetch pages concurrently so the crawl is short (long crawls see the list shift under them).
        with ThreadPoolExecutor(max_workers=self.LIST_WORKERS) as pool:
            pages_data = list(pool.map(fetch_page, offsets))
        for payload in pages_data:
            if payload is None:
                complete = False
                continue
            raw_count += len(payload["jobPostings"])
            absorb(payload)
        expected_raw = total
        if raw_count != expected_raw:
            complete = False

        # Try to resolve remaining stubs by searching their requisition id. Workday keeps listing
        # requisitions it can no longer render (no title/path) - these are unpublished and are not
        # treated as errors, but they are never ingested.
        for rid in dict.fromkeys(stub_req_ids):
            if rid in full_req_ids:
                continue
            resolved = False
            try:
                found = self.http_client.post_json(
                    list_url, {"appliedFacets": applied, "limit": self.PAGE_SIZE, "offset": 0, "searchText": rid}
                )
                for item in found.get("jobPostings") or [] if isinstance(found, dict) else []:
                    bullets = item.get("bulletFields") if isinstance(item, dict) else None
                    path = item.get("externalPath") if isinstance(item, dict) else None
                    if (isinstance(bullets, list) and rid in [str(b) for b in bullets] and isinstance(path, str)
                            and path.startswith("/job/") and isinstance(item.get("title"), str) and item["title"].strip()):
                        if path not in seen:
                            seen.add(path)
                            items.append(item)
                        resolved = True
                        break
            except IngestionFetchError:
                pass
            if not resolved:
                unresolved_stubs.append(rid)
        if complete:
            # Verify the list did not shift while we paged: totals and the newest page must be unchanged.
            # (Workday itself may list a posting twice; that is only harmless on a stable list.)
            try:
                recheck = self.http_client.post_json(
                    list_url, {"appliedFacets": applied, "limit": self.PAGE_SIZE, "offset": 0, "searchText": ""}
                )
                now_paths = {
                    it.get("externalPath") for it in recheck.get("jobPostings", []) if isinstance(it, dict) and it.get("externalPath")
                } if isinstance(recheck, dict) else None
                if not isinstance(recheck, dict) or recheck.get("total") != total or (dup_seen and now_paths != first_page_paths):
                    complete = False
            except IngestionFetchError:
                complete = False
        if unresolved_stubs:
            logger.info("Workday slice ignored %d unrenderable requisition stub(s)", len(unresolved_stubs))
        return items, total, raw_count, complete, parse_errors

    def fetch_jobs(self, company_name: str, identifier: str) -> FetchResult:
        tenant, pod, site = parse_workday_identifier(identifier)
        api_base = self._api_base(tenant, pod, site)
        public_base = f"https://{tenant}.{pod}.myworkdayjobs.com/{site}"
        list_url = f"{api_base}/jobs"

        # Page 1 must succeed: a failed first request is an outright fetch failure.
        first = self.http_client.post_json(
            list_url, {"appliedFacets": {}, "limit": self.PAGE_SIZE, "offset": 0, "searchText": ""}
        )
        if not isinstance(first, dict) or not isinstance(first.get("jobPostings"), list) or not isinstance(first.get("total"), int):
            raise IngestionFetchError(
                f"Malformed Workday response for '{company_name}' ({identifier}): expected 'total' and 'jobPostings'."
            )

        # Restrict to the US/Canada slice when the tenant has a country facet: those are the only
        # jobs RoleRadar can show, and it keeps large global tenants under Workday's 2000-row ceiling.
        base_facets: Dict[str, List[str]] = {}
        country_param, country_values = self._facet_values(first, lambda p: "country" in p.lower())
        wanted = [v["id"] for v in country_values if str(v.get("descriptor")) in ("Canada", "United States of America", "United States")]
        if country_param and wanted:
            base_facets = {country_param: wanted}

        if base_facets:
            plans = [(base_facets, None)]
        else:
            plans = [({}, first)]

        entries: List[Dict[str, Any]] = []
        seen_paths = set()
        parse_error_count = 0
        raw_count = 0
        complete = True

        def run(applied, first_page):
            nonlocal parse_error_count, raw_count, complete
            items, total, raw, ok, errors = self._collect(list_url, applied, first_page)
            parse_error_count += errors
            raw_count += raw
            complete = complete and ok
            for item in items:
                if item["externalPath"] not in seen_paths:
                    seen_paths.add(item["externalPath"])
                    entries.append(item)
            return total

        total = run(*plans[0])
        if total >= self.MAX_RESULTS:
            # Still at the ceiling: split by job family so each slice fits under it.
            fam_param, fam_values = self._facet_values(first, lambda p: p == "jobFamilyGroup")
            if fam_param and fam_values:
                complete = True
                entries.clear(); seen_paths.clear(); parse_error_count = 0; raw_count = 0
                for value in fam_values:
                    slice_total = run({**base_facets, fam_param: [value["id"]]}, None)
                    if slice_total >= self.MAX_RESULTS:
                        complete = False
                # Every requisition must fall in exactly one family slice.
                if sum(int(v.get("count") or 0) for v in fam_values) < total:
                    complete = False
            else:
                logger.warning("%s: Workday slice at the %d-row ceiling with no partition facet; snapshot cannot be complete", company_name, self.MAX_RESULTS)

        def build(item: Dict[str, Any]) -> Optional[RawJobPosting]:
            path = item["externalPath"]
            title = item["title"].strip()
            locations_text = str(item.get("locationsText") or "").strip()
            # Slugs/requisition ids are only unique within an employer's Workday site.
            source_job_id = f"{tenant}.{pod}/{site}/{path.rstrip('/').rsplit('/', 1)[-1]}"
            source_url = f"{public_base}{path}"
            detail: Dict[str, Any] = {}
            if self._needs_detail(title, locations_text):
                payload = self.http_client.get_json(f"{api_base}{path}")
                info = payload.get("jobPostingInfo") if isinstance(payload, dict) else None
                if not isinstance(info, dict):
                    raise IngestionFetchError(f"Malformed Workday detail for {path}")
                detail = info

            location = _clean_label(str(detail.get("location") or locations_text or ""))
            country_desc = ""
            if isinstance(detail.get("country"), dict):
                country_desc = str(detail["country"].get("descriptor") or "").strip()
            locations = []
            for label in [location] + [_clean_label(x) for x in (detail.get("additionalLocations") or []) if isinstance(x, str)]:
                if not label or MULTI_LOCATION_RE.match(label) or is_home_word(label):
                    continue
                entry: Dict[str, Any] = {"location": label}
                # Tenant-specific shapes ("US, CA, Santa Clara", "16 YORK ST:TORONTO") become one canonical label.
                # The source label is kept as raw_location; anything not confidently parsed stays exactly as published.
                canonical = normalize_workday_location(label)
                if (
                    canonical
                    and canonical["location"] != label
                    and (not country_desc or label != location or canonical["country"] == canonical_country_name(country_desc))
                ):
                    entry = {"location": canonical["location"], "country": canonical["country"], "raw_location": label}
                # Workday's country applies to the primary location only.
                if country_desc and label == location:
                    entry["country"] = country_desc
                locations.append(entry)
            if locations and locations[0].get("raw_location"):
                location = locations[0]["location"]
            return RawJobPosting(
                source_name="workday",
                source_job_id=source_job_id,
                company_name=company_name,
                title=title,
                raw_location=location,
                source_url=source_url,
                posted_at=_parse_start_date(detail.get("startDate")),
                raw_description=str(detail.get("jobDescription") or ""),
                raw_workplace_type=str(detail.get("remoteType")).strip() if detail.get("remoteType") else None,
                raw_job_type=str(detail.get("timeType")).strip() if detail.get("timeType") else None,
                company_apply_url=str(detail.get("externalUrl") or source_url),
                raw_locations=locations,
            )

        def safe_build(item: Dict[str, Any]) -> Tuple[Optional[RawJobPosting], bool]:
            try:
                return build(item), False
            except IngestionFetchError as err:
                logger.warning("%s: Workday detail fetch failed for %s: %s", company_name, item.get("externalPath"), err)
                return None, True

        with ThreadPoolExecutor(max_workers=self.DETAIL_WORKERS) as pool:
            results = list(pool.map(safe_build, entries))

        postings: List[RawJobPosting] = []
        for posting, failed in results:
            if failed:
                parse_error_count += 1
            elif posting is not None:
                postings.append(posting)

        # The snapshot is complete only if every listed requisition is accounted for.
        if len(postings) != len(entries) or parse_error_count:
            complete = False

        logger.info(
            "Parsed %d Workday postings for %s (%s): listed=%d raw=%d parse_errors=%d complete=%s",
            len(postings), company_name, identifier, len(entries), raw_count, parse_error_count, complete,
        )
        return FetchResult(
            jobs=postings,
            parse_error_count=parse_error_count,
            fetch_complete=complete,
            total_raw_records=len(entries) + parse_error_count,
        )
