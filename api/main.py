"""
FastAPI application for RoleRadar Career Intelligence platform.
Provides analytics and metrics endpoints backed by PostgreSQL, along with
the Job Explorer API for active SWE postings.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Union, Tuple
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.database import get_db_cursor
from api.search_text import fold_search_clause, parse_search_query
from main import CANONICAL_SKILL_NAMES
from ingestion.freshness import (
    RECENTLY_POSTED_DAYS,
    classify_freshness_status,
    get_public_visibility_sql_predicate,
    get_today_freshness_sql_predicate,
    get_week_freshness_sql_predicate,
    is_job_recently_posted,
)
from ingestion.normalizer import (
    EARLY_CAREER_ROLE_TYPES,
    SUPPORTED_TERM_SEASONS,
    VALID_ROLE_TYPES,
    get_user_facing_geography_sql_predicate,
    official_sources_sql,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database migrations are applied on startup (skip during pytest / unit tests)
    is_testing = bool(os.getenv("PYTEST_CURRENT_TEST") or "unittest" in sys.modules or os.getenv("TESTING"))
    if not os.getenv("SKIP_MIGRATIONS") and not is_testing:
        try:
            from db.migrate import run_migrations
            logger.info("Checking and applying pending database migrations on startup...")
            # Source identity changes wait for the production ingestion concurrency group.
            # Render startup may occur while an older ingestion snapshot is still running.
            run_migrations(defer_versions={"013_scope_workday_identities.sql"})
            logger.info("Database migrations check complete.")
        except Exception as err:
            logger.warning("Database migrations on startup encountered an issue: %s", err)
    yield


app = FastAPI(
    title="RoleRadar Career Intelligence API",
    description="REST API for tech market intelligence and job posting analytics.",
    version="0.3.0",
    lifespan=lifespan,
)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://jobber-mauve.vercel.app",
]

frontend_origin_env = os.getenv("FRONTEND_ORIGIN")
if frontend_origin_env:
    for origin in frontend_origin_env.split(","):
        cleaned = origin.strip().rstrip("/")
        if cleaned and cleaned not in origins:
            origins.append(cleaned)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https://([a-zA-Z0-9-]+\.)*vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


@app.middleware("http")
async def add_security_headers(request, call_next):
    """JSON API only: nothing here is meant to be framed, sniffed or rendered, so say so on every response."""
    response = await call_next(request)
    interactive_docs = request.url.path.startswith(("/docs", "/redoc"))  # Swagger UI needs its own scripts/styles
    for name, value in SECURITY_HEADERS.items():
        if interactive_docs and name == "Content-Security-Policy":
            continue
        response.headers.setdefault(name, value)
    return response


@app.get("/api/health")
def health_check():
    """Health check endpoint for deployment monitoring."""
    db_status = "unknown"
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT 1;")
            db_status = "connected"
    except Exception as err:
        logger.error("Health database check failed: %s", err)
        db_status = "unavailable"
    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "version": "0.3.0",
        "commit": os.getenv("RENDER_GIT_COMMIT") or os.getenv("VERCEL_GIT_COMMIT_SHA"),
        "database": db_status,
    }


# --- Response Models ---

class OverviewStats(BaseModel):
    total_postings: int
    total_companies: int
    total_locations: int
    total_skills: int
    recently_posted_postings: Optional[int] = None
    last_refreshed_at: Optional[datetime] = None


class CountryStats(BaseModel):
    country: str
    postings: int
    share_pct: float


class SkillStats(BaseModel):
    rank: int
    skill: str
    mentions: int
    frequency_pct: float


class BreakdownItem(BaseModel):
    category: str
    count: int
    share_pct: float


class JobSummary(BaseModel):
    job_id: str
    title: str
    company: str
    company_logo_url: Optional[str] = None
    company_logo_status: Optional[str] = None
    location: str
    country: str
    workplace_type: str
    role_type: str = "unknown"
    experience_level: Optional[str] = None
    source_name: str
    source_url: Optional[str] = None
    company_apply_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    simplify_url: Optional[str] = None
    term_season: Optional[str] = None
    term_year: Optional[int] = None
    academic_term: Optional[str] = None
    posted_at: Optional[datetime] = None
    # "date" when the employer published a calendar date only (Workday/Amazon, or an exact UTC-midnight stamp); never invent hours
    posted_at_precision: Optional[str] = None
    created_at: Optional[datetime] = None
    freshness_status: str = "recently_posted"
    recently_posted: bool = False
    skills: List[str]
    locations: List[dict] = Field(default_factory=list)
    compensation: Optional[dict] = None


class JobListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    jobs: List[JobSummary]


class JobFilterOptions(BaseModel):
    countries: List[str]
    companies: List[str]
    skills: List[str]
    workplace_types: List[str]
    role_types: List[str]
    locations: List[str] = Field(default_factory=list)
    experience_levels: List[str] = Field(default_factory=list)



class CompanyInfo(BaseModel):
    id: Optional[int] = None
    name: str
    logo_url: Optional[str] = None
    logo_source_url: Optional[str] = None
    logo_status: str = "unresolved"
    website_url: Optional[str] = None
    active_jobs_count: int = 0


class JobDetail(BaseModel):
    job_id: str
    title: str
    company: str
    company_logo_url: Optional[str] = None
    company_logo_status: Optional[str] = None
    company_website_url: Optional[str] = None
    location: str
    country: str
    workplace_type: str
    role_type: str = "unknown"
    experience_level: Optional[str] = None
    source_name: str
    source_url: Optional[str] = None
    company_apply_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    simplify_url: Optional[str] = None
    term_season: Optional[str] = None
    term_year: Optional[int] = None
    academic_term: Optional[str] = None
    posted_at: Optional[datetime] = None
    # "date" when the employer published a calendar date only (Workday/Amazon, or an exact UTC-midnight stamp); never invent hours
    posted_at_precision: Optional[str] = None
    created_at: Optional[datetime] = None
    freshness_status: str = "recently_posted"
    recently_posted: bool = False
    description: Optional[str] = None
    skills: List[str]
    locations: List[dict] = Field(default_factory=list)
    compensation: Optional[dict] = None


def get_deduplication_sql_predicate(table_alias: str = "jp") -> str:
    """Suppress only matching source identities or exact job URLs, never text similarity.

    "No later duplicate by source id OR by URL" is written as two separate NOT EXISTS terms. A single NOT EXISTS with
    an OR between the two keys cannot be hash-joined, so PostgreSQL compared every row with every other row (about
    2.5 million comparisons for 3,700 jobs, and quadratic as the inventory grows). Each equality key on its own is
    a hash anti join. The two forms are logically identical.
    """
    def later_duplicate(match: str) -> str:
        return f"""NOT EXISTS (
        SELECT 1 FROM job_postings jp2
        JOIN locations l2 ON l2.id = jp2.location_id
        WHERE jp2.is_active = TRUE
          AND jp2.is_eligible_role = TRUE
          AND {get_user_facing_geography_sql_predicate(location_alias="l2")}
          AND jp2.source_name IN {official_sources_sql()}
          AND jp2.id > {table_alias}.id
          AND {match}
    )"""

    same_source_id = (
        f"jp2.source_name = {table_alias}.source_name "
        f"AND NULLIF(jp2.source_job_id, '') = {table_alias}.source_job_id"
    )
    same_url = (
        "NULLIF(split_part(jp2.source_url, '#', 1), '') = "
        f"NULLIF(split_part({table_alias}.source_url, '#', 1), '')"
    )
    return f"({later_duplicate(same_source_id)} AND {later_duplicate(same_url)})"


DATE_ONLY_SOURCES = ("workday", "amazon", "shopify", "phenom", "successfactors")


def posted_at_precision(source_name: Optional[str], posted_at: Optional[datetime]) -> Optional[str]:
    """"date" for calendar-date-only postings (the source gave no time of day), "time" for real timestamps."""
    if posted_at is None:
        return None
    if (source_name or "").lower() in DATE_ONLY_SOURCES:
        return "date"
    stamp = posted_at.astimezone(timezone.utc) if posted_at.tzinfo else posted_at
    return "date" if (stamp.hour, stamp.minute, stamp.second, stamp.microsecond) == (0, 0, 0, 0) else "time"


def get_target_postings_cte(extra_columns: str = "") -> str:
    """
    Returns the centralized CTE for target active postings matching all visibility rules:
    - Active jobs verified by official ATS feeds
    - Eligible user-facing geography (United States and Canada)
    - Strict deduplication rules
    - The 30-day public visibility window (age hides a job from the public list; it never deactivates it).
      Active status itself is still determined solely by source presence.
    """
    geography_predicate = get_user_facing_geography_sql_predicate(location_alias="l")
    dedup_predicate = get_deduplication_sql_predicate(table_alias="jp")
    cols = f", {extra_columns}" if extra_columns else ""
    return f"""
    WITH active_real AS (
        SELECT jp.id, jp.company_id, jp.location_id, jp.posted_at, jp.created_at, jp.role_type, jp.workplace_type, l.country{cols}
        FROM job_postings jp
        JOIN locations l ON jp.location_id = l.id
        WHERE jp.source_name != 'sample' AND jp.source_name IN {official_sources_sql()} AND jp.is_eligible_role = TRUE
          AND jp.is_active = TRUE
          AND {geography_predicate}
          AND {dedup_predicate}
          AND {get_public_visibility_sql_predicate(table_alias="jp")}
    ),
    target_postings AS (
        SELECT * FROM active_real
    )
    """


# --- Analytics Endpoints ---

class SourceStatus(BaseModel):
    source_name: str
    status: str  # "healthy" | "degraded" | "unknown"
    companies_tracked: int
    companies_ok: int
    companies_degraded: int
    active_jobs: int
    last_success_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None


@app.get("/api/sources/status", response_model=List[SourceStatus])
def get_source_status():
    """Per-source refresh health from each employer's most recent ingestion run.

    A source is "degraded" when any tracked employer's latest run failed or only partly succeeded (its jobs were
    kept, not closed, in that case); "healthy" when every latest run succeeded. Error text is deliberately not
    exposed here.
    """
    query = """
    WITH latest AS (
        SELECT DISTINCT ON (source_name, company_identifier)
               source_name, company_identifier, status, started_at
        FROM sync_runs
        WHERE status <> 'running'
        ORDER BY source_name, company_identifier, started_at DESC
    ), last_ok AS (
        SELECT source_name, MAX(completed_at) AS at FROM sync_runs WHERE status = 'success' GROUP BY source_name
    ), active AS (
        SELECT source_name, COUNT(*) AS n FROM job_postings WHERE is_active AND is_eligible_role GROUP BY source_name
    )
    SELECT l.source_name,
           COUNT(*) AS tracked,
           COUNT(*) FILTER (WHERE l.status = 'success') AS ok,
           COUNT(*) FILTER (WHERE l.status <> 'success') AS degraded,
           COALESCE(MAX(a.n), 0) AS active_jobs,
           MAX(o.at) AS last_success_at,
           MAX(l.started_at) AS last_attempt_at
    FROM latest l
    LEFT JOIN last_ok o ON o.source_name = l.source_name
    LEFT JOIN active a ON a.source_name = l.source_name
    GROUP BY l.source_name
    ORDER BY l.source_name;
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
    except psycopg2.Error as err:
        logger.error("Database query failed in /api/sources/status: %s", err)
        raise HTTPException(status_code=500, detail="Database query error.")
    return [
        {
            "source_name": r[0],
            "status": "degraded" if r[3] else "healthy",
            "companies_tracked": r[1],
            "companies_ok": r[2],
            "companies_degraded": r[3],
            "active_jobs": int(r[4]),
            "last_success_at": r[5],
            "last_attempt_at": r[6],
        }
        for r in rows
    ]


