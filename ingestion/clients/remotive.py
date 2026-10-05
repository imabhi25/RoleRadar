"""
Remotive Remote Jobs API adapter for RoleRadar.
Fetches and standardizes postings from Remotive's official public REST API.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.http_client import IngestionFetchError

logger = logging.getLogger("ingestion.clients.remotive")


class RemotiveClient(BaseATSClient):
    """
    Client for Remotive's official public Remote Jobs API.
    Preserves attribution and source URLs in compliance with Remotive API terms.
    """

    DEFAULT_API_URL = "https://remotive.com/api/remote-jobs"

    def fetch_jobs(
        self,
        company_name: str = "All Companies",
        identifier: str = "",
        category: Optional[str] = "software-development",
        limit: Optional[int] = None,
        count: Optional[int] = None,
        **kwargs,
    ) -> FetchResult:
        """
        Fetches remote job postings from the Remotive public API.

        Args:
            company_name: Display label for the source (default 'All Companies').
            identifier: Optional specific category slug (overrides category arg if provided).
            category: Job category slug (default 'software-development').
            limit: Optional maximum number of jobs to fetch.
            count: Alias for limit for uniform broad-source interface.

        Returns:
            FetchResult containing standardized RawJobPosting records and parse error counts.

        Raises:
            IngestionFetchError: If the remote request fails or payload is malformed.
        """
        effective_limit = limit or count
        cat_slug = identifier.strip() if identifier else (category.strip() if category else None)

        params: List[str] = []
        if cat_slug:
            params.append(f"category={cat_slug}")
        if effective_limit:
            params.append(f"limit={effective_limit}")

        query_str = f"?{'&'.join(params)}" if params else ""
        url = f"{self.DEFAULT_API_URL}{query_str}"

        payload = self.http_client.get_json(url)

        if not isinstance(payload, dict) or "jobs" not in payload or not isinstance(payload["jobs"], list):
            raise IngestionFetchError(
                f"Malformed Remotive response from {url}: expected JSON object containing a 'jobs' list."
            )

        raw_jobs = payload["jobs"]
        if effective_limit:
            raw_jobs = raw_jobs[:effective_limit]

        total_raw_records = len(raw_jobs)
        postings: List[RawJobPosting] = []
        parse_error_count = 0

        for job in raw_jobs:
            if not isinstance(job, dict):
                logger.warning("Skipping non-dict job entry in Remotive response")
                parse_error_count += 1
                continue

            job_id_val = job.get("id")
            title_val = job.get("title")
            company_val = job.get("company_name")

            if not job_id_val or not title_val or not company_val:
                logger.warning(
                    "Skipping malformed Remotive job record (missing id, title, or company_name): %s",
                    job,
                )
                parse_error_count += 1
                continue

            source_job_id = str(job_id_val).strip()
            title = str(title_val).strip()
            extracted_company = str(company_val).strip()

            # Location / candidate location (default to 'Remote')
            raw_location = str(job.get("candidate_required_location") or "Remote").strip()

            # Preserve legitimate source URL pointing to Remotive as required by API terms
            source_url = str(job.get("url") or "").strip()

            # Job description
            raw_description = str(job.get("description") or "").strip()

            # Workplace type: Remote by definition of Remotive
            raw_workplace_type = "remote"

            # Raw job / employment type (e.g. 'full_time', 'contract')
            raw_job_type_val = job.get("job_type")
            raw_job_type = str(raw_job_type_val).strip() if raw_job_type_val else None

            # Publication date parsing (ISO format string, e.g. '2026-09-18T16:43:22')
            posted_at: Optional[datetime] = None
            pub_date_raw = job.get("publication_date")
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
                        "Failed to parse publication_date '%s' for Remotive posting %s: %s",
                        pub_date_raw,
                        source_job_id,
                        date_err,
                    )
                    posted_at = None

            postings.append(
                RawJobPosting(
                    source_name="remotive",
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
            "Successfully parsed %d Remotive postings with %d parse errors (total raw: %d)",
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

    def get_attribution(self) -> str:
        """Returns required attribution text for Remotive API usage."""
        return getattr(self, "_legal_notice", None) or "Job listings powered by Remotive (https://remotive.com)."
