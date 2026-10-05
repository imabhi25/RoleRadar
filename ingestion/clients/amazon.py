"""
Amazon.jobs adapter for RoleRadar.

amazon.jobs serves its own careers search from a public JSON endpoint
(https://www.amazon.jobs/en/search.json). The identifier is a 3-letter country code
selecting the slice to ingest, e.g. {"name": "Amazon", "ats": "amazon", "identifier": "CAN"}.
The result is a complete snapshot of that country slice only when every page was
fetched and the collected count equals Amazon's reported hit count.
"""

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.http_client import IngestionFetchError

logger = logging.getLogger("ingestion.clients.amazon")

SEARCH_URL = "https://www.amazon.jobs/en/search.json"
SITE_ROOT = "https://www.amazon.jobs"
# amazon.jobs may answer with zstd, which some urllib3 builds cannot stream-decode.
REQUEST_HEADERS = {"Accept": "application/json", "Accept-Encoding": "gzip, deflate"}


def _parse_posted_date(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%B %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _section(heading: str, html_body: Any) -> str:
    return f"<h3>{heading}</h3><p>{html_body}</p>" if isinstance(html_body, str) and html_body.strip() else ""


class AmazonClient(BaseATSClient):
    PAGE_SIZE = 100
    MAX_PAGES = 150

    def fetch_jobs(self, company_name: str, identifier: str) -> FetchResult:
        country = (identifier or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", country):
            raise ValueError(f"Invalid Amazon identifier {identifier!r}: expected a 3-letter country code such as 'CAN'")

        postings: List[RawJobPosting] = []
        seen_ids = set()
        parse_error_count = 0
        raw_count = 0
        hits: Optional[int] = None
        complete = True
        offset = 0

        for _ in range(self.MAX_PAGES):
            params = {"country": country, "result_limit": self.PAGE_SIZE, "offset": offset, "sort": "recent"}
            try:
                payload = self.http_client.get_json(SEARCH_URL, params=params, headers=REQUEST_HEADERS)
            except IngestionFetchError:
                if offset == 0:
                    raise
                complete = False
                break
            if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list) or not isinstance(payload.get("hits"), int):
                if offset == 0:
                    raise IngestionFetchError("Malformed Amazon response: expected 'hits' and 'jobs'.")
                complete = False
                break
            if hits is None:
                hits = payload["hits"]
            jobs = payload["jobs"]
            if not jobs:
                break
            raw_count += len(jobs)

            for job in jobs:
                if not isinstance(job, dict):
                    parse_error_count += 1
                    continue
                job_id = str(job.get("id_icims") or "").strip()
                title = job.get("title")
                path = job.get("job_path")
                if not job_id or not isinstance(title, str) or not title.strip() or not isinstance(path, str) or not path.startswith("/"):
                    parse_error_count += 1
                    continue
                if job_id in seen_ids:
                    complete = False
                    continue
                seen_ids.add(job_id)

                locations: List[Dict[str, Any]] = []
                for raw_loc in job.get("locations") or []:
                    try:
                        loc = json.loads(raw_loc) if isinstance(raw_loc, str) else raw_loc
                    except ValueError:
                        continue
                    if not isinstance(loc, dict):
                        continue
                    city = str(loc.get("normalizedCityName") or loc.get("city") or "").strip()
                    region = str(loc.get("region") or "").strip()
                    label = ", ".join(x for x in (city, region) if x) or str(loc.get("location") or "").strip()
                    if label:
                        entry = {"location": label, "country": str(loc.get("normalizedCountryCode") or loc.get("countryIso3a") or "")}
                        if entry not in locations:
                            locations.append(entry)

                source_url = f"{SITE_ROOT}{path}"
                description = "".join([
                    str(job.get("description") or ""),
                    _section("Basic Qualifications", job.get("basic_qualifications")),
                    _section("Preferred Qualifications", job.get("preferred_qualifications")),
                ])
                postings.append(
                    RawJobPosting(
                        source_name="amazon",
                        source_job_id=job_id,
                        company_name=company_name,
                        title=title.strip(),
                        raw_location=str(job.get("normalized_location") or job.get("location") or ""),
                        source_url=source_url,
                        posted_at=_parse_posted_date(job.get("posted_date")),
                        raw_description=description,
                        raw_job_type="Intern" if job.get("is_intern") else job.get("job_schedule_type"),
                        company_apply_url=source_url,
                        raw_locations=locations,
                    )
                )

            offset += self.PAGE_SIZE
            if hits is not None and offset >= hits:
                break
        else:
            complete = False

        if hits is None or raw_count != hits or parse_error_count or len(postings) != raw_count:
            complete = False

        logger.info("Parsed %d Amazon postings (%s slice): hits=%s parse_errors=%d complete=%s", len(postings), country, hits, parse_error_count, complete)
        return FetchResult(
            jobs=postings,
            parse_error_count=parse_error_count,
            fetch_complete=complete,
            total_raw_records=raw_count,
        )