@app.get("/api/stats/overview", response_model=OverviewStats)
def get_overview_stats(
    country: Optional[List[str]] = Query(default=None, description="Optional country scope, identical to /api/jobs (a job counts for a country when any of its locations is there)"),
):
    """
    Returns aggregate counts for postings, companies, locations, and skills,
    along with the last successful completed ingestion refresh timestamp.
    Uses active, fresh real jobs if present, falling back to sample jobs when none exist.
    Explicitly distinguishes total active postings from recently_posted_postings.
    With ?country=, every figure is scoped with the same rule /api/jobs uses, so the totals match the job list.
    """
    reject_nul(country)
    countries = canonicalize_countries(country)
    if countries:
        placeholders = ", ".join(["LOWER(%s)"] * len(countries))
        cte = get_target_postings_cte(extra_columns="jp.locations") + f""",
    scoped_postings AS (
        SELECT * FROM target_postings tp
        WHERE LOWER(tp.country) IN ({placeholders})
           OR EXISTS (SELECT 1 FROM jsonb_to_recordset(tp.locations) AS jl(location text, country text) WHERE LOWER(jl.country) IN ({placeholders}))
    )
    """
        scope = "scoped_postings"
        params: List[Any] = countries * 2
    else:
        cte = get_target_postings_cte()
        scope = "target_postings"
        params = []
    query = f"""
    {cte}
    SELECT
        (SELECT COUNT(*) FROM {scope}) AS total_postings,
        (SELECT COUNT(DISTINCT company_id) FROM {scope}) AS total_companies,
        (SELECT COUNT(DISTINCT location_id) FROM {scope} WHERE location_id IS NOT NULL) AS total_locations,
        (SELECT COUNT(DISTINCT jps.skill_id)
         FROM job_posting_skills jps
         JOIN {scope} tp ON jps.job_posting_id = tp.id) AS total_skills,
        (SELECT COUNT(*) FROM {scope} WHERE posted_at IS NOT NULL AND posted_at >= NOW() - INTERVAL '{RECENTLY_POSTED_DAYS} days' AND posted_at <= NOW() + INTERVAL '1 hour') AS recently_posted_postings,
        COALESCE(
            (SELECT MAX(completed_at) FROM sync_runs WHERE status = 'success'),
            (SELECT MAX(last_seen_at) FROM job_postings WHERE is_active = TRUE),
            (SELECT MAX(updated_at) FROM job_postings)
        ) AS last_refreshed_at;
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(query, params or None)
            row = cur.fetchone()
            last_refreshed = None
            if row and len(row) > 5 and row[5] is not None:
                if isinstance(row[5], datetime):
                    last_refreshed = row[5]
                elif isinstance(row[5], str):
                    try:
                        last_refreshed = datetime.fromisoformat(row[5])
                    except Exception:
                        pass
            return {
                "total_postings": row[0] if row else 0,
                "total_companies": row[1] if row else 0,
                "total_locations": row[2] if row else 0,
                "total_skills": row[3] if row else 0,
                "recently_posted_postings": int(row[4]) if row and len(row) > 4 and row[4] is not None else 0,
                "last_refreshed_at": last_refreshed,
            }
    except psycopg2.Error as err:
        logger.error("Database query failed in /api/stats/overview: %s", err)
        raise HTTPException(status_code=500, detail="Database query error.")
    except Exception as err:
        logger.error("Unexpected error in /api/stats/overview: %s", err)
        raise HTTPException(status_code=500, detail="Internal server error.")


@app.get("/api/stats/countries", response_model=List[CountryStats])
def get_country_stats():
    """
    Returns geographic distribution of job postings ranked by count descending.
    Operates on the identical deduplicated population as /api/jobs and /api/stats/overview.
    """
    cte = get_target_postings_cte()
    query = f"""
    {cte},
    known_country_postings AS (
        SELECT DISTINCT tp.id, loc.country
        FROM target_postings tp
        JOIN job_postings jp ON jp.id = tp.id
        CROSS JOIN LATERAL jsonb_to_recordset(
            CASE WHEN jsonb_array_length(jp.locations) > 0 THEN jp.locations
                 ELSE jsonb_build_array(jsonb_build_object('country', tp.country)) END
        ) AS loc(country text)
        WHERE loc.country IN ('United States', 'Canada')
    )
    SELECT
        kcp.country,
        COUNT(kcp.id) AS postings,
        ROUND((COUNT(kcp.id)::numeric / NULLIF((SELECT COUNT(*) FROM known_country_postings), 0) * 100), 1) AS share_pct
    FROM known_country_postings kcp
    GROUP BY kcp.country
    ORDER BY postings DESC, LOWER(kcp.country) ASC;
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            return [
                {
                    "country": row[0],
                    "postings": row[1],
                    "share_pct": float(row[2]) if row[2] is not None else 0.0,
                }
                for row in rows
            ]
    except psycopg2.Error as err:
        logger.error("Database query failed in /api/stats/countries: %s", err)
        raise HTTPException(status_code=500, detail="Database query error.")
    except Exception as err:
        logger.error("Unexpected error in /api/stats/countries: %s", err)
        raise HTTPException(status_code=500, detail="Internal server error.")


