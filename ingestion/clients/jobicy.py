"""
Jobicy Remote Jobs API adapter for RoleRadar.
Fetches and standardizes postings from Jobicy's official public REST API.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.http_client import IngestionFetchError

logger = logging.getLogger("ingestion.clients.jobicy")


class JobicyClient(BaseATSClient):
    """
    Client for Jobicy's official public REST Jobs API (v2).
    """

    DEFAULT_API_URL = "https://jobicy.com/api/v2/remote-jobs"

    def fetch_jobs(
        self,
        company_name: str = "All Companies",
        identifier: str = "",
        count: int = 50,
        geo: Optional[str] = None,
        industry: Optional[str] = None,
        **kwargs,
    ) -> FetchResult:
        """
        Fetches remote job postings from the Jobicy API.

        Args:
            company_name: Display label for the source (default 'All Companies').
            identifier: Optional specific query/category slug.
            count: Number of jobs to fetch (default 50).
            geo: Optional geographic filter (e.g. 'usa', 'canada', 'emea').
            industry: Optional industry category.

        Returns:
            FetchResult containing standardized RawJobPosting records and parse error counts.

        Raises:
            IngestionFetchError: If the remote request fails or payload is malformed.
        """
        params = [f"count={count}"]
        if geo:
            params.append(f"geo={geo}")
        if industry:
            params.append(f"industry={industry}")
        elif identifier:
            params.append(f"tag={identifier}")

        query_str = "&".join(params)
        url = f"{self.DEFAULT_API_URL}?{query_str}"

        payload = self.http_client.get_json(url)

        if not isinstance(payload, dict) or "jobs" not in payload or not isinstance(payload["jobs"], list):
            raise IngestionFetchError(
                f"Malformed Jobicy response from {url}: expected JSON object containing a 'jobs' list."
            )

        postings: List[RawJobPosting] = []
        raw_jobs = payload["jobs"]
        total_raw_records = len(raw_jobs)
        parse_error_count = 0

        for job in raw_jobs:
            if not isinstance(job, dict):
                logger.warning("Skipping non-dict job entry in Jobicy response")
                parse_error_count += 1
                continue

            job_id_val = job.get("id")
            title_val = job.get("jobTitle")
            company_val = job.get("companyName")

            if not job_id_val or not title_val or not company_val:
                logger.warning(
                    "Skipping malformed Jobicy job record (missing id, title, or companyName): %s",
                    job,
                )
                parse_error_count += 1
                continue

            source_job_id = str(job_id_val).strip()
            title = str(title_val).strip()
            extracted_company = str(company_val).strip()

            # Location / geography (default to 'Remote')
            raw_location = str(job.get("jobGeo") or "Remote").strip()

            # Legitimate source URL
            source_url = str(job.get("url") or "").strip()

            # Job description
            raw_description = str(job.get("jobDescription") or "").strip()

            # Workplace type: remote by definition of Jobicy remote jobs API
            raw_workplace_type = "remote"

            # Raw job / employment type (e.g. ["Full-Time"] -> "Full-Time")
            raw_job_type: Optional[str] = None
            jt_val = job.get("jobType")
            if isinstance(jt_val, list):
                raw_job_type = ", ".join(str(item).strip() for item in jt_val if item)
            elif isinstance(jt_val, str):
                raw_job_type = jt_val.strip()

            # Publication date parsing (ISO 8601 string, e.g. '2026-09-25T20:54:07+00:00' or trailing 'Z')
            posted_at: Optional[datetime] = None
            pub_date_raw = job.get("pubDate")
            if pub_date_raw:
                try:
                    date_str = str(pub_date_raw).strip()
                    if date_str.endswith("Z"):
                        date_str = date_str[:-1] + "+00:00"
                    posted_at = datetime.fromisoformat(date_str)
                    if posted_at.tzinfo is None:
                        posted_at = posted_at.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError) as date_err:
                    logger.warning(
                        "Failed to parse pubDate '%s' for Jobicy posting %s: %s",
                        pub_date_raw,
                        source_job_id,
                        date_err,
                    )
                    posted_at = None

            postings.append(
                RawJobPosting(
                    source_name="jobicy",
                    source_job_id=source_job_id,
                    company_name=extracted_company,
                    title=title,
                    raw_location=raw_location,
                    source_url=source_url,
                    posted_at=posted_at,
                    raw_description=raw_description,
                    raw_workplace_type=raw_workplace_type,
                    raw_job_type=raw_job_type,
                )
            )

        logger.info(
            "Successfully parsed %d Jobicy postings with %d parse errors (total raw: %d)",
            len(postings),
            parse_error_count,
            total_raw_records,
        )

        return FetchResult(
            jobs=postings,
            parse_error_count=parse_error_count,
            fetch_complete=True,
            total_raw_records=total_raw_records,
        )
