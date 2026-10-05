"""
RoleRadar Ingestion Package
Provides foundation tools, ATS clients, and data pipelines for job ingestion.
"""

from ingestion.extractor import extract_skills, sanitize_html_description, sanitize_html_to_text
from ingestion.freshness import (
    DEFAULT_FRESHNESS_DAYS,
    FRESHNESS_INACTIVE,
    FRESHNESS_RECENTLY_DISCOVERED,
    FRESHNESS_RECENTLY_POSTED,
    FRESHNESS_STALE,
    VALID_FRESHNESS_STATUSES,
    classify_freshness_status,
    get_effective_freshness_date,
    get_freshness_sql_predicate,
    get_today_freshness_sql_predicate,
    get_week_freshness_sql_predicate,
    is_job_fresh,
    is_job_posted_this_week,
    is_job_posted_today,
)
from ingestion.http_client import HardenedHttpClient, IngestionFetchError
from ingestion.normalizer import (
    VALID_ROLE_TYPES,
    classify_role_type,
    classify_workplace,
    is_swe_role,
    normalize_location_and_country,
)

__all__ = [
    "HardenedHttpClient",
    "IngestionFetchError",
    "sanitize_html_to_text",
    "sanitize_html_description",
    "extract_skills",
    "is_swe_role",
    "classify_workplace",
    "normalize_location_and_country",
    "classify_role_type",
    "VALID_ROLE_TYPES",
    "DEFAULT_FRESHNESS_DAYS",
    "FRESHNESS_RECENTLY_POSTED",
    "FRESHNESS_RECENTLY_DISCOVERED",
    "FRESHNESS_STALE",
    "FRESHNESS_INACTIVE",
    "VALID_FRESHNESS_STATUSES",
    "classify_freshness_status",
    "get_effective_freshness_date",
    "get_freshness_sql_predicate",
    "get_today_freshness_sql_predicate",
    "get_week_freshness_sql_predicate",
    "is_job_fresh",
    "is_job_posted_today",
    "is_job_posted_this_week",
]