@app.get("/api/stats/skills", response_model=List[SkillStats])
def get_skill_stats():
    """
    Returns ranked skills by posting mentions and frequency percentage.
    Operates on the identical deduplicated population as /api/jobs and /api/stats/overview.
    """
    cte = get_target_postings_cte()
    query = f"""
    {cte}
    SELECT
        ROW_NUMBER() OVER (ORDER BY COUNT(jps.job_posting_id) DESC, LOWER(s.name) ASC) AS rank,
        s.name AS skill,
        COUNT(jps.job_posting_id) AS mentions,
        ROUND((COUNT(jps.job_posting_id)::numeric / NULLIF((SELECT COUNT(*) FROM target_postings), 0) * 100), 1) AS frequency_pct
    FROM skills s
    JOIN job_posting_skills jps ON s.id = jps.skill_id
    JOIN target_postings tp ON jps.job_posting_id = tp.id
    GROUP BY s.name
    ORDER BY mentions DESC, LOWER(s.name) ASC;
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            return [
                {
                    "rank": int(row[0]),
                    "skill": row[1],
                    "mentions": int(row[2]),
                    "frequency_pct": float(row[3]) if row[3] is not None else 0.0,
                }
                for row in rows
            ]
    except psycopg2.Error as err:
        logger.error("Database query failed in /api/stats/skills: %s", err)
        raise HTTPException(status_code=500, detail="Database query error.")
    except Exception as err:
        logger.error("Unexpected error in /api/stats/skills: %s", err)
        raise HTTPException(status_code=500, detail="Internal server error.")


@app.get("/api/stats/roles", response_model=List[BreakdownItem])
def get_role_stats():
    """
    Returns breakdown of active SWE postings by role type.
    Operates on the identical deduplicated population as /api/jobs and /api/stats/overview.
    """
    cte = get_target_postings_cte()
    query = f"""
    {cte},
    grouped AS (
        SELECT
            COALESCE(NULLIF(TRIM(tp.role_type), ''), 'unspecified') AS role_type,
            COUNT(tp.id) AS count
        FROM target_postings tp
        GROUP BY COALESCE(NULLIF(TRIM(tp.role_type), ''), 'unspecified')
    )
    SELECT
        g.role_type,
        g.count,
        ROUND((g.count::numeric / NULLIF((SELECT COUNT(*) FROM target_postings), 0) * 100), 1) AS share_pct
    FROM grouped g
    ORDER BY g.count DESC, g.role_type ASC;
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            return [
                {
                    "category": row[0],
                    "count": int(row[1]),
                    "share_pct": float(row[2]) if row[2] is not None else 0.0,
                }
                for row in rows
            ]
    except psycopg2.Error as err:
        logger.error("Database query failed in /api/stats/roles: %s", err)
        raise HTTPException(status_code=500, detail="Database query error.")
    except Exception as err:
        logger.error("Unexpected error in /api/stats/roles: %s", err)
        raise HTTPException(status_code=500, detail="Internal server error.")


@app.get("/api/stats/workplace", response_model=List[BreakdownItem])
def get_workplace_stats():
    """
    Returns breakdown of active SWE postings by workplace type.
    Operates on the identical deduplicated population as /api/jobs and /api/stats/overview.
    """
    cte = get_target_postings_cte()
    query = f"""
    {cte},
    grouped AS (
        SELECT
            COALESCE(NULLIF(TRIM(tp.workplace_type), ''), 'unspecified') AS workplace_type,
            COUNT(tp.id) AS count
        FROM target_postings tp
        GROUP BY COALESCE(NULLIF(TRIM(tp.workplace_type), ''), 'unspecified')
    )
    SELECT
        g.workplace_type,
        g.count,
        ROUND((g.count::numeric / NULLIF((SELECT COUNT(*) FROM target_postings), 0) * 100), 1) AS share_pct
    FROM grouped g
    ORDER BY g.count DESC, g.workplace_type ASC;
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            return [
                {
                    "category": row[0],
                    "count": int(row[1]),
                    "share_pct": float(row[2]) if row[2] is not None else 0.0,
                }
                for row in rows
            ]
    except psycopg2.Error as err:
        logger.error("Database query failed in /api/stats/workplace: %s", err)
        raise HTTPException(status_code=500, detail="Database query error.")
    except Exception as err:
        logger.error("Unexpected error in /api/stats/workplace: %s", err)
        raise HTTPException(status_code=500, detail="Internal server error.")


@app.get("/api/stats/companies", response_model=List[BreakdownItem])
def get_company_stats():
    """
    Returns top 10 hiring companies by active SWE postings.
    Operates on the identical deduplicated population as /api/jobs and /api/stats/overview.
    """
    cte = get_target_postings_cte()
    query = f"""
    {cte}
    SELECT
        c.name AS company,
        COUNT(tp.id) AS count,
        ROUND((COUNT(tp.id)::numeric / NULLIF((SELECT COUNT(*) FROM target_postings), 0) * 100), 1) AS share_pct
    FROM target_postings tp
    JOIN companies c ON tp.company_id = c.id
    GROUP BY c.name
    ORDER BY count DESC, LOWER(c.name) ASC
    LIMIT 10;
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            return [
                {
                    "category": row[0],
                    "count": int(row[1]),
                    "share_pct": float(row[2]) if row[2] is not None else 0.0,
                }
                for row in rows
            ]
    except psycopg2.Error as err:
        logger.error("Database query failed in /api/stats/companies: %s", err)
        raise HTTPException(status_code=500, detail="Database query error.")
    except Exception as err:
        logger.error("Unexpected error in /api/stats/companies: %s", err)
        raise HTTPException(status_code=500, detail="Internal server error.")


# --- Job Explorer Endpoints ---

VALID_WORKPLACE_TYPES = {"remote", "hybrid", "on_site", "onsite", "unspecified"}
# "recent" (default, alias "45d") is the public 45-day visibility window; "all" is the unbounded
# internal/debug view of every source-active job; the others narrow the public window further.
VALID_FRESHNESS_FILTERS = {"recent", "all", "today", "week", "14d", "30d"}
FRESHNESS_WINDOW_DAYS = {"week": 7, "14d": 14}   # "30d" IS the default public window (see below)
ROLE_NORMALIZATION_MAP = {
    "fulltime": "full_time",
    "full_time": "full_time",
    "intern": "internship",
    "internship": "internship",
    "coop": "co_op",
    "co_op": "co_op",
    "newgrad": "new_grad",
    "new_grad": "new_grad",
    "entrylevel": "entry_level",
    "entry_level": "entry_level",
    "entry": "entry_level",
}

# Search words that mean an early-career role type: matched on role_type first, title text second.
EARLY_CAREER_SEARCH_TOKENS = {
    "coop": ("co_op", r"\yco[ -]?ops?\y"),
    "newgrad": ("new_grad", r"\ynew[ -]?grad(?:uate)?s?\y"),
    "entrylevel": ("entry_level", r"\yentry[ -]?level\y"),
}

VALID_SORTS = "^(recommended|newest|oldest|company|title)$"

CANADIAN_METROS: Dict[str, str] = {
    "toronto": r"\y(?:toronto|gta|greater toronto area|mississauga|brampton|markham|vaughan|richmond hill|oakville|burlington|milton|pickering|ajax|whitby|oshawa|newmarket|aurora|king|halton hills|caledon|scarborough|north york|etobicoke|(?<!new\s)york|east york)\y",
    "gta": r"\y(?:toronto|gta|greater toronto area|mississauga|brampton|markham|vaughan|richmond hill|oakville|burlington|milton|pickering|ajax|whitby|oshawa|newmarket|aurora|king|halton hills|caledon|scarborough|north york|etobicoke|(?<!new\s)york|east york)\y",
    "vancouver": r"\y(?:vancouver|greater vancouver|metro vancouver|burnaby|richmond|surrey|coquitlam|north vancouver|west vancouver|delta|langley|new westminster|port coquitlam|port moody)\y",
    "montreal": r"\y(?:montreal|montréal|greater montreal|grand montréal|laval|longueuil|brossard|kirkland|dorval|pointe claire|pointe-claire|westmount|saint laurent|saint-laurent|boucherville|terrebonne)\y",
    "ottawa": r"\y(?:ottawa|gatineau|national capital region|kanata|nepean|gloucester|orleans)\y",
    "waterloo": r"\y(?:waterloo|kitchener|kitchener-waterloo|kw|cambridge|guelph)\y",
    "calgary": r"\y(?:calgary|greater calgary|airdrie|cochrane|okotoks|chestermere)\y",
    "edmonton": r"\y(?:edmonton|greater edmonton|st albert|st\. albert|sherwood park|spruce grove|leduc)\y",
}

US_METROS: Dict[str, str] = {
    "san francisco, ca": r"\y(?:san francisco|sf|south san francisco)\y",
    "san francisco": r"\y(?:san francisco|sf|south san francisco)\y",
    "sf": r"\y(?:san francisco|sf)\y",
    "new york, ny": r"\y(?:new york|nyc|new york city|manhattan|brooklyn)\y",
    "new york": r"\y(?:new york|nyc|new york city|manhattan|brooklyn)\y",
    "nyc": r"\y(?:new york|nyc|new york city|manhattan|brooklyn)\y",
    "seattle, wa": r"\y(?:seattle|bellevue|redmond)\y",
    "seattle": r"\y(?:seattle|bellevue|redmond)\y",
}

POSITIVE_SPONSORSHIP_REGEX = (
    r"\y(?:"
    r"visa sponsorship (?:is )?(?:available|provided|offered|supported)|"
    r"(?:will|can|able to)\s+sponsor (?:(?:work |employment )?visas?|candidates?|foreign nationals?|work authorization)|"
    r"offers? (?:visa |work )?sponsorship|"
    r"eligible for (?:visa |work )?sponsorship|"
    r"(?:h-?1b|tn|work permit) sponsorship (?:is )?(?:available|provided|offered)"
    r")\y"
)

