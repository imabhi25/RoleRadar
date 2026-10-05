"""
Arbeitnow Job Board API adapter for RoleRadar.
Fetches and standardizes postings from Arbeitnow's official public REST API.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional, Set

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.http_client import IngestionFetchError

logger = logging.getLogger("ingestion.clients.arbeitnow")


class ArbeitnowClient(BaseATSClient):
    """
    Client for Arbeitnow's official public job board API.
    Handles bounded pagination and maps diverse European/global tech listings.
    """

    DEFAULT_API_URL = "https://www.arbeitnow.com/api/job-board-api"

    def fetch_jobs(
        self,
        company_name: str = "All Companies",
        identifier: str = "",
        max_pages: int = 2,
        count: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> FetchResult:
        """
        Fetches job postings from the Arbeitnow public API with bounded pagination.

        Args:
            company_name: Display label for the source (default 'All Companies').
            identifier: Optional unused identifier token.
            max_pages: Maximum number of pagination pages to traverse (default 2, ~500 postings).
            count: Optional maximum number of jobs to return.
            limit: Alias for count for uniform broad-source interface.

        Returns:
            FetchResult containing standardized RawJobPosting records and parse error counts.

        Raises:
            IngestionFetchError: If the initial remote request fails or payload is malformed.
        """
        effective_limit = count or limit
        postings: List[RawJobPosting] = []
        seen_ids: Set[str] = set()
        total_raw_records = 0
        parse_error_count = 0
        current_url: Optional[str] = self.DEFAULT_API_URL
        page_num = 1
        fetch_complete = True

        while current_url and page_num <= max_pages:
            logger.info("Fetching Arbeitnow page %d from %s", page_num, current_url)
            try:
                payload = self.http_client.get_json(current_url)
            except IngestionFetchError as err:
                if page_num == 1:
                    raise
                logger.warning("Arbeitnow fetch failed on page %d: %s. Terminating pagination.", page_num, err)
                fetch_complete = False
                break

            if not isinstance(payload, dict) or "data" not in payload or not isinstance(payload["data"], list):
                if page_num == 1:
                    raise IngestionFetchError(
                        f"Malformed Arbeitnow response from {current_url}: expected JSON object with 'data' list."
                    )
                logger.warning("Malformed Arbeitnow payload on page %d; terminating pagination.", page_num)
                fetch_complete = False
                break

            raw_jobs = payload["data"]
            if not raw_jobs:
                break

            total_raw_records += len(raw_jobs)

            for job in raw_jobs:
                if not isinstance(job, dict):
                    logger.warning("Skipping non-dict job entry in Arbeitnow response")
                    parse_error_count += 1
                    continue

                slug_val = job.get("slug")
                title_val = job.get("title")
                company_val = job.get("company_name")

                if not slug_val or not title_val or not company_val:
                    logger.warning(
                        "Skipping malformed Arbeitnow job record (missing slug, title, or company_name): %s",
                        job,
                    )
                    parse_error_count += 1
                    continue

                source_job_id = str(slug_val).strip()
                if source_job_id in seen_ids:
                    # Duplicate slug across pages
                    continue
                seen_ids.add(source_job_id)

                title = str(title_val).strip()
                extracted_company = str(company_val).strip()

                # Location & Remote status
                is_remote_flag = bool(job.get("remote", False))
                loc_raw = job.get("location")
                if loc_raw and str(loc_raw).strip():
                    raw_location = str(loc_raw).strip()
                elif is_remote_flag:
                    raw_location = "Remote"
                else:
                    raw_location = "Unknown"

                # Workplace type mapping
                raw_workplace_type: Optional[str] = "remote" if is_remote_flag else None

                # Source URL
                source_url = str(job.get("url") or "").strip()

                # Description
                raw_description = str(job.get("description") or "").strip()

                # Job type from job_types array or tags
                raw_job_type: Optional[str] = None
                jt_val = job.get("job_types")
                if isinstance(jt_val, list) and jt_val:
                    raw_job_type = ", ".join(str(t).strip() for t in jt_val if t)
                elif isinstance(jt_val, str) and jt_val.strip():
                    raw_job_type = jt_val.strip()

                # Publication timestamp from created_at Unix integer
                posted_at: Optional[datetime] = None
                created_at_raw = job.get("created_at")
                if created_at_raw is not None:
                    try:
                        ts = float(created_at_raw)
                        posted_at = datetime.fromtimestamp(ts, tz=timezone.utc)
                    except (ValueError, TypeError, OverflowError) as ts_err:
                        logger.warning(
                            "Failed to parse created_at timestamp '%s' for Arbeitnow posting %s: %s",
                            created_at_raw,
                            source_job_id,
                            ts_err,
                        )
                        posted_at = None

                postings.append(
                    RawJobPosting(
                        source_name="arbeitnow",
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

                if effective_limit and len(postings) >= effective_limit:
                    break

            if effective_limit and len(postings) >= effective_limit:
                break

            # Handle next page link from 'links.next'
            links = payload.get("links")
            if isinstance(links, dict) and links.get("next"):
                current_url = links["next"]
                page_num += 1
            else:
                break

        logger.info(
            "Successfully parsed %d Arbeitnow postings across %d page(s) with %d parse errors (total raw: %d)",
            len(postings),
            page_num,
            parse_error_count,
            total_raw_records,
        )

        return FetchResult(
            jobs=postings,
            parse_error_count=parse_error_count,
            fetch_complete=fetch_complete,
            total_raw_records=total_raw_records,
        )

    def get_attribution(self) -> str:
        """Returns attribution text for Arbeitnow API usage."""
        return "Job listings powered by Arbeitnow (https://www.arbeitnow.com)."
