"""
Core Ingestion Pipeline for RoleRadar.
Orchestrates fetching, SWE filtering, text cleaning, skill extraction,
atomic PostgreSQL persistence, and fail-safe tombstoning.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.database import get_db_connection
from collections import Counter
from ingestion.clients import get_ats_client
from ingestion.compensation import resolve_compensation
from ingestion.extractor import extract_skills, sanitize_html_description, sanitize_html_to_text
from ingestion.freshness import DEFAULT_FRESHNESS_DAYS, is_job_fresh
from ingestion.http_client import HardenedHttpClient, IngestionFetchError
from psycopg2.extras import Json

from ingestion.normalizer import (
    EARLY_CAREER_ROLE_TYPES,
    STUDENT_ENGINEER_REGEX,
    extract_academic_term,
    normalize_job_locations,
    is_user_facing_location_eligible,
    classify_application_urls,
    classify_role_type,
    classify_workplace,
    is_swe_role,
    normalize_location_and_country,
)

logger = logging.getLogger("ingestion.pipeline")


# --------------------------------------------------------------------------- field safety

TITLE_MAX = 255            # job_postings.title VARCHAR(255)
SOURCE_JOB_ID_MAX = 150    # job_postings.source_job_id VARCHAR(150)
COUNTRY_MAX = 100          # locations.country VARCHAR(100)


def fit_text(value: Any, limit: int) -> str:
    """NUL-free text that fits a VARCHAR(limit); over-long values keep their start plus an ellipsis."""
    text = str(value if value is not None else "").replace("\x00", "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


def normalize_source_job_id(value: Any) -> str:
    """Stable, schema-safe source identity: over-long ids become a deterministic sha256 digest."""
    text = str(value if value is not None else "").replace("\x00", "").strip()
    if len(text) <= SOURCE_JOB_ID_MAX:
        return text
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- tombstone guard

# A complete snapshot that would deactivate most of a company's jobs (or all of them) is far more
# likely a vendor/API fault than a real mass closure. Such a drop is only applied once several
# consecutive successful runs have observed the same reduced listing.
DROP_GUARD_MIN_DEACTIVATIONS = 3     # a drop must remove at least this many active jobs ...
DROP_GUARD_RATIO = 0.5               # ... and at least this fraction of the currently active jobs
DROP_GUARD_CONFIRMATIONS = 2         # earlier consistent observations needed before a suspicious drop is applied
DROP_GUARD_MAX_AGE_HOURS = 24        # ... and those observations must be this recent (runs are 6-hourly)

# Record persistence failures: a few bad rows are a partial success, but if every attempted record
# fails, or at least 80% of >= 5 attempted records fail, the ingester itself is broken.
RECORD_FAILURE_MIN_ATTEMPTS = 5
RECORD_FAILURE_RATIO = 0.8


def is_suspicious_drop(previous_active: int, would_deactivate: int, listed_count: int) -> bool:
    """
    True when a complete snapshot looks like a vendor fault rather than real churn:
    an empty listing while jobs are active, or a drop that would deactivate at least
    DROP_GUARD_MIN_DEACTIVATIONS jobs AND at least DROP_GUARD_RATIO (inclusive) of the active ones.
    """
    if would_deactivate <= 0 or previous_active <= 0:
        return False
    if listed_count == 0:
        return True
    return would_deactivate >= DROP_GUARD_MIN_DEACTIVATIONS and would_deactivate / previous_active >= DROP_GUARD_RATIO


def record_failure_is_systemic(attempted: int, failed: int) -> bool:
    """True when so many records failed to persist that the company sync itself must be reported as failed."""
    if attempted <= 0 or failed <= 0:
        return False
    if failed >= attempted:
        return True
    return attempted >= RECORD_FAILURE_MIN_ATTEMPTS and failed / attempted >= RECORD_FAILURE_RATIO


def evaluate_tombstone_guard(
    cur,
    company_id: int,
    source_name: str,
    sync_run_id: Optional[int],
    started_at: datetime,
    listed_ids: List[str],
    total_listed: int,
) -> Optional[str]:
    """
    Returns a human-readable reason when tombstoning must be suppressed despite an otherwise
    trustworthy complete snapshot, or None when deactivation is safe.

    Suppressed (see is_suspicious_drop): an empty complete snapshot, or a drop of >= 3 jobs and >= 50%
    of the active ones, unless the previous DROP_GUARD_CONFIRMATIONS runs already saw the same reduced
    count. Only runs that are completed, within DROP_GUARD_MAX_AGE_HOURS, have status success/partial_success
    and (crucially) had a TRUSTWORTHY source snapshot may confirm; failed or incomplete runs never do.
    """
    cur.execute(
        """SELECT COUNT(*),
                  COUNT(*) FILTER (WHERE last_seen_at < %s AND NOT (source_job_id = ANY(%s)))
           FROM job_postings
           WHERE source_name = %s AND company_id = %s AND source_name != 'sample' AND is_active = TRUE""",
        (started_at, listed_ids, source_name, company_id),
    )
    row = cur.fetchone()
    previous_active, would_deactivate = (
        (row[0], row[1]) if row and all(isinstance(v, int) for v in row[:2]) else (0, 0)
    )
    if would_deactivate == 0:
        return None

    zero_result = len(listed_ids) == 0
    if not is_suspicious_drop(previous_active, would_deactivate, len(listed_ids)):
        return None

    cur.execute(
        """SELECT jobs_fetched FROM sync_runs
           WHERE source_name = %s AND company_identifier = (
                 SELECT company_identifier FROM sync_runs WHERE id = %s)
             AND id <> %s AND status IN ('success', 'partial_success')
             AND snapshot_trustworthy = TRUE
             AND completed_at IS NOT NULL AND completed_at >= %s
           ORDER BY started_at DESC, id DESC LIMIT %s""",
        (source_name, sync_run_id, sync_run_id, started_at - timedelta(hours=DROP_GUARD_MAX_AGE_HOURS),
         DROP_GUARD_CONFIRMATIONS),
    )
    prior = [r[0] for r in cur.fetchall() if isinstance(r[0], int)]
    tolerance = 0 if total_listed == 0 else max(1, int(total_listed * 0.1))
    persistent = len(prior) >= DROP_GUARD_CONFIRMATIONS and all(abs(p - total_listed) <= tolerance for p in prior)
    if persistent:
        logger.warning(
            "Confirmed persistent reduction for company %s: %d consecutive runs listed ~%d jobs; applying tombstoning.",
            company_id, DROP_GUARD_CONFIRMATIONS + 1, total_listed,
        )
        return None
    kind = "a complete but EMPTY snapshot" if zero_result else "a large drop"
    return (
        f"Tombstoning suppressed: {kind} would deactivate {would_deactivate} of {previous_active} active jobs; "
        f"it will only be applied after {DROP_GUARD_CONFIRMATIONS} further consecutive runs confirm the same listing."
    )


def is_swe_posting(raw_job) -> bool:
    """SWE membership from titles; ambiguous technical student programs need software description evidence."""
    if is_swe_role(raw_job.title):
        return True
    return is_swe_role(raw_job.title, sanitize_html_to_text(raw_job.raw_description))


def resolve_job_term(raw_job, role_type: str, clean_description: str):
    """(term_season, term_year) from structured terms, title, then description (early-career only)."""
    term = extract_academic_term(
        raw_job.title,
        structured_terms=getattr(raw_job, "raw_terms", None),
        description=clean_description,
        role_type=role_type,
    )
    return (term["season"], term["year"]) if term else (None, None)


def build_job_id(source_name: str, source_job_id: str) -> str:
    """
    Constructs a deterministic unique identifier fitting within VARCHAR(100).
    Uses '<source_name>:<source_job_id>' by default. If the identifier exceeds
    100 characters, derives a stable SHA-256 hash.
    """
    candidate = f"{source_name}:{source_job_id}"
    if len(candidate) <= 100:
        return candidate

    # Truncate source_name to max 20 chars, hash the vendor ID with SHA-256
    clean_src = source_name[:20]
    sha_hash = hashlib.sha256(source_job_id.encode("utf-8")).hexdigest()[:60]
    return f"{clean_src}:{sha_hash}"


from ingestion.company_resolver import get_or_create_company_with_branding


def get_or_create_company(
    cur,
    company_name: str,
    ats_type: Optional[str] = None,
    identifier: Optional[str] = None,
) -> Tuple[int, bool]:
    """Retrieves existing company ID or creates a new one with company-level branding."""
    return get_or_create_company_with_branding(
        cur, company_name, ats_type=ats_type, identifier=identifier
    )


def get_or_create_location(cur, location: str, country: str) -> Tuple[int, bool]:
    """Retrieves existing location ID or creates a new one."""
    cur.execute(
        "SELECT id FROM locations WHERE location = %s AND country = %s;",
        (location, country),
    )
    row = cur.fetchone()
    if row:
        return row[0], False
    cur.execute(
        "INSERT INTO locations (location, country) VALUES (%s, %s) RETURNING id;",
        (location, country),
    )
    return cur.fetchone()[0], True


def get_or_create_skill(cur, skill_name: str) -> Tuple[int, bool]:
    """Retrieves existing skill ID or creates a new one."""
    cur.execute("SELECT id FROM skills WHERE name = %s;", (skill_name,))
    row = cur.fetchone()
    if row:
        return row[0], False
    cur.execute("INSERT INTO skills (name) VALUES (%s) RETURNING id;", (skill_name,))
    return cur.fetchone()[0], True


def upsert_job_posting(
    cur,
    job_id: str,
    company_id: int,
    title: str,
    location_id: int,
    description: str,
    workplace_type: str,
    source_name: str,
    source_job_id: str,
    source_url: str,
    posted_at: Optional[datetime],
    role_type: str = "unknown",
    company_apply_url: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    simplify_url: Optional[str] = None,
    term_season: Optional[str] = None,
    term_year: Optional[int] = None,
) -> Tuple[int, bool]:
    """
    Inserts a new job posting or updates an existing one matching (source_name, source_job_id).
    Maintains created_at unchanged while updating last_seen_at and updated_at.
    Categorizes and persists company_apply_url, linkedin_url, and simplify_url routes.
    """
    classified = classify_application_urls(
        source_url=source_url,
        company_apply_url=company_apply_url,
        linkedin_url=linkedin_url,
        simplify_url=simplify_url,
    )
    c_apply = classified["company_apply_url"]
    c_linkedin = classified["linkedin_url"]
    c_simplify = classified["simplify_url"]
    c_source = classified["source_url"] or source_url

    cur.execute(
        """
        SELECT id FROM job_postings 
        WHERE source_name = %s AND source_job_id = %s;
        """,
        (source_name, source_job_id),
    )
    row = cur.fetchone()

    if row:
        posting_id = row[0]
        cur.execute(
            """
            UPDATE job_postings
            SET company_id = %s,
                location_id = %s,
                title = %s,
                description = %s,
                workplace_type = %s,
                role_type = %s,
                source_url = %s,
                company_apply_url = COALESCE(%s, company_apply_url),
                linkedin_url = COALESCE(%s, linkedin_url),
                simplify_url = COALESCE(%s, simplify_url),
                term_season = %s,
                term_year = %s,
                posted_at = COALESCE(%s, posted_at),
                is_active = TRUE,
                is_eligible_role = TRUE,
                last_seen_at = NOW(),
                updated_at = NOW()
            WHERE id = %s;
            """,
            (
                company_id,
                location_id,
                title,
                description,
                workplace_type,
                role_type,
                c_source,
                c_apply,
                c_linkedin,
                c_simplify,
                term_season,
                term_year,
                posted_at,
                posting_id,
            ),
        )
        return posting_id, False

    cur.execute(
        """
        INSERT INTO job_postings (
            job_id, company_id, title, location_id, description,
            workplace_type, role_type, source_name, source_job_id, source_url,
            company_apply_url, linkedin_url, simplify_url,
            term_season, term_year,
            posted_at, is_active, last_seen_at, created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, TRUE, NOW(), NOW(), NOW()
        )
        RETURNING id;
        """,
        (
            job_id,
            company_id,
            title,
            location_id,
            description,
            workplace_type,
            role_type,
            source_name,
            source_job_id,
            c_source,
            c_apply,
            c_linkedin,
            c_simplify,
            term_season,
            term_year,
            posted_at,
        ),
    )
    return cur.fetchone()[0], True


def sync_posting_skills(cur, job_posting_id: int, skill_ids: Set[int]) -> Tuple[int, int]:
    """
    Synchronizes skills for a job posting:
    - Removes stale skill relationships.
    - Adds newly detected skill relationships.
    Returns (added_count, removed_count).
    """
    cur.execute(
        "SELECT skill_id FROM job_posting_skills WHERE job_posting_id = %s;",
        (job_posting_id,),
    )
    current_ids = {r[0] for r in cur.fetchall()}

    stale_ids = current_ids - skill_ids
    new_ids = skill_ids - current_ids

    removed_count = 0
    for s_id in stale_ids:
        cur.execute(
            "DELETE FROM job_posting_skills WHERE job_posting_id = %s AND skill_id = %s;",
            (job_posting_id, s_id),
        )
        removed_count += 1

    added_count = 0
    for s_id in new_ids:
        cur.execute(
            """
            INSERT INTO job_posting_skills (job_posting_id, skill_id)
            VALUES (%s, %s)
            ON CONFLICT (job_posting_id, skill_id) DO NOTHING;
            """,
            (job_posting_id, s_id),
        )
        added_count += 1

    return added_count, removed_count


def sync_company(
    company_config: Dict[str, Any],
    db_conn=None,
    http_client: Optional[HardenedHttpClient] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Executes an end-to-end sync for a single company:
    1. Records execution in sync_runs.
    2. Fetches public ATS feed.
    3. Filters for SWE roles.
    4. Cleans HTML, normalizes locations and workplace types.
    5. Extracts and links technical skills.
    6. Upserts postings atomically.
    7. Executes tombstoning ONLY if fetch was 100% complete with 0 parse errors.
    """
    company_name = company_config["name"]
    ats_type = company_config["ats"]
    identifier = company_config["identifier"]
    started_at = datetime.now(timezone.utc)

    logger.info("Starting sync for %s (ATS: %s, Identifier: %s, dry_run=%s)", company_name, ats_type, identifier, dry_run)

    client = get_ats_client(ats_type, http_client=http_client)

    # In dry-run mode: fetch, filter, extract, and return without database mutations
    if dry_run:
        fetch_result = client.fetch_jobs(company_name, identifier)
        swe_jobs = [j for j in fetch_result.jobs if j.is_listed and is_swe_posting(j)]
        sample_skills: Set[str] = set()
        for j in swe_jobs[:5]:
            clean_text = sanitize_html_to_text(j.raw_description)
            sample_skills.update(extract_skills(f"{j.title}\n{clean_text}"))

        role_counts: Counter = Counter()
        term_counts: Counter = Counter()
        eligible = canada = canada_early = 0
        for j in swe_jobs:
            clean_text = sanitize_html_to_text(j.raw_description)
            locations = normalize_job_locations(j.raw_location, j.raw_locations)
            if not any(is_user_facing_location_eligible(l["location"], l["country"]) for l in locations):
                continue
            eligible += 1
            role_type = classify_role_type(j.title, clean_text, j.raw_job_type)
            role_counts[role_type] += 1
            term = resolve_job_term(j, role_type, clean_text)
            if term[0]:
                term_counts[f"{term[0]} {term[1]}"] += 1
            if any(l["country"] == "Canada" and is_user_facing_location_eligible(l["location"], l["country"]) for l in locations):
                canada += 1
                if role_type in EARLY_CAREER_ROLE_TYPES:
                    canada_early += 1

        return {
            "company": company_name,
            "ats": ats_type,
            "status": "dry_run",
            "jobs_fetched": fetch_result.total_raw_records,
            "swe_jobs_accepted": len(swe_jobs),
            "eligible_jobs": eligible,
            "canada_jobs": canada,
            "canada_early_career_jobs": canada_early,
            "role_type_counts": dict(role_counts),
            "term_counts": dict(term_counts),
            "fetch_complete": fetch_result.fetch_complete,
            "parse_error_count": fetch_result.parse_error_count,
            "sample_skills": sorted(list(sample_skills))[:10],
            "error_message": None,
        }

    owns_connection = False
    if db_conn is None:
        db_conn = get_db_connection()
        owns_connection = True

    sync_run_id = None
    try:
        # Step A: Register sync run record
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_runs (source_name, company_identifier, status, started_at)
                VALUES (%s, %s, 'running', %s)
                RETURNING id;
                """,
                (ats_type, identifier, started_at),
            )
            sync_run_id = cur.fetchone()[0]
        db_conn.commit()

        # Step B: Fetch ATS postings
        fetch_result = client.fetch_jobs(company_name, identifier)

        # Step C: Filter for SWE roles
        swe_jobs = [j for j in fetch_result.jobs if j.is_listed and is_swe_posting(j)]
        logger.info(
            "%s: %d total vendor jobs, %d qualified as SWE roles (parse errors: %d)",
            company_name,
            fetch_result.total_raw_records,
            len(swe_jobs),
            fetch_result.parse_error_count,
        )

        # Step D & E: Database persistence within an atomic transaction
        jobs_upserted = 0
        jobs_deactivated = 0

        with db_conn.cursor() as cur:
            company_id, _ = get_or_create_company(
                cur, company_name, ats_type=ats_type, identifier=identifier
            )

            record_errors: List[str] = []

            def persist_record(raw_job) -> None:
                source_job_id = normalize_source_job_id(raw_job.source_job_id)
                title = fit_text(raw_job.title, TITLE_MAX)
                job_locations = normalize_job_locations(raw_job.raw_location, raw_job.raw_locations)
                for loc in job_locations:
                    loc["country"] = fit_text(loc.get("country"), COUNTRY_MAX)
                primary = next((loc for loc in job_locations if is_user_facing_location_eligible(loc["location"], loc["country"])), job_locations[0])
                norm_loc, norm_country = primary["location"], primary["country"]
                location_id, _ = get_or_create_location(cur, norm_loc, norm_country)
                clean_description = sanitize_html_to_text(raw_job.raw_description).replace("\x00", "")
                rich_description = (sanitize_html_description(raw_job.raw_description) or clean_description).replace("\x00", "")
                workplace_type = classify_workplace(
                    location_text=raw_job.raw_location,
                    workplace_type_raw=raw_job.raw_workplace_type,
                    title=raw_job.title,
                    description=clean_description,
                )

                # Skill extraction from title + cleaned description
                skill_names = extract_skills(f"{raw_job.title}\n{clean_description}")
                skill_ids: Set[int] = set()
                for s_name in skill_names:
                    s_id, _ = get_or_create_skill(cur, s_name)
                    skill_ids.add(s_id)

                job_id = build_job_id(raw_job.source_name, source_job_id)

                role_type = classify_role_type(
                    title=raw_job.title,
                    description=clean_description,
                    raw_job_type=raw_job.raw_job_type,
                )
                term_season, term_year = resolve_job_term(raw_job, role_type, clean_description)

                posting_id, _ = upsert_job_posting(
                    cur=cur,
                    job_id=job_id,
                    company_id=company_id,
                    title=title,
                    location_id=location_id,
                    description=rich_description,
                    workplace_type=workplace_type,
                    source_name=raw_job.source_name,
                    source_job_id=source_job_id,
                    source_url=raw_job.source_url,
                    posted_at=raw_job.posted_at,
                    role_type=role_type,
                    company_apply_url=getattr(raw_job, "company_apply_url", None),
                    linkedin_url=getattr(raw_job, "linkedin_url", None),
                    simplify_url=getattr(raw_job, "simplify_url", None),
                    term_season=term_season,
                    term_year=term_year,
                )
                # What the source published stays as published; believable pay stated only in the text is added beside it.
                stored_compensation = resolve_compensation(raw_job.compensation, raw_job.raw_description, job_locations)
                cur.execute(
                    "UPDATE job_postings SET locations = %s, compensation = %s WHERE id = %s",
                    (Json(job_locations), Json(stored_compensation) if stored_compensation else None, posting_id),
                )
                sync_posting_skills(cur, posting_id, skill_ids)

            for raw_job in swe_jobs:
                # Each record runs in its own savepoint so one bad row can never roll back the others.
                cur.execute("SAVEPOINT sync_record")
                try:
                    persist_record(raw_job)
                except Exception as record_err:
                    try:
                        cur.execute("ROLLBACK TO SAVEPOINT sync_record")
                    except Exception:
                        raise record_err  # connection-level failure: fatal for the whole company
                    message = f"{raw_job.source_job_id}: {type(record_err).__name__}: {str(record_err)[:160]}"
                    record_errors.append(message)
                    logger.warning("%s: skipped one record (%s)", company_name, message)
                else:
                    jobs_upserted += 1
                finally:
                    cur.execute("RELEASE SAVEPOINT sync_record")

            # Role membership is independent of open/closed state. A source-listed
            # non-SWE role stays active, but must not retain an old eligible title.
            for raw_job in fetch_result.jobs:
                if raw_job.is_listed and not is_swe_posting(raw_job):
                    cur.execute(
                        """UPDATE job_postings SET title = %s, is_eligible_role = FALSE,
                           is_active = TRUE, last_seen_at = NOW(), updated_at = NOW()
                           WHERE source_name = %s AND source_job_id = %s AND company_id = %s""",
                        (fit_text(raw_job.title, TITLE_MAX), raw_job.source_name, normalize_source_job_id(raw_job.source_job_id), company_id),
                    )

            # Step F: Tombstoning. Only a trustworthy complete official snapshot may deactivate jobs,
            # and even then a suspicious zero-result / mass drop needs confirmation first.
            listed_ids = [normalize_source_job_id(j.source_job_id) for j in fetch_result.jobs if j.is_listed]
            warnings: List[str] = []
            snapshot_trustworthy = (
                fetch_result.fetch_complete and fetch_result.parse_error_count == 0
                and fetch_result.total_raw_records == len(fetch_result.jobs)
                and len({j.source_job_id for j in fetch_result.jobs}) == len(fetch_result.jobs)
            )
            suppression_reason: Optional[str] = None
            systemic_failure = record_failure_is_systemic(len(swe_jobs), len(record_errors))
            if systemic_failure:
                suppression_reason = (
                    f"Tombstoning suppressed: {len(record_errors)} of {len(swe_jobs)} records failed to persist "
                    f"(systematic failure); first error: {record_errors[0]}"
                )
            elif snapshot_trustworthy:
                suppression_reason = evaluate_tombstone_guard(
                    cur, company_id, ats_type, sync_run_id, started_at, listed_ids, fetch_result.total_raw_records
                )
            else:
                suppression_reason = (
                    f"Tombstoning suppressed: source snapshot not trustworthy "
                    f"(complete={fetch_result.fetch_complete}, parse_errors={fetch_result.parse_error_count}, "
                    f"listed={len(fetch_result.jobs)}/{fetch_result.total_raw_records})."
                )

            if suppression_reason is None:
                cur.execute(
                    """
                    UPDATE job_postings
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE source_name = %s
                      AND company_id = %s
                      AND source_name != 'sample'
                      AND last_seen_at < %s
                      AND NOT (source_job_id = ANY(%s))
                      AND is_active = TRUE
                    RETURNING id;
                    """,
                    (ats_type, company_id, started_at, listed_ids),
                )
                jobs_deactivated = len(cur.fetchall())
                final_status = "success"
            else:
                logger.warning("%s: %s", company_name, suppression_reason)
                warnings.append(suppression_reason)
                jobs_deactivated = 0
                # Valid rows were still upserted: that is partial success, unless nothing useful arrived.
                final_status = "partial_success" if (fetch_result.jobs or snapshot_trustworthy) else "failed"
                if systemic_failure:
                    final_status = "failed"

            if record_errors:
                warnings.append(f"{len(record_errors)} record(s) skipped after failing database validation: {record_errors[0]}")
                if final_status == "success":
                    final_status = "partial_success"
            if fetch_result.parse_error_count:
                warnings.append(f"{fetch_result.parse_error_count} malformed source record(s) skipped while parsing.")
            error_msg = " | ".join(warnings) if warnings else None

        # Commit posting transactions
        db_conn.commit()

        # Step G: Update sync_runs metrics
        with db_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sync_runs
                SET status = %s,
                    jobs_fetched = %s,
                    jobs_upserted = %s,
                    jobs_deactivated = %s,
                    snapshot_trustworthy = %s,
                    completed_at = NOW(),
                    error_message = %s
                WHERE id = %s;
                """,
                (
                    final_status,
                    fetch_result.total_raw_records,
                    jobs_upserted,
                    jobs_deactivated,
                    snapshot_trustworthy,
                    error_msg,
                    sync_run_id,
                ),
            )
        db_conn.commit()

        return {
            "company": company_name,
            "ats": ats_type,
            "status": final_status,
            "jobs_fetched": fetch_result.total_raw_records,
            "swe_jobs_accepted": len(swe_jobs),
            "jobs_upserted": jobs_upserted,
            "jobs_deactivated": jobs_deactivated,
            "parse_error_count": fetch_result.parse_error_count,
            "record_error_count": len(record_errors),
            "warnings": warnings,
            "tombstone_suppressed_reason": suppression_reason,
            "error_message": error_msg,
        }

    except Exception as err:
        logger.error("Sync failed for %s (%s): %s", company_name, identifier, err, exc_info=True)
        try:
            db_conn.rollback()
        except Exception:
            pass

        if sync_run_id:
            try:
                with db_conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE sync_runs
                        SET status = 'failed',
                            error_message = %s,
                            completed_at = NOW()
                        WHERE id = %s;
                        """,
                        (str(err), sync_run_id),
                    )
                db_conn.commit()
            except Exception as update_err:
                logger.error("Failed to update sync_runs failure state for run %s: %s", sync_run_id, update_err)

        return {
            "company": company_name,
            "ats": ats_type,
            "status": "failed",
            "jobs_fetched": 0,
            "swe_jobs_accepted": 0,
            "jobs_upserted": 0,
            "jobs_deactivated": 0,
            "error_message": str(err),
        }
    finally:
        if owns_connection:
            db_conn.close()


def sync_broad_source(
    source_name: str = "jobicy",
    db_conn=None,
    http_client: Optional[HardenedHttpClient] = None,
    dry_run: bool = False,
    count: int = 50,
    max_pages: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Executes an end-to-end sync for a broad/aggregator job feed (e.g. 'jobicy', 'remotive', 'arbeitnow'):
    1. Fetches feed using source client adapter.
    2. Filters for SWE/technical roles.
    3. Normalizes location, workplace type, and role type.
    4. Extracts skills.
    5. Atomically upserts jobs across diverse hiring companies.
    6. CRITICAL: Aggregator tombstoning safety - NEVER bulk-deactivates historical jobs
       based merely on absence from a limited query response.
    """
    started_at = datetime.now(timezone.utc)
    logger.info("Starting broad source sync for %s (dry_run=%s, count=%d)", source_name, dry_run, count)

    owns_connection = False
    if db_conn is None and not dry_run:
        db_conn = get_db_connection()
        owns_connection = True

    sync_run_id = None
    try:
        if not dry_run:
            # Step A: Register sync run record
            with db_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sync_runs (source_name, company_identifier, status, started_at)
                    VALUES (%s, %s, 'running', %s)
                    RETURNING id;
                    """,
                    (source_name, "all", started_at),
                )
                sync_run_id = cur.fetchone()[0]
            db_conn.commit()

        client = get_ats_client(source_name, http_client=http_client)
        fetch_kwargs: Dict[str, Any] = {}
        if max_pages is not None:
            fetch_kwargs["max_pages"] = max_pages
        elif source_name == "arbeitnow":
            fetch_kwargs["max_pages"] = 2
        elif count is not None:
            fetch_kwargs["count"] = count
        fetch_result = client.fetch_jobs(**fetch_kwargs)

        # Filter for SWE / technical roles
        swe_jobs = [j for j in fetch_result.jobs if j.is_listed and is_swe_posting(j)]

        # Compute role_type, workplace_type, country, and freshness analytics for verification
        role_type_counts: Counter = Counter()
        workplace_counts: Counter = Counter()
        country_counts: Counter = Counter()
        posted_dates: List[datetime] = []
        stale_count = 0

        for j in swe_jobs:
            clean_desc = sanitize_html_to_text(j.raw_description)
            rt = classify_role_type(j.title, clean_desc, j.raw_job_type)
            wt = classify_workplace(
                location_text=j.raw_location,
                workplace_type_raw=j.raw_workplace_type,
                title=j.title,
                description=clean_desc,
            )
            _, norm_country = normalize_location_and_country(j.raw_location)
            role_type_counts[rt] += 1
            workplace_counts[wt] += 1
            country_counts[norm_country] += 1
            if j.posted_at:
                posted_dates.append(j.posted_at)
                if not is_job_fresh(j.posted_at, started_at, freshness_days=DEFAULT_FRESHNESS_DAYS, reference_time=started_at):
                    stale_count += 1

        posted_dates_sorted = sorted(posted_dates)
        oldest_posted = posted_dates_sorted[0].isoformat() if posted_dates_sorted else None
        newest_posted = posted_dates_sorted[-1].isoformat() if posted_dates_sorted else None

        # In dry-run mode: return metadata without touching the database
        if dry_run:
            sample_jobs = [
                {
                    "company": j.company_name,
                    "title": j.title,
                    "location": j.raw_location,
                    "workplace": classify_workplace(
                        location_text=j.raw_location,
                        workplace_type_raw=j.raw_workplace_type,
                        title=j.title,
                        description=sanitize_html_to_text(j.raw_description),
                    ),
                    "role_type": classify_role_type(j.title, j.raw_description, j.raw_job_type),
                    "posted_at": j.posted_at.isoformat() if j.posted_at else None,
                    "source_url": j.source_url,
                }
                for j in swe_jobs[:10]
            ]
            return {
                "company": f"{source_name.title()} Feed",
                "ats": source_name,
                "status": "dry_run",
                "jobs_fetched": fetch_result.total_raw_records,
                "swe_jobs_accepted": len(swe_jobs),
                "parse_error_count": fetch_result.parse_error_count,
                "role_type_counts": dict(role_type_counts),
                "workplace_counts": dict(workplace_counts),
                "country_counts": dict(country_counts),
                "oldest_posted_at": oldest_posted,
                "newest_posted_at": newest_posted,
                "stale_rejected_count": stale_count,
                "sample_jobs": sample_jobs,
                "raw_swe_jobs": swe_jobs,
                "error_message": None,
            }

        # Step B: Database persistence across hiring companies
        jobs_upserted = 0
        with db_conn.cursor() as cur:
            for raw_job in swe_jobs:
                company_id, _ = get_or_create_company(cur, raw_job.company_name)
                job_locations = normalize_job_locations(raw_job.raw_location, raw_job.raw_locations)
                primary = next((loc for loc in job_locations if is_user_facing_location_eligible(loc["location"], loc["country"])), job_locations[0])
                norm_loc, norm_country = primary["location"], primary["country"]
                location_id, _ = get_or_create_location(cur, norm_loc, norm_country)
                clean_description = sanitize_html_to_text(raw_job.raw_description)
                rich_description = sanitize_html_description(raw_job.raw_description) or clean_description
                workplace_type = classify_workplace(
                    location_text=raw_job.raw_location,
                    workplace_type_raw=raw_job.raw_workplace_type,
                    title=raw_job.title,
                    description=clean_description,
                )
                role_type = classify_role_type(
                    title=raw_job.title,
                    description=clean_description,
                    raw_job_type=raw_job.raw_job_type,
                )
                term_season, term_year = resolve_job_term(raw_job, role_type, clean_description)

                # Skill extraction
                skill_names = extract_skills(f"{raw_job.title}\n{clean_description}")
                skill_ids: Set[int] = set()
                for s_name in skill_names:
                    s_id, _ = get_or_create_skill(cur, s_name)
                    skill_ids.add(s_id)

                job_id = build_job_id(raw_job.source_name, raw_job.source_job_id)

                posting_id, _ = upsert_job_posting(
                    cur=cur,
                    job_id=job_id,
                    company_id=company_id,
                    title=raw_job.title,
                    location_id=location_id,
                    description=rich_description,
                    workplace_type=workplace_type,
                    source_name=raw_job.source_name,
                    source_job_id=raw_job.source_job_id,
                    source_url=raw_job.source_url,
                    posted_at=raw_job.posted_at,
                    role_type=role_type,
                    company_apply_url=getattr(raw_job, "company_apply_url", None),
                    linkedin_url=getattr(raw_job, "linkedin_url", None),
                    simplify_url=getattr(raw_job, "simplify_url", None),
                    term_season=term_season,
                    term_year=term_year,
                )
                # What the source published stays as published; believable pay stated only in the text is added beside it.
                stored_compensation = resolve_compensation(raw_job.compensation, raw_job.raw_description, job_locations)
                cur.execute(
                    "UPDATE job_postings SET locations = %s, compensation = %s WHERE id = %s",
                    (Json(job_locations), Json(stored_compensation) if stored_compensation else None, posting_id),
                )
                jobs_upserted += 1

                # Sync skills
                sync_posting_skills(cur, posting_id, skill_ids)

        db_conn.commit()

        # A partial aggregator result is a degraded run even though safe upserts succeeded.
        final_status = "success" if fetch_result.fetch_complete and fetch_result.parse_error_count == 0 else "failed"
        error_msg = None if final_status == "success" else "Incomplete aggregator response; no jobs deactivated."
        # Step C: Update sync_runs metrics (NO tombstoning for broad aggregators!)
        with db_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sync_runs
                SET status = %s,
                    jobs_fetched = %s,
                    jobs_upserted = %s,
                    jobs_deactivated = 0,
                    completed_at = NOW(),
                    error_message = %s
                WHERE id = %s;
                """,
                (
                    final_status,
                    fetch_result.total_raw_records,
                    jobs_upserted,
                    error_msg,
                    sync_run_id,
                ),
            )
        db_conn.commit()

        return {
            "company": f"{source_name.title()} Feed",
            "ats": source_name,
            "status": final_status,
            "jobs_fetched": fetch_result.total_raw_records,
            "swe_jobs_accepted": len(swe_jobs),
            "jobs_upserted": jobs_upserted,
            "jobs_deactivated": 0,
            "role_type_counts": dict(role_type_counts),
            "workplace_counts": dict(workplace_counts),
            "error_message": error_msg,
        }

    except Exception as err:
        logger.error("Sync failed for broad source %s: %s", source_name, err, exc_info=True)
        try:
            db_conn.rollback()
        except Exception:
            pass

        if sync_run_id:
            try:
                with db_conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE sync_runs
                        SET status = 'failed',
                            error_message = %s,
                            completed_at = NOW()
                        WHERE id = %s;
                        """,
                        (str(err), sync_run_id),
                    )
                db_conn.commit()
            except Exception as update_err:
                logger.error("Failed to update sync_runs failure state for run %s: %s", sync_run_id, update_err)

        return {
            "company": f"{source_name.title()} Feed",
            "ats": source_name,
            "status": "failed",
            "jobs_fetched": 0,
            "swe_jobs_accepted": 0,
            "jobs_upserted": 0,
            "jobs_deactivated": 0,
            "error_message": str(err),
        }
    finally:
        if owns_connection:
            db_conn.close()