NEGATION_SPONSORSHIP_REGEX = (
    r"\y(?:"
    r"(?:do(?:es)?\s+not|not|cannot|can\s+not|won'?t|will\s+not|unable\s+to|not\s+able\s+to)\s+(?:offer|provide|support|give|sponsor)\s+(?:[a-z0-9_-]+\s+){0,3}(?:visas?|sponsorship)|"
    r"(?:no|without|not\s+requiring)\s+(?:[a-z0-9_-]+\s+){0,2}(?:visa\s+)?sponsorship|"
    r"not\s+(?:currently\s+)?offering\s+(?:visa\s+)?sponsorship|"
    r"not\s+eligible\s+for\s+(?:visa\s+)?sponsorship"
    r")\y"
)

GENERAL_NOT_REQUIRED_REGEX = (
    r"\y(?:"
    r"no\s+(?:visa\s+)?sponsorship\s+(?:available|provided|offered|required)|"
    r"(?:do(?:es)?\s+not|not|cannot|can\s+not|won'?t|will\s+not|unable\s+to|not\s+able\s+to)\s+(?:offer|provide|support|give|sponsor)\s+(?:[a-z0-9_-]+\s+){0,3}(?:visas?|sponsorship)|"
    r"not\s+(?:currently\s+)?offering\s+(?:visa\s+)?sponsorship|"
    r"not\s+eligible\s+for\s+(?:visa\s+)?sponsorship|"
    r"without\s+(?:requiring\s+)?(?:employer\s+|company\s+)?(?:visa\s+)?sponsorship"
    r")\y"
)

CANADA_NOT_REQUIRED_REGEX = (
    r"\y(?:"
    r"(?:authorized|authorised|entitled)\s+to\s+work\s+in\s+canada\s+without\s+(?:requiring\s+)?(?:employer\s+|company\s+)?(?:visa\s+)?sponsorship|"
    r"canadian\s+citizen(?:ship)?(?:\s+or\s+permanent\s+residen(?:t|cy))?\s+required|"
    r"requires\s+canadian\s+citizenship"
    r")\y"
)

US_NOT_REQUIRED_REGEX = (
    r"(?:\y(?:authorized|authorised|entitled)\s+to\s+work\s+in\s+(?:the\s+)?(?:u\.?s\.?|united\s+states)\s+without\s+(?:requiring\s+)?(?:employer\s+|company\s+)?(?:visa\s+)?sponsorship|"
    r"(?:\y|(?<=\s))(?:u\.?s\.?|us)\s+citizen(?:ship)?(?:\s+or\s+permanent\s+residen(?:t|cy))?\s+required|"
    r"\yrequires\s+(?:u\.?s\.?|us)\s+citizenship)"
)


def resolve_metro_regex(term: str) -> Optional[str]:
    """Returns regex pattern if term refers to a recognized Canadian metro region."""
    cleaned = term.strip().lower()
    cleaned = re.sub(r"\s*\([^)]*\)", "", cleaned).strip()
    return CANADIAN_METROS.get(cleaned)


def resolve_us_metro_regex(term: str) -> Optional[str]:
    """Returns regex pattern if term refers to a recognized US metro region."""
    cleaned = term.strip().lower()
    return US_METROS.get(cleaned)


_CANADA_LOCATION_SQL = (
    "(l.country = 'Canada' OR EXISTS (SELECT 1 FROM jsonb_to_recordset(jp.locations) "
    "AS jl(location text, country text) WHERE jl.country = 'Canada'))"
)
_EARLY_CAREER_SQL = "jp.role_type IN (" + ", ".join(f"'{r}'" for r in EARLY_CAREER_ROLE_TYPES) + ")"
def _posted_within(days: int) -> str:
    return f"(jp.posted_at IS NOT NULL AND jp.posted_at >= NOW() - INTERVAL '{days} days')"


# Freshness-weighted, Canada-first buckets (age only ranks, it never hides a job):
# 1 Canada <=7d, 2 Canada <=30d, 3 Canada early-career <=60d, 4 other Canada,
# 5 remote, 6 US early-career, 7 the rest.
RECOMMENDED_RANK_SQL = f"""CASE
        WHEN {_CANADA_LOCATION_SQL} AND {_posted_within(7)} THEN 1
        WHEN {_CANADA_LOCATION_SQL} AND {_posted_within(30)} THEN 2
        WHEN {_CANADA_LOCATION_SQL} AND {_EARLY_CAREER_SQL} AND {_posted_within(60)} THEN 3
        WHEN {_CANADA_LOCATION_SQL} THEN 4
        WHEN jp.workplace_type = 'remote' OR l.location ~* '\\yremote\\y' THEN 5
        WHEN {_EARLY_CAREER_SQL} THEN 6
        ELSE 7
    END"""


def format_academic_term(season: Optional[str], year: Optional[int]) -> Optional[str]:
    return f"{season.title()} {year}" if season in SUPPORTED_TERM_SEASONS and year else None


# Curated Location dropdown entries (metro labels). Which of them are *offered* is decided by the data: see
# get_job_filter_options, which only lists a metro that matches at least one job in the public results population.
LOCATION_OPTIONS = (
    "Toronto (GTA)", "Vancouver", "Montreal", "Ottawa", "Waterloo", "Calgary", "Edmonton",
    "San Francisco, CA", "New York, NY", "Seattle, WA",
)


def location_filter_clause(loc_item: str) -> Tuple[str, List[str]]:
    """SQL + params matching one location filter value against `l` (primary location) and `jp.locations`.

    The single definition of what a location filter means, shared by the job list and by the filter options so an
    option can never promise results the list would not return.
    """
    metro_pattern = resolve_metro_regex(loc_item)
    us_pattern = resolve_us_metro_regex(loc_item)
    if metro_pattern:
        return (
            "((l.country = 'Canada' AND l.location ~* %s) OR EXISTS (SELECT 1 FROM jsonb_to_recordset(jp.locations) AS jl(location text, country text) WHERE jl.country = 'Canada' AND jl.location ~* %s))",
            [metro_pattern, metro_pattern],
        )
    if us_pattern:
        return (
            "((l.country = 'United States' AND l.location ~* %s) OR EXISTS (SELECT 1 FROM jsonb_to_recordset(jp.locations) AS jl(location text, country text) WHERE jl.country = 'United States' AND jl.location ~* %s))",
            [us_pattern, us_pattern],
        )
    escaped_loc = f"%{escape_like_wildcard(loc_item)}%"
    return (
        "(l.location ILIKE %s ESCAPE '\\' OR EXISTS (SELECT 1 FROM jsonb_to_recordset(jp.locations) AS jl(location text, country text) WHERE jl.location ILIKE %s ESCAPE '\\'))",
        [escaped_loc, escaped_loc],
    )


MAX_OFFSET = 100_000  # far beyond any real page; keeps absurd values from overflowing PostgreSQL integers


def reject_nul(*values: Any) -> None:
    """PostgreSQL text cannot contain NUL; reject such input up front with a client error, not a 500."""
    for value in values:
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            if isinstance(item, str) and "\x00" in item:
                raise HTTPException(status_code=400, detail="Invalid characters in request parameters.")


def escape_like_wildcard(text: str) -> str:
    """
    Escapes special SQL LIKE wildcard characters (% and _) using backslash as the escape character.
    Also escapes literal backslashes so user-entered backslashes are treated literally.
    """
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def canonicalize_countries(country: Optional[Union[str, List[str]]]) -> List[str]:
    """Validated, de-duplicated canonical country names ("Canada", "United States") from a filter value."""
    cleaned: List[str] = []
    for c in parse_multi_values(country):
        c_norm = c.strip().replace("_", " ").lower()
        if c_norm in ("united states", "us", "usa"):
            canonical = "United States"
        elif c_norm in ("canada", "ca"):
            canonical = "Canada"
        else:
            raise HTTPException(status_code=400, detail=f"Invalid country '{c}'. Must be one of: Canada, United States.")
        if canonical not in cleaned:
            cleaned.append(canonical)
    return cleaned


def parse_multi_values(val: Optional[Union[str, List[str]]]) -> List[str]:
    """
    Parses single strings, comma-separated strings, or lists of strings into a distinct list of non-empty items.
    """
    if not val:
        return []
    items = [val] if isinstance(val, str) else val
    res: List[str] = []
    for item in items:
        if isinstance(item, str):
            for part in item.split(","):
                cleaned = part.strip()
                if cleaned and cleaned not in res:
                    res.append(cleaned)
    return res


def parse_locations(val: Optional[Union[str, List[str]]]) -> List[str]:
    """
    Parses location parameters preserving commas within location names.
    Supports repeated location parameters (e.g. ?location=San Francisco, CA&location=New York, NY)
    or lists of strings.
    """
    if not val:
        return []
    items = [val] if isinstance(val, str) else val
    res: List[str] = []
    for item in items:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned and cleaned not in res:
                res.append(cleaned)
    return res


