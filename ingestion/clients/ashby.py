"""
Ashby Job Board GET API adapter for RoleRadar.
Fetches and standardizes postings from public Ashby job boards.
"""

from datetime import datetime, timezone
import logging
from typing import List

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.http_client import IngestionFetchError

logger = logging.getLogger("ingestion.clients.ashby")


class AshbyClient(BaseATSClient):
    """
    Client for the public Ashby Job Board GET endpoint.
    """

    BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{identifier}"

    def fetch_jobs(self, company_name: str, identifier: str) -> FetchResult:
        url = self.BASE_URL.format(identifier=identifier)
        payload = self.http_client.get_json(url, params={"includeCompensation": "true"})

        if not isinstance(payload, dict) or "jobs" not in payload or not isinstance(payload["jobs"], list):
            raise IngestionFetchError(
                f"Malformed Ashby response for '{company_name}' ({identifier}): "
                "expected JSON object containing a 'jobs' array."
            )

        postings: List[RawJobPosting] = []
        raw_jobs = payload["jobs"]
        total_raw_records = len(raw_jobs)
        parse_error_count = 0

        for job in raw_jobs:
            if not isinstance(job, dict):
                logger.warning("Skipping non-dict job entry in Ashby feed for %s", company_name)
                parse_error_count += 1
                continue

            job_id_val = job.get("id")
            title_val = job.get("title")

            if not isinstance(job_id_val, (str, int)) or not str(job_id_val).strip() or not isinstance(title_val, str) or not title_val.strip():
                logger.warning(
                    "Skipping malformed Ashby job record (missing id or title) for %s: %s",
                    company_name,
                    job,
                )
                parse_error_count += 1
                continue

            source_job_id = str(job_id_val).strip()
            title = str(title_val).strip()

            location_raw = ""
            loc_val = job.get("locationName") or job.get("location")
            if isinstance(loc_val, str):
                location_raw = loc_val.strip()
            elif isinstance(loc_val, dict):
                location_raw = str(loc_val.get("name") or "").strip()

            raw_workplace_type = None
            if job.get("workplaceType"):
                raw_workplace_type = str(job["workplaceType"]).strip()
            elif job.get("isRemote") is True:
                raw_workplace_type = "Remote"

            source_url = str(job.get("jobUrl") or job.get("applyUrl") or "").strip()
            raw_description = str(job.get("descriptionHtml") or job.get("description") or job.get("descriptionPlain") or "").strip()

            posted_at = None
            published_val = job.get("publishedAt")
            if published_val and isinstance(published_val, str):
                try:
                    posted_at = datetime.fromisoformat(published_val.replace("Z", "+00:00"))
                    if posted_at.tzinfo is None:
                        posted_at = posted_at.replace(tzinfo=timezone.utc)
                except ValueError as err:
                    logger.warning(
                        "Invalid publishedAt ISO timestamp %r for %s job %s: %s",
                        published_val,
                        company_name,
                        source_job_id,
                        err,
                    )

            postings.append(
                RawJobPosting(
                    source_name="ashby",
                    source_job_id=source_job_id,
                    company_name=company_name,
                    title=title,
                    raw_location=location_raw,
                    source_url=source_url,
                    posted_at=posted_at,
                    raw_description=raw_description,
                    raw_workplace_type=raw_workplace_type,
                    company_apply_url=job.get("applyUrl"),
                    raw_job_type=job.get("employmentType"),
                    is_listed=job.get("isListed") is not False,
                    compensation=job.get("compensation") if isinstance(job.get("compensation"), dict) else None,
                    raw_locations=[{"location": location_raw, "address": job.get("address")}]
                        + [loc for loc in job.get("secondaryLocations", []) if isinstance(loc, dict)],
                )
            )

        logger.info(
            "Successfully parsed %d Ashby postings for %s (%s) with %d parse errors (total raw: %d)",
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
