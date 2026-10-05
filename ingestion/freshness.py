"""
Freshness policy and utilities for RoleRadar.
Defines publication/discovery date distinction and default freshness window.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

# Legacy recency-analysis window; never determines whether a job is open.
DEFAULT_FRESHNESS_DAYS: int = 30

# Freshness semantic status categories
FRESHNESS_RECENTLY_POSTED = "recently_posted"
FRESHNESS_RECENTLY_DISCOVERED = "recently_discovered"
FRESHNESS_ACTIVE = "active"
FRESHNESS_STALE = "stale"
FRESHNESS_INACTIVE = "inactive"

VALID_FRESHNESS_STATUSES = {
    FRESHNESS_RECENTLY_POSTED,
    FRESHNESS_RECENTLY_DISCOVERED,
    FRESHNESS_ACTIVE,
    FRESHNESS_STALE,
    FRESHNESS_INACTIVE,
}

# Rolling window in days for a posting to qualify as "recently_posted".
RECENTLY_POSTED_DAYS: int = 7


def is_job_recently_posted(
    posted_at: Optional[datetime],
    reference_time: Optional[datetime] = None,
    days: int = RECENTLY_POSTED_DAYS,
) -> bool:
    """
    Returns True strictly if the job has a trustworthy posted_at timestamp within the rolling window (default 7 days).
    Never treats NULL posted_at as recently posted (undated jobs are always False).
    Never falls back to created_at, crawl date, or discovery date.
    """
    if posted_at is None:
        return False
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    p_date = posted_at if posted_at.tzinfo is not None else posted_at.replace(tzinfo=timezone.utc)
    cutoff = reference_time - timedelta(days=days)
    return cutoff <= p_date <= reference_time + timedelta(hours=1)


def classify_freshness_status(
    posted_at: Optional[datetime],
    created_at: Optional[datetime],
    is_active: bool = True,
    freshness_days: int = DEFAULT_FRESHNESS_DAYS,
    recently_posted_days: int = RECENTLY_POSTED_DAYS,
    reference_time: Optional[datetime] = None,
) -> str:
    """Label source-confirmed open state separately from publication recency.

    Old and undated open jobs remain active. Discovery time never becomes a
    publication date; its label uses the legacy discovery window only.
    """
    if not is_active:
        return FRESHNESS_INACTIVE

    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    if posted_at is not None:
        p_date = posted_at if posted_at.tzinfo is not None else posted_at.replace(tzinfo=timezone.utc)
        recent_cutoff = reference_time - timedelta(days=recently_posted_days)
        if recent_cutoff <= p_date <= reference_time + timedelta(hours=1):
            return FRESHNESS_RECENTLY_POSTED
        return FRESHNESS_ACTIVE

    # posted_at is NULL: evaluate RoleRadar discovery date
    if created_at is not None:
        c_date = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=timezone.utc)
        stale_cutoff = reference_time - timedelta(days=freshness_days)
        if stale_cutoff <= c_date <= reference_time + timedelta(hours=1):
            return FRESHNESS_RECENTLY_DISCOVERED
        return FRESHNESS_ACTIVE

    return FRESHNESS_ACTIVE


def is_job_fresh(
    posted_at: Optional[datetime],
    created_at: Optional[datetime],
    is_active: bool = True,
    freshness_days: int = DEFAULT_FRESHNESS_DAYS,
    reference_time: Optional[datetime] = None,
) -> bool:
    """
    Evaluates whether a job posting is fresh (recently_posted or recently_discovered)
    and not stale or inactive.
    """
    if not is_active:
        return False
    date = posted_at or created_at
    if date is None:
        return False
    now = reference_time or datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    date = date if date.tzinfo else date.replace(tzinfo=timezone.utc)
    return now - timedelta(days=freshness_days) <= date <= now + timedelta(hours=1)


def get_effective_freshness_date(
    posted_at: Optional[datetime],
    created_at: Optional[datetime],
) -> Optional[datetime]:
    """
    Returns the date used for timeline fallback:
    - Trustworthy source publication date (posted_at) if available.
    - Falls back to RoleRadar discovery date (created_at).
    Note: created_at represents when RoleRadar saw the job, NOT when the company posted it.
    """
    if posted_at is not None:
        return posted_at
    return created_at


def get_freshness_sql_predicate(
    table_alias: str = "jp",
    freshness_days: int = DEFAULT_FRESHNESS_DAYS,
) -> str:
    """
    Returns SQL predicate matching Python freshness classifier:
    (
        ({prefix}posted_at IS NOT NULL
         AND {prefix}posted_at >= NOW() - INTERVAL '{days} days')
        OR
        ({prefix}posted_at IS NULL
         AND {prefix}created_at >= NOW() - INTERVAL '{days} days')
    )
    """
    days = int(freshness_days)
    prefix = f"{table_alias}." if table_alias else ""
    return (
        f"(\n"
        f"    ({prefix}posted_at IS NOT NULL\n"
        f"     AND {prefix}posted_at >= NOW() - INTERVAL '{days} days')\n"
        f"    OR\n"
        f"    ({prefix}posted_at IS NULL\n"
        f"     AND {prefix}created_at >= NOW() - INTERVAL '{days} days')\n"
        f")"
    )


def get_today_freshness_sql_predicate(table_alias: str = "jp") -> str:
    """
    Returns SQL predicate for jobs posted today:
    Requires trustworthy posted_at timestamp within current calendar day.
    Never treats NULL posted_at as posted today (no created_at fallback).
    """
    prefix = f"{table_alias}." if table_alias else ""
    return (
        f"(\n"
        f"    {prefix}posted_at IS NOT NULL\n"
        f"    AND {prefix}posted_at >= (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')\n"
        f"    AND {prefix}posted_at < (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') + INTERVAL '1 day'\n"
        f")"
    )


def get_week_freshness_sql_predicate(
    table_alias: str = "jp",
    freshness_days: int = 7,
) -> str:
    """
    Returns SQL predicate for jobs posted this week:
    Requires trustworthy posted_at timestamp within rolling freshness_days (default 7).
    Never treats NULL posted_at as posted this week (no created_at fallback).
    """
    days = int(freshness_days)
    prefix = f"{table_alias}." if table_alias else ""
    return (
        f"(\n"
        f"    {prefix}posted_at IS NOT NULL\n"
        f"    AND {prefix}posted_at >= NOW() - INTERVAL '{days} days'\n"
        f"    AND {prefix}posted_at <= NOW() + INTERVAL '1 hour'\n"
        f")"
    )


def is_job_posted_today(
    posted_at: Optional[datetime],
    reference_time: Optional[datetime] = None,
) -> bool:
    """
    Returns True if the job has a trustworthy posted_at timestamp within the current calendar day.
    If posted_at is None, returns False (never falls back to created_at).
    """
    if posted_at is None:
        return False
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    p_date = posted_at if posted_at.tzinfo is not None else posted_at.replace(tzinfo=timezone.utc)
    day_start = reference_time.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return day_start <= p_date < day_end


def is_job_posted_this_week(
    posted_at: Optional[datetime],
    freshness_days: int = 7,
    reference_time: Optional[datetime] = None,
) -> bool:
    """
    Returns True if the job has a trustworthy posted_at timestamp within rolling freshness_days.
    If posted_at is None, returns False (never falls back to created_at).
    """
    if posted_at is None:
        return False
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    p_date = posted_at if posted_at.tzinfo is not None else posted_at.replace(tzinfo=timezone.utc)
    cutoff = reference_time - timedelta(days=freshness_days)
    # Allows small 1h clock skew for future timestamps
    return cutoff <= p_date <= reference_time + timedelta(hours=1)



# ---------------------------------------------------------------------------
# Public visibility window (separate from source-truth is_active)
# ---------------------------------------------------------------------------

# Jobs older than this are excluded from the normal PUBLIC listing even while the employer still
# lists them. This never touches is_active: rows are kept, and they reappear/disappear purely by date.
PUBLIC_VISIBILITY_DAYS: int = 30
# An undated (or implausibly future-dated) job is shown only if RoleRadar first saw it inside the public window AND
# the official source still listed it in the last two days of syncs (last_seen_at refreshes on every sync).
# RoleRadar never fabricates a posting date for such jobs.
UNDATED_VERIFICATION_HOURS: int = 48
# Employer dates may run slightly ahead (date-only sources, clock skew): through tomorrow counts as a real date.
FUTURE_DATE_TOLERANCE_DAYS: int = 2


def get_public_visibility_sql_predicate(
    table_alias: str = "jp",
    days: int = PUBLIC_VISIBILITY_DAYS,
    verification_hours: int = UNDATED_VERIFICATION_HOURS,
) -> str:
    """
    SQL for the rolling public visibility window (timestamp comparisons are timezone-independent):

    - dated job: posted_at on or after NOW minus `days` days, and not beyond tomorrow
      (the exact cutoff is included; one microsecond older is excluded)
    - undated job, or a posted_at further in the future than the tolerance: first seen inside the window AND
      still listed by the official source within `verification_hours`
    """
    prefix = f"{table_alias}." if table_alias else ""
    days = int(days)
    hours = int(verification_hours)
    today = "(date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')"
    return (
        f"(\n"
        f"    ({prefix}posted_at IS NOT NULL\n"
        f"     AND {prefix}posted_at >= NOW() - INTERVAL '{days} days'\n"
        f"     AND {prefix}posted_at < {today} + INTERVAL '{FUTURE_DATE_TOLERANCE_DAYS} days')\n"
        f"    OR\n"
        f"    (({prefix}posted_at IS NULL OR {prefix}posted_at >= {today} + INTERVAL '{FUTURE_DATE_TOLERANCE_DAYS} days')\n"
        f"     AND {prefix}created_at >= NOW() - INTERVAL '{days} days'\n"
        f"     AND {prefix}last_seen_at >= NOW() - INTERVAL '{hours} hours')\n"
        f")"
    )


def is_publicly_visible(
    posted_at: Optional[datetime],
    last_seen_at: Optional[datetime],
    reference_time: Optional[datetime] = None,
    days: int = PUBLIC_VISIBILITY_DAYS,
    verification_hours: int = UNDATED_VERIFICATION_HOURS,
    first_seen_at: Optional[datetime] = None,
) -> bool:
    """Python mirror of get_public_visibility_sql_predicate (for tests and callers without SQL)."""
    now = reference_time or datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    day_start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = now - timedelta(days=days)
    tomorrow_end = day_start + timedelta(days=FUTURE_DATE_TOLERANCE_DAYS)

    def aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    if posted_at is not None and aware(posted_at) < tomorrow_end:
        return aware(posted_at) >= window_start
    # undated, or a future date that cannot be trusted
    if last_seen_at is None or first_seen_at is None:
        return False
    first_seen = aware(first_seen_at)
    return first_seen >= window_start and aware(last_seen_at) >= now - timedelta(hours=verification_hours)