@app.get("/api/jobs", response_model=JobListResponse)
def get_jobs(
    limit: int = Query(default=25, ge=1, le=100, description="Page limit (1-100)"),
    offset: int = Query(default=0, ge=0, le=MAX_OFFSET, description=f"Page offset (0-{MAX_OFFSET})"),
    search: Optional[str] = Query(default=None, description="Case-insensitive title, company, or skill search"),
    q: Optional[str] = Query(default=None, description="Case-insensitive title, company, or skill search (canonical alias)"),
    country: Optional[List[str]] = Query(default=None, description="Country filter (single, comma-separated, or repeated)"),
    location: Optional[List[str]] = Query(default=None, description="Regional or specific location filter (single, comma-separated, or repeated)"),
    company: Optional[str] = Query(default=None, description="Exact case-insensitive company match"),
    skill: Optional[str] = Query(default=None, description="Exact case-insensitive skill match"),
    workplace_type: Optional[List[str]] = Query(default=None, description="Workplace type (single, comma-separated, or repeated)"),
    role_type: Optional[List[str]] = Query(default=None, description="Role type (single, comma-separated, or repeated)"),
    experience_level: Optional[List[str]] = Query(default=None, description="Experience level: internship, entry, mid, senior (single, comma-separated, or repeated)"),
    min_compensation: Optional[int] = Query(default=None, ge=0, description="Minimum annualized compensation"),
    compensation_currency: Optional[str] = Query(default=None, description="Currency filter for compensation: CAD, USD, etc."),
    sponsorship: Optional[str] = Query(default="all", description="Sponsorship requirement: all, available, not_required"),
    term: Optional[List[str]] = Query(default=None, description="Academic term season: winter, summer, fall (single, comma-separated, or repeated)"),
    freshness: Optional[str] = Query(default="recent", description="Posted-date window: recent/30d (the default 30-day public window), today, week, 14d, or all (unbounded, internal/debug)"),
    sort: str = Query(default="recommended", pattern=VALID_SORTS, description="recommended (Canada-first, default), newest, oldest, company, title"),
):
    """
    Returns paginated active real SWE jobs matching optional filter criteria.
    By default only jobs inside the 30-day public visibility window are listed (see
    get_public_visibility_sql_predicate); older source-active jobs stay stored but are hidden.
    freshness=30d is an alias of the default; all disables the window (internal/debug); today/week/14d narrow it.
    """
    reject_nul(
        search, q, country, location, company, skill, workplace_type, role_type,
        experience_level, sponsorship, compensation_currency, term, freshness
    )
    cleaned_freshness = "recent"
    if freshness:
        cleaned_freshness = freshness.strip().lower()
        if cleaned_freshness not in VALID_FRESHNESS_FILTERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid freshness. Must be one of: {', '.join(sorted(VALID_FRESHNESS_FILTERS))}.",
            )

    if cleaned_freshness == "today":
        freshness_sql = get_today_freshness_sql_predicate(table_alias="jp")
    elif cleaned_freshness in FRESHNESS_WINDOW_DAYS:
        freshness_sql = get_week_freshness_sql_predicate(table_alias="jp", freshness_days=FRESHNESS_WINDOW_DAYS[cleaned_freshness])
    elif cleaned_freshness == "all":
        freshness_sql = None  # unbounded: every source-active job, however old
    else:
        freshness_sql = get_public_visibility_sql_predicate(table_alias="jp")

    where_clauses = [
        "jp.is_active = TRUE",
        f"jp.source_name != 'sample' AND jp.source_name IN {official_sources_sql()} AND jp.is_eligible_role = TRUE",
        get_user_facing_geography_sql_predicate(location_alias="l"),
        get_deduplication_sql_predicate(table_alias="jp"),
    ]
    if freshness_sql:
        where_clauses.append(freshness_sql)
    params: List[Any] = []

    effective_search = search or q
    search_terms = parse_search_query(effective_search or "")
    search_clause_start = len(where_clauses)
    if search_terms:
        # Case, accents, hyphens, repeated whitespace and surrounding punctuation are normalized once (api/search_text.py) and the
        # stored text is folded the same way below, so list results and counts always agree. Quotes make a phrase.
        search_tokens = [term.text for term in search_terms]
        phrase_tokens = {term.text for term in search_terms if term.phrase}
        for token in search_tokens:
            token_lower = token.lower()
            escaped_token = escape_like_wildcard(token)
            like_pattern = f"%{escaped_token}%"
            is_phrase = token in phrase_tokens

            synonyms = {
                "swe": r"\y(?:swe|software engineer(?:ing)?|software developer)\y",
                "sre": r"\y(?:sre|site reliability)\y",
                "ml": r"\y(?:ml|machine learning)\y",
                "ai": r"\y(?:ai|artificial intelligence)\y",
                "k8s": r"\y(?:k8s|kubernetes)\y",
                "kubernetes": r"\y(?:k8s|kubernetes)\y",
                "postgres": r"\y(?:postgres|postgresql)\y",
                "postgresql": r"\y(?:postgres|postgresql)\y",
                "js": r"\y(?:js|javascript)\y",
                "ts": r"\y(?:ts|typescript)\y",
                "backend": r"\yback[ -]?end\y",
                "frontend": r"\yfront[ -]?end\y",
                "fullstack": r"\yfull[ -]?stack\y",
            }
            synonyms["javascript"] = synonyms["js"]
            synonyms["typescript"] = synonyms["ts"]
            if not is_phrase and token_lower in synonyms:
                pattern = synonyms[token_lower]
                where_clauses.append("""(jp.title ~* %s OR c.name ~* %s OR regexp_replace(COALESCE(jp.description,''), '<[^>]*>', ' ', 'g') ~* %s OR EXISTS (
                    SELECT 1 FROM job_posting_skills jps_s JOIN skills s_s ON jps_s.skill_id = s_s.id
                    WHERE jps_s.job_posting_id = jp.id AND s_s.name ~* %s))""")
                params.extend([pattern, pattern, pattern, pattern])
            elif not is_phrase and token_lower in EARLY_CAREER_SEARCH_TOKENS:
                role_value, title_pattern = EARLY_CAREER_SEARCH_TOKENS[token_lower]
                where_clauses.append("(jp.role_type = %s OR jp.title ~* %s)")
                params.extend([role_value, title_pattern])
            elif not is_phrase and token_lower in ("intern", "interns", "internship", "internships"):
                # Word-aware matching for internship roles:
                # Matches explicit internship titles, role_type = 'internship', or matching companies/skills,
                # while avoiding false positives on 'Internal' / 'Internals' / 'International'
                token_clause = """(
                    (jp.title ~* %s OR jp.role_type = 'internship')
                    OR (c.name ILIKE %s ESCAPE '\\' AND c.name NOT ILIKE %s ESCAPE '\\')
                    OR l.location ILIKE %s ESCAPE '\\'
                    OR jp.workplace_type ILIKE %s ESCAPE '\\'
                    OR EXISTS (
                        SELECT 1 FROM job_posting_skills jps_s
                        JOIN skills s_s ON jps_s.skill_id = s_s.id
                        WHERE jps_s.job_posting_id = jp.id AND s_s.name ILIKE %s ESCAPE '\\'
                    )
                )"""
                where_clauses.append(token_clause)
                internal_pattern = f"%{escape_like_wildcard('internal')}%"
                params.extend([r"\yintern(s|ship|ships)?\y", like_pattern, internal_pattern, like_pattern, like_pattern, like_pattern])
            elif not is_phrase and token_lower in ("go", "golang"):
                # Word-aware matching for Go / Golang technical roles:
                # Matches Go / Golang as a discrete programming language in titles or skills,
                # while avoiding false positives on 'Government', 'ongoing', 'foregoing', 'go-to-market', etc.
                token_clause = """(
                    (jp.title ~* %s AND jp.title !~* %s)
                    OR c.name ~* %s
                    OR l.location ~* %s
                    OR jp.workplace_type ILIKE %s ESCAPE '\\'
                    OR EXISTS (
                        SELECT 1 FROM job_posting_skills jps_s
                        JOIN skills s_s ON jps_s.skill_id = s_s.id
                        WHERE jps_s.job_posting_id = jp.id AND LOWER(s_s.name) IN ('go', 'golang')
                    )
                )"""
                where_clauses.append(token_clause)
                params.extend([
                    r"\y(golang|go)\y",
                    r"\ygo[\s\-]to[\s\-]market\y|\ygo[\s\-]live\y",
                    r"\y(golang|go)\y",
                    r"\y(golang|go)\y",
                    like_pattern,
                ])
            elif not is_phrase and len(token) <= 2 and token.isalnum():
                # Short ambiguous token (1-2 chars, e.g. "C", "R", "AI", "ML", "CA"):
                # Avoid catastrophic substring ILIKE explosion (%c% or %r% matching the entire catalog).
                # Use word-boundary regex for title, company, location, and workplace, and exact match for skills.
                token_regex = rf"\y{re.escape(token)}\y"
                token_clause = """(
                    jp.title ~* %s
                    OR c.name ~* %s
                    OR l.location ~* %s
                    OR jp.workplace_type ~* %s
                    OR EXISTS (
                        SELECT 1 FROM job_posting_skills jps_s
                        JOIN skills s_s ON jps_s.skill_id = s_s.id
                        WHERE jps_s.job_posting_id = jp.id AND LOWER(s_s.name) = LOWER(%s)
                    )
                )"""
                where_clauses.append(token_clause)
                params.extend([token_regex, token_regex, token_regex, token_regex, token])
            elif token_lower in CANONICAL_SKILL_NAMES:
                # Technical tokens are whole words: Java is not JavaScript, Rust is not trust,
                # and C# keeps its punctuation. Descriptions are searched even before re-ingestion.
                canonical = CANONICAL_SKILL_NAMES[token_lower]
                aliases = sorted(key for key, value in CANONICAL_SKILL_NAMES.items() if value == canonical)
                literal = re.escape(aliases[0]) if len(aliases) == 1 else "(?:" + "|".join(re.escape(value) for value in aliases) + ")"
                pattern = rf"(?<![[:alnum:]_+#]){literal}(?![[:alnum:]_+#])"
                where_clauses.append("""(jp.title ~* %s OR c.name ~* %s OR l.location ~* %s
                    OR regexp_replace(COALESCE(jp.description,''), '<[^>]*>', ' ', 'g') ~* %s OR EXISTS (
                    SELECT 1 FROM job_posting_skills jps_s JOIN skills s_s ON jps_s.skill_id=s_s.id
                    WHERE jps_s.job_posting_id=jp.id AND s_s.name ~* %s))""")
                params.extend([pattern] * 5)
            else:
                token_clause = """(
                    jp.title ILIKE %s ESCAPE '\\'
                    OR c.name ILIKE %s ESCAPE '\\'
                    OR l.location ILIKE %s ESCAPE '\\'
                    OR jp.workplace_type ILIKE %s ESCAPE '\\'
                    OR jp.search_document @@ plainto_tsquery('simple', %s)
                    OR EXISTS (
                        SELECT 1 FROM job_posting_skills jps_s
                        JOIN skills s_s ON jps_s.skill_id = s_s.id
                        WHERE jps_s.job_posting_id = jp.id AND s_s.name ILIKE %s ESCAPE '\\'
                    )
                )"""
                if is_phrase:
                    token_clause = token_clause.replace("plainto_tsquery", "phraseto_tsquery")
                where_clauses.append(token_clause)
                params.extend([like_pattern, like_pattern, like_pattern, like_pattern, token, like_pattern])

    for index in range(search_clause_start, len(where_clauses)):
        where_clauses[index] = fold_search_clause(where_clauses[index])

    cleaned_countries = canonicalize_countries(country)
    if cleaned_countries:
        if len(cleaned_countries) == 1:
            where_clauses.append("(LOWER(l.country) = LOWER(%s) OR EXISTS (SELECT 1 FROM jsonb_to_recordset(jp.locations) AS jl(location text, country text) WHERE LOWER(jl.country) = LOWER(%s)))")
            params.extend([cleaned_countries[0], cleaned_countries[0]])
        else:
            placeholders = ", ".join(["LOWER(%s)"] * len(cleaned_countries))
            where_clauses.append(f"(LOWER(l.country) IN ({placeholders}) OR EXISTS (SELECT 1 FROM jsonb_to_recordset(jp.locations) AS jl(location text, country text) WHERE LOWER(jl.country) IN ({placeholders})))")
            params.extend(cleaned_countries * 2)

    if company:
        cleaned_company = company.strip()
        if cleaned_company:
            where_clauses.append("LOWER(c.name) = LOWER(%s)")
            params.append(cleaned_company)

    if skill:
        cleaned_skill = skill.strip()
        if cleaned_skill:
            where_clauses.append("""
                EXISTS (
                    SELECT 1 FROM job_posting_skills jps_f
                    JOIN skills s_f ON jps_f.skill_id = s_f.id
                    WHERE jps_f.job_posting_id = jp.id AND LOWER(s_f.name) = LOWER(%s)
                )
            """)
            params.append(cleaned_skill)

    parsed_wts = parse_multi_values(workplace_type)
    if parsed_wts:
        cleaned_wts = []
        for w in parsed_wts:
            wt_raw = w.lower().strip().replace("-", "_")
            if wt_raw in ("onsite", "on_site"):
                wt = "on_site"
            elif wt_raw in ("remote", "hybrid", "unspecified"):
                wt = wt_raw
            else:
                raise HTTPException(status_code=400, detail=f"Invalid workplace_type '{w}'. Must be one of: remote, hybrid, on_site, unspecified.")
            if wt not in cleaned_wts:
                cleaned_wts.append(wt)
        if cleaned_wts:
            # Map on_site to both on_site and onsite for database compatibility
            wt_db_values = []
            for wt in cleaned_wts:
                if wt == "on_site":
                    wt_db_values.extend(["on_site", "onsite"])
                else:
                    wt_db_values.append(wt)
            wt_db_values = list(dict.fromkeys(wt_db_values))
            if len(wt_db_values) == 1:
                where_clauses.append("jp.workplace_type = %s")
                params.append(wt_db_values[0])
            else:
                placeholders = ", ".join(["%s"] * len(wt_db_values))
                where_clauses.append(f"jp.workplace_type IN ({placeholders})")
                params.extend(wt_db_values)

    parsed_roles = parse_multi_values(role_type)
    if parsed_roles:
        cleaned_roles = []
        for r in parsed_roles:
            rt_raw = r.lower().strip().replace("-", "_")
            rt = ROLE_NORMALIZATION_MAP.get(rt_raw)
            if not rt or rt not in VALID_ROLE_TYPES:
                raise HTTPException(status_code=400, detail=f"Invalid role_type '{r}'. Must be one of: internship, co_op, new_grad, entry_level, full_time.")
            if rt not in cleaned_roles:
                cleaned_roles.append(rt)
        if cleaned_roles:
            if len(cleaned_roles) == 1:
                where_clauses.append("jp.role_type = %s")
                params.append(cleaned_roles[0])
            else:
                placeholders = ", ".join(["%s"] * len(cleaned_roles))
                where_clauses.append(f"jp.role_type IN ({placeholders})")
                params.extend(cleaned_roles)

    parsed_terms = []
    for raw_term in parse_multi_values(term):
        season = {"autumn": "fall"}.get(raw_term.strip().lower(), raw_term.strip().lower())
        if season not in SUPPORTED_TERM_SEASONS:
            raise HTTPException(status_code=400, detail=f"Invalid term '{raw_term}'. Must be one of: winter, summer, fall.")
        parsed_terms.append(season)
    if parsed_terms:
        parsed_terms = list(dict.fromkeys(parsed_terms))
        placeholders = ", ".join(["%s"] * len(parsed_terms))
        where_clauses.append(f"jp.term_season IN ({placeholders})")
        params.extend(parsed_terms)

    parsed_locs = parse_locations(location)
    if parsed_locs:
        loc_clauses = []
        for loc_item in parsed_locs:
            clause_sql, clause_params = location_filter_clause(loc_item)
            loc_clauses.append(clause_sql)
            params.extend(clause_params)
        if loc_clauses:
            where_clauses.append(f"({' OR '.join(loc_clauses)})")

    parsed_exp = parse_multi_values(experience_level)
    if parsed_exp:
        aliases = {"intern": "internship", "co_op": "internship", "coop": "internship", "entry_level": "entry", "new_grad": "entry", "newgrad": "entry", "junior": "entry", "associate": "entry", "sr": "senior", "lead": "senior", "staff": "senior", "principal": "senior", "mid_level": "mid", "intermediate": "mid"}
        levels = [aliases.get(value.lower().strip(), value.lower().strip()) for value in parsed_exp]
        if any(value not in ("internship", "entry", "mid", "senior") for value in levels):
            raise HTTPException(status_code=400, detail="Invalid experience_level. Must be internship, entry, mid or senior.")
        where_clauses.append("jp.experience_level = ANY(%s)")
        params.append(levels)

    if min_compensation is not None and min_compensation > 0:
        # Compensation filtering is currency-explicit: require explicit currency or deduce from single country filter
        if compensation_currency and compensation_currency.strip():
            effective_currency = compensation_currency.upper().strip()
        elif cleaned_countries and len(cleaned_countries) == 1:
            country_norm = cleaned_countries[0].lower()
            if country_norm == "canada":
                effective_currency = "CAD"
            elif country_norm == "united states":
                effective_currency = "USD"
            else:
                raise HTTPException(
                    status_code=400,
                    detail="compensation_currency (e.g. CAD or USD) is required when min_compensation is specified without a supported country filter.",
                )
        else:
            raise HTTPException(
                status_code=400,
                detail="compensation_currency (e.g. CAD or USD) is required when min_compensation is specified.",
            )

        where_clauses.append("EXISTS (SELECT 1 FROM jsonb_to_recordset(jp.pay_ranges) AS pay(currency text, min_annual numeric, max_annual numeric) WHERE pay.max_annual >= %s AND pay.currency = %s)")
        params.extend([min_compensation, effective_currency])

    if sponsorship and sponsorship.strip().lower() not in ("all", ""):
        sp = sponsorship.strip().lower()
        if sp in ("available", "offers_sponsorship", "sponsored"):
            where_clauses.append("(jp.description ~* %s AND jp.description !~* %s)")
            params.extend([POSITIVE_SPONSORSHIP_REGEX, NEGATION_SPONSORSHIP_REGEX])
        elif sp in ("not_required", "no_sponsorship", "citizen_or_pr"):
            if cleaned_countries and len(cleaned_countries) == 1 and cleaned_countries[0].lower() == "canada":
                where_clauses.append("(jp.description ~* %s OR jp.description ~* %s)")
                params.extend([GENERAL_NOT_REQUIRED_REGEX, CANADA_NOT_REQUIRED_REGEX])
            elif cleaned_countries and len(cleaned_countries) == 1 and cleaned_countries[0].lower() == "united states":
                where_clauses.append("(jp.description ~* %s OR jp.description ~* %s)")
                params.extend([GENERAL_NOT_REQUIRED_REGEX, US_NOT_REQUIRED_REGEX])
            else:
                where_clauses.append("(jp.description ~* %s OR jp.description ~* %s OR jp.description ~* %s)")
                params.extend([GENERAL_NOT_REQUIRED_REGEX, CANADA_NOT_REQUIRED_REGEX, US_NOT_REQUIRED_REGEX])
        else:
            raise HTTPException(status_code=400, detail=f"Invalid sponsorship '{sponsorship}'. Must be one of: all, available, not_required.")


    recency = "jp.posted_at DESC NULLS LAST, jp.created_at DESC, jp.id DESC"
    order_sql = {
        "recommended": f"{RECOMMENDED_RANK_SQL} ASC, {recency}",
        "newest": "jp.posted_at DESC NULLS LAST, jp.created_at DESC, jp.id DESC",
        "oldest": "jp.posted_at ASC NULLS LAST, jp.created_at ASC, jp.id ASC",
        "company": "LOWER(c.name) ASC, jp.posted_at DESC NULLS LAST, jp.id DESC",
        "title": "LOWER(jp.title) ASC, jp.posted_at DESC NULLS LAST, jp.id DESC",
    }[sort]
    where_sql = " AND ".join(where_clauses)

    count_query = f"""
    SELECT COUNT(*)
    FROM job_postings jp
    JOIN companies c ON jp.company_id = c.id
    LEFT JOIN locations l ON jp.location_id = l.id
    WHERE {where_sql};
    """

    data_query = f"""
    SELECT
        jp.job_id,
        jp.title,
        c.name AS company,
        COALESCE(l.location, 'Unspecified') AS location,
        COALESCE(l.country, 'Unspecified') AS country,
        jp.workplace_type,
        jp.role_type,
        jp.source_name,
        jp.source_url,
        jp.posted_at,
        jp.created_at,
        COALESCE(ARRAY_AGG(DISTINCT s.name ORDER BY s.name) FILTER (WHERE s.name IS NOT NULL), '{{}}') AS skills,
        c.logo_url,
        c.logo_status,
        jp.company_apply_url,
        jp.linkedin_url,
        jp.simplify_url,
        jp.locations,
        jp.compensation,
        jp.term_season,
        jp.term_year,
        jp.experience_level
    FROM job_postings jp
    JOIN companies c ON jp.company_id = c.id
    LEFT JOIN locations l ON jp.location_id = l.id
    LEFT JOIN job_posting_skills jps ON jp.id = jps.job_posting_id
    LEFT JOIN skills s ON jps.skill_id = s.id
    WHERE {where_sql}
    GROUP BY jp.id, jp.job_id, jp.title, c.name, c.logo_url, c.logo_status, l.location, l.country, jp.workplace_type, jp.role_type, jp.source_name, jp.source_url, jp.posted_at, jp.created_at, jp.company_apply_url, jp.linkedin_url, jp.simplify_url
    ORDER BY {order_sql}
    LIMIT %s OFFSET %s;
    """

    try:
        with get_db_cursor() as cur:
            cur.execute(count_query, params)
            count_row = cur.fetchone()
            total = count_row[0] if count_row else 0

            cur.execute(data_query, params + [limit, offset])
            rows = cur.fetchall()

            jobs = [
                {
                    "locations": row[17] if len(row) > 17 else [],
                    "compensation": row[18] if len(row) > 18 else None,
                    "term_season": row[19] if len(row) > 19 else None,
                    "term_year": row[20] if len(row) > 20 else None,
                    "academic_term": format_academic_term(row[19], row[20]) if len(row) > 20 else None,
                    "experience_level": row[21] if len(row) > 21 else None,
                    "job_id": row[0],
                    "title": row[1],
                    "company": row[2],
                    "company_logo_url": row[12] if len(row) > 12 else None,
                    "company_logo_status": row[13] if len(row) > 13 else None,
                    "location": row[3],
                    "country": row[4],
                    "workplace_type": row[5],
                    "role_type": row[6],
                    "source_name": row[7],
                    "source_url": row[8],
                    "company_apply_url": row[14] if (len(row) > 14 and row[14]) else (row[8] if row[8] and "linkedin.com" not in row[8] and "simplify.jobs" not in row[8] and "indeed.com" not in row[8] else None),
                    "linkedin_url": row[15] if (len(row) > 15 and row[15]) else (row[8] if row[8] and "linkedin.com" in row[8] else None),
                    "simplify_url": row[16] if (len(row) > 16 and row[16]) else (row[8] if row[8] and "simplify.jobs" in row[8] else None),
                    "posted_at": row[9],
                    "posted_at_precision": posted_at_precision(row[7], row[9]),
                    "created_at": row[10],
                    "freshness_status": classify_freshness_status(
                        posted_at=row[9],
                        created_at=row[10],
                        is_active=True,
                    ),
                    "recently_posted": is_job_recently_posted(
                        posted_at=row[9],
                    ),
                    "skills": list(row[11]) if row[11] else [],
                }
                for row in rows
            ]

            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "jobs": jobs,
            }
    except HTTPException:
        raise
    except psycopg2.Error as err:
        logger.error("Database query failed in /api/jobs: %s", err)
        raise HTTPException(status_code=500, detail="Database query error.")
    except Exception as err:
        logger.error("Unexpected error in /api/jobs: %s", err)
        raise HTTPException(status_code=500, detail="Internal server error.")


