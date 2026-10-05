"""
Greenhouse Job Board API adapter for RoleRadar.
Fetches and standardizes postings from public Greenhouse boards.
"""

import html
import logging
import re
from datetime import datetime, timezone
from typing import List

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.compensation import build_compensation, interval_from_text
from ingestion.http_client import IngestionFetchError

logger = logging.getLogger("ingestion.clients.greenhouse")


def _greenhouse_compensation(ranges):
    """Structured pay from Greenhouse pay_input_ranges (cents). The description text already carries the employer's prose."""
    if not isinstance(ranges, list):
        return None
    usable = [r for r in ranges if isinstance(r, dict) and r.get("currency_type") and isinstance(r.get("min_cents"), (int, float))]
    currencies = {str(r["currency_type"]).upper() for r in usable}
    if not usable or len(currencies) != 1:
        return None   # mixed currencies: show nothing rather than a misleading blended range
    lows = [r["min_cents"] / 100 for r in usable]
    highs = [(r.get("max_cents") if isinstance(r.get("max_cents"), (int, float)) else r["min_cents"]) / 100 for r in usable]
    intervals = {interval_from_text(str(r.get("title") or "")) for r in usable}
    if len(intervals) > 1:
        return None  # Different or partially unspecified intervals cannot form one truthful range.
    interval = next(iter(intervals))  # An unspecified interval stays unspecified; amount is not evidence.
    result = build_compensation(next(iter(currencies)), min(lows), max(highs), interval, source="greenhouse")
    if result and len({(r["min_cents"], r.get("max_cents")) for r in usable}) > 1:
        result["compensationTierSummary"] += " · Multiple ranges"
        result["ranges"] = [
            {"min": r["min_cents"] / 100, "max": (r.get("max_cents") or r["min_cents"]) / 100, "label": str(r.get("title") or "").strip()}
            for r in usable
        ]
    return result


class GreenhouseClient(BaseATSClient):
    """
    Client for the public Greenhouse Job Board API.
    """

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs?content=true&pay_transparency=true"

    def fetch_jobs(self, company_name: str, identifier: str) -> FetchResult:
        url = self.BASE_URL.format(identifier=identifier)
        payload = self.http_client.get_json(url)

        if not isinstance(payload, dict) or "jobs" not in payload or not isinstance(payload["jobs"], list):
            raise IngestionFetchError(
                f"Malformed Greenhouse response for '{company_name}' ({identifier}): "
                "expected JSON object containing a 'jobs' array."
            )

        postings: List[RawJobPosting] = []
        raw_jobs = payload["jobs"]
        total_raw_records = len(raw_jobs)
        parse_error_count = 0

        for job in raw_jobs:
            if not isinstance(job, dict):
                logger.warning("Skipping non-dict job entry in Greenhouse feed for %s", company_name)
                parse_error_count += 1
                continue

            job_id_val = job.get("id")
            title_val = job.get("title")

            if not isinstance(job_id_val, (str, int)) or not str(job_id_val).strip() or not isinstance(title_val, str) or not title_val.strip():
                logger.warning(
                    "Skipping malformed Greenhouse job record (missing id or title) for %s: %s",
                    company_name,
                    job,
                )
                parse_error_count += 1
                continue

            source_job_id = str(job_id_val).strip()
            title = str(title_val).strip()

            location_raw = ""
            loc_data = job.get("location")
            if isinstance(loc_data, dict):
                location_raw = str(loc_data.get("name") or "").strip()
            elif isinstance(loc_data, str):
                location_raw = loc_data.strip()

            source_url = str(job.get("absolute_url") or "").strip()
            raw_description = str(job.get("content") or "").strip()
            if "&lt;" in raw_description and "&gt;" in raw_description:
                raw_description = html.unescape(raw_description)

            # Parse first_published — the trustworthy original publication date
            # Do NOT use updated_at (reflects any metadata change, not original posting)
            posted_at = None
            first_published_val = job.get("first_published")
            if first_published_val and isinstance(first_published_val, str):
                try:
                    posted_at = datetime.fromisoformat(first_published_val)
                    # Ensure timezone-aware (UTC if naive)
                    if posted_at.tzinfo is None:
                        posted_at = posted_at.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError) as err:
                    logger.warning(
                        "Invalid first_published timestamp %r for %s job %s: %s",
                        first_published_val,
                        company_name,
                        source_job_id,
                        err,
                    )

            job_locations = []
            for field in job.get("metadata") or []:
                if isinstance(field, dict) and str(field.get("name", "")).lower() == "job posting location":
                    values = field.get("value")
                    if isinstance(values, str):
                        values = [values]
                    if isinstance(values, list):
                        job_locations.extend({"location": value} for value in values if isinstance(value, str) and value.strip())

            compensation = _greenhouse_compensation(job.get("pay_input_ranges"))
            # Some boards disclose range-specific caveats separately from content.
            # Preserve those words even when a structured summary cannot safely be built.
            for pay_range in job.get("pay_input_ranges") or []:
                if not isinstance(pay_range, dict) or not isinstance(pay_range.get("blurb"), str):
                    continue
                blurb = pay_range["blurb"].strip()
                normalize = lambda value: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()
                if normalize(blurb) and normalize(blurb) not in normalize(raw_description):
                    raw_description = (raw_description + "\n\n" + blurb).strip()

            postings.append(
                RawJobPosting(
                    source_name="greenhouse",
                    source_job_id=source_job_id,
                    company_name=company_name,
                    title=title,
                    raw_location=location_raw,
                    source_url=source_url,
                    posted_at=posted_at,
                    raw_description=raw_description,
                    raw_locations=job_locations,
                    raw_workplace_type=None,
                    compensation=compensation,
                )
            )

        logger.info(
            "Successfully parsed %d Greenhouse postings for %s (%s) with %d parse errors (total raw: %d)",
            len(postings),
            company_name,
            identifier,
            parse_error_count,
            total_raw_records,
        )
        return FetchResult(
            jobs=postings,
            parse_error_count=parse_error_count,
            fetch_complete=True,
            total_raw_records=total_raw_records,
        )
