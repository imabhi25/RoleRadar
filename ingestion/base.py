"""
Base models and abstractions for RoleRadar ATS adapters.
Defines the standard RawJobPosting dataclass and BaseATSClient interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from ingestion.http_client import HardenedHttpClient


@dataclass
class RawJobPosting:
    """
    Standardized, vendor-agnostic representation of a raw job posting extracted from an ATS feed.
    """
    source_name: str
    source_job_id: str
    company_name: str
    title: str
    raw_location: str
    source_url: str
    posted_at: Optional[datetime]
    raw_description: str
    raw_workplace_type: Optional[str] = None
    raw_job_type: Optional[str] = None
    role_type: Optional[str] = None
    company_apply_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    simplify_url: Optional[str] = None
    raw_locations: list[dict] = field(default_factory=list)
    compensation: Optional[dict] = None
    is_listed: bool = True
    # Structured academic-term strings supplied by the source (e.g. ['Summer 2027']).
    raw_terms: list = field(default_factory=list)


@dataclass
class FetchResult:
    """
    Encapsulates the result of fetching jobs from an ATS board,
    including parse error tracking for fail-safe tombstoning.
    Implements sequence methods for seamless backward compatibility.
    """
    jobs: List[RawJobPosting]
    parse_error_count: int
    fetch_complete: bool
    total_raw_records: int

    def __iter__(self):
        return iter(self.jobs)

    def __len__(self) -> int:
        return len(self.jobs)

    def __getitem__(self, idx):
        return self.jobs[idx]


class BaseATSClient(ABC):
    """
    Abstract interface for all ATS adapter clients (Greenhouse, Lever, Ashby).
    """

    def __init__(self, http_client: Optional[HardenedHttpClient] = None) -> None:
        self.http_client = http_client or HardenedHttpClient()

    @abstractmethod
    def fetch_jobs(self, company_name: str, identifier: str) -> FetchResult:
        """
        Fetches and translates raw job postings from the ATS board for the specified company.

        Args:
            company_name: Canonical display name of the hiring organization (e.g. 'Figma').
            identifier: Vendor-specific board token, slug, or organization name (e.g. 'figma').

        Returns:
            A FetchResult containing parsed RawJobPosting objects and parse-error metrics.

        Raises:
            IngestionFetchError: If the remote fetch fails or returns a malformed source response.
        """
        pass