@app.get("/api/jobs/filters", response_model=JobFilterOptions)
def get_job_filter_options():
    """
    Returns available filter options calculated from active real postings.
    Excludes sample jobs and inactive jobs. Options are deterministically sorted.
    """
    geography_predicate = get_user_facing_geography_sql_predicate(location_alias="l")
    query_countries = f"""
    {get_target_postings_cte()}
    SELECT DISTINCT loc.country
    FROM target_postings tp JOIN job_postings jp ON jp.id = tp.id
    CROSS JOIN LATERAL jsonb_to_recordset(
        CASE WHEN jsonb_array_length(jp.locations) > 0 THEN jp.locations
             ELSE jsonb_build_array(jsonb_build_object('country', tp.country)) END
    ) AS loc(country text)
    WHERE loc.country IN ('United States', 'Canada')
    ORDER BY loc.country;
    """
    query_companies = f"""
    SELECT DISTINCT c.name
    FROM job_postings jp
    JOIN companies c ON jp.company_id = c.id
    JOIN locations l ON jp.location_id = l.id
    WHERE jp.is_active = TRUE
      AND jp.source_name != 'sample' AND jp.source_name IN {official_sources_sql()} AND jp.is_eligible_role = TRUE
      AND {geography_predicate}
      AND {get_deduplication_sql_predicate()}
      AND {get_public_visibility_sql_predicate(table_alias="jp")}
      AND c.name IS NOT NULL AND c.name != ''
    ORDER BY c.name ASC;
    """
    query_skills = f"""
    SELECT DISTINCT s.name
    FROM job_postings jp
    JOIN locations l ON jp.location_id = l.id
    JOIN job_posting_skills jps ON jp.id = jps.job_posting_id
    JOIN skills s ON jps.skill_id = s.id
    WHERE jp.is_active = TRUE
      AND jp.source_name != 'sample' AND jp.source_name IN {official_sources_sql()} AND jp.is_eligible_role = TRUE
      AND {geography_predicate}
      AND {get_deduplication_sql_predicate()}
      AND {get_public_visibility_sql_predicate(table_alias="jp")}
      AND s.name IS NOT NULL AND s.name != ''
    ORDER BY s.name ASC;
    """
    query_workplaces = f"""
    SELECT DISTINCT jp.workplace_type
    FROM job_postings jp
    JOIN locations l ON jp.location_id = l.id
    WHERE jp.is_active = TRUE
      AND jp.source_name != 'sample' AND jp.source_name IN {official_sources_sql()} AND jp.is_eligible_role = TRUE
      AND {geography_predicate}
      AND {get_deduplication_sql_predicate()}
      AND {get_public_visibility_sql_predicate(table_alias="jp")}
      AND jp.workplace_type IS NOT NULL AND jp.workplace_type != ''
    ORDER BY jp.workplace_type ASC;
    """
    query_role_types = f"""
    SELECT DISTINCT jp.role_type
    FROM job_postings jp
    JOIN locations l ON jp.location_id = l.id
    WHERE jp.is_active = TRUE
      AND jp.source_name != 'sample' AND jp.source_name IN {official_sources_sql()} AND jp.is_eligible_role = TRUE
      AND {geography_predicate}
      AND {get_deduplication_sql_predicate()}
      AND {get_public_visibility_sql_predicate(table_alias="jp")}
      AND jp.role_type IS NOT NULL AND jp.role_type != ''
    ORDER BY jp.role_type ASC;
    """

    try:
        with get_db_cursor() as cur:
            cur.execute(query_countries)
            countries = [row[0] for row in cur.fetchall()]

            cur.execute(query_companies)
            companies = [row[0] for row in cur.fetchall()]

            cur.execute(query_skills)
            skills = [row[0] for row in cur.fetchall()]

            cur.execute(query_workplaces)
            workplace_types = [row[0] for row in cur.fetchall()]

            cur.execute(query_role_types)
            role_types = [row[0] for row in cur.fetchall()]

            # Offer a metro only if the public results contain at least one job for it: same population
            # (target_postings), same matching (location_filter_clause) as /api/jobs.
            clauses = [location_filter_clause(label) for label in LOCATION_OPTIONS]
            location_query = (
                get_target_postings_cte()
                + "SELECT " + ", ".join(f"COALESCE(bool_or({sql}), FALSE)" for sql, _ in clauses)
                + " FROM target_postings tp JOIN job_postings jp ON jp.id = tp.id JOIN locations l ON l.id = jp.location_id"
            )
            cur.execute(location_query, [param for _, clause_params in clauses for param in clause_params])
            present = cur.fetchone()
            locations = [label for label, has_jobs in zip(LOCATION_OPTIONS, present) if has_jobs]

            return {
                "countries": countries,
                "companies": companies,
                "skills": skills,
                "workplace_types": workplace_types,
                "role_types": role_types,
                "locations": locations,
                "experience_levels": [
                    "internship", "entry", "mid", "senior"
                ],
            }
    except psycopg2.Error as err:
        logger.error("Database query failed in /api/jobs/filters: %s", err)
        raise HTTPException(status_code=500, detail="Database query error.")
    except Exception as err:
        logger.error("Unexpected error in /api/jobs/filters: %s", err)
        raise HTTPException(status_code=500, detail="Internal server error.")


@app.get("/api/jobs/{job_id}", response_model=JobDetail)
def get_job_detail(job_id: str):
    """
    Returns full details for a single active real job posting.
    Returns 404 if the job is not found, inactive, or a sample job.
    """
    reject_nul(job_id)
    query = f"""
    SELECT
        jp.job_id,
        jp.title,
        c.name AS company,
        COALESCE(l.location, 'Unspecified') AS location,
        COALESCE(l.country, 'Unspecified') AS country,
        jp.workplace_type,
        jp.role_type,
        jp.source_name,
        jp.source_url,
        jp.posted_at,
        jp.created_at,
        jp.description,
        COALESCE(ARRAY_AGG(DISTINCT s.name ORDER BY s.name) FILTER (WHERE s.name IS NOT NULL), '{{}}') AS skills,
        c.logo_url,
        c.logo_status,
        c.website_url,
        jp.company_apply_url,
        jp.linkedin_url,
        jp.simplify_url,
        jp.locations,
        jp.compensation,
        jp.term_season,
        jp.term_year,
        jp.experience_level
    FROM job_postings jp
    JOIN companies c ON jp.company_id = c.id
    LEFT JOIN locations l ON jp.location_id = l.id
    LEFT JOIN job_posting_skills jps ON jp.id = jps.job_posting_id
    LEFT JOIN skills s ON jps.skill_id = s.id
    WHERE jp.job_id = %s AND jp.is_active = TRUE AND jp.source_name != 'sample' AND jp.source_name IN {official_sources_sql()} AND jp.is_eligible_role = TRUE
    GROUP BY jp.id, jp.job_id, jp.title, c.name, c.logo_url, c.logo_status, c.website_url, l.location, l.country, jp.workplace_type, jp.role_type, jp.source_name, jp.source_url, jp.posted_at, jp.created_at, jp.description, jp.company_apply_url, jp.linkedin_url, jp.simplify_url;
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(query, (job_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Job posting '{job_id}' not found.")

            return {
                "locations": row[19] if len(row) > 19 else [],
                "compensation": row[20] if len(row) > 20 else None,
                "term_season": row[21] if len(row) > 21 else None,
                "term_year": row[22] if len(row) > 22 else None,
                "academic_term": format_academic_term(row[21], row[22]) if len(row) > 22 else None,
                "experience_level": row[23] if len(row) > 23 else None,
                "job_id": row[0],
                "title": row[1],
                "company": row[2],
                "location": row[3],
                "country": row[4],
                "workplace_type": row[5],
                "role_type": row[6],
                "source_name": row[7],
                "source_url": row[8],
                "company_apply_url": row[16] if (len(row) > 16 and row[16]) else (row[8] if row[8] and "linkedin.com" not in row[8] and "simplify.jobs" not in row[8] and "indeed.com" not in row[8] else None),
                "linkedin_url": row[17] if (len(row) > 17 and row[17]) else (row[8] if row[8] and "linkedin.com" in row[8] else None),
                "simplify_url": row[18] if (len(row) > 18 and row[18]) else (row[8] if row[8] and "simplify.jobs" in row[8] else None),
                "posted_at": row[9],
                "posted_at_precision": posted_at_precision(row[7], row[9]),
                "created_at": row[10],
                "freshness_status": classify_freshness_status(
                    posted_at=row[9],
                    created_at=row[10],
                    is_active=True,
                ),
                "recently_posted": is_job_recently_posted(
                    posted_at=row[9],
                ),
                "description": row[11],
                "skills": list(row[12]) if row[12] else [],
                "company_logo_url": row[13] if len(row) > 13 else None,
                "company_logo_status": row[14] if len(row) > 14 else None,
                "company_website_url": row[15] if len(row) > 15 else None,
            }
    except HTTPException:
        raise
    except psycopg2.Error as err:
        logger.error("Database query failed in /api/jobs/%s: %s", job_id, err)
        raise HTTPException(status_code=500, detail="Database query error.")
    except Exception as err:
        logger.error("Unexpected error in /api/jobs/%s: %s", job_id, err)
        raise HTTPException(status_code=500, detail="Internal server error.")


@app.get("/api/companies", response_model=List[CompanyInfo])
def get_companies_list():
    """
    Returns list of hiring companies with their verified company branding,
    logo status, source provenance, and active jobs count.
    """
    query = f"""
    {get_target_postings_cte()}
    SELECT 
        c.id,
        c.name,
        c.logo_url,
        c.logo_source_url,
        c.logo_status,
        c.website_url,
        COUNT(jp.id) AS active_jobs_count
    FROM companies c
    JOIN target_postings jp ON c.id = jp.company_id
    GROUP BY c.id, c.name, c.logo_url, c.logo_source_url, c.logo_status, c.website_url
    ORDER BY c.name ASC;
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "logo_url": r[2],
                    "logo_source_url": r[3],
                    "logo_status": r[4] or "unresolved",
                    "website_url": r[5],
                    "active_jobs_count": r[6] or 0,
                }
                for r in rows
            ]
    except Exception as err:
        logger.error("Error fetching companies: %s", err)
        raise HTTPException(status_code=500, detail="Database query error.")


@app.get("/api/companies/{company_name}", response_model=CompanyInfo)
def get_company_detail(company_name: str):
    """
    Returns verified company branding, logo status, and active job statistics
    for a specific company.
    """
    reject_nul(company_name)
    query = f"""
    {get_target_postings_cte()}
    SELECT 
        c.id,
        c.name,
        c.logo_url,
        c.logo_source_url,
        c.logo_status,
        c.website_url,
        COUNT(jp.id) AS active_jobs_count
    FROM companies c
    LEFT JOIN target_postings jp ON c.id = jp.company_id
    WHERE LOWER(c.name) = LOWER(%s)
    GROUP BY c.id, c.name, c.logo_url, c.logo_source_url, c.logo_status, c.website_url;
    """
    try:
        with get_db_cursor() as cur:
            cur.execute(query, (company_name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Company '{company_name}' not found.")
            return {
                "id": row[0],
                "name": row[1],
                "logo_url": row[2],
                "logo_source_url": row[3],
                "logo_status": row[4] or "unresolved",
                "website_url": row[5],
                "active_jobs_count": row[6] or 0,
            }
    except HTTPException:
        raise
    except Exception as err:
        logger.error("Error fetching company '%s': %s", company_name, err)
        raise HTTPException(status_code=500, detail="Database query error.")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("api.main:app", host="0.0.0.0", port=port, reload=False)


@app.get("/api/company-logos/{company_id}")
def get_company_logo(company_id: int):
    with get_db_cursor() as cur:
        cur.execute("SELECT logo_data, logo_content_type FROM companies WHERE id = %s AND logo_status = 'verified'", (company_id,))
        row = cur.fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Logo not found")
    return Response(bytes(row[0]), media_type=row[1], headers={
        "Cache-Control": "public, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        # Inline styles are allowed so brand SVGs that colour their paths with style attributes render
        # correctly; scripts, network, embedding and everything else stay denied by default-src 'none'.
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    })
