#!/usr/bin/env python3
"""
Career Intelligence / Job Analytics Platform (Phase 2 Database Ingestion)
Loads, normalizes, and ingests job postings into PostgreSQL.
"""

import argparse
import os
from pathlib import Path
import sys
from typing import Dict, List, Optional, Set, Tuple

# Ensure project root is in sys.path to safely import Phase 1 normalization logic
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import psycopg2
except ImportError:
    print(
        "Error: PostgreSQL driver 'psycopg2' is not installed.\n"
        "Please install it using: pip install psycopg2-binary",
        file=sys.stderr,
    )
    sys.exit(1)

from main import extract_skills_from_posting, load_job_postings

DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "sample_jobs.csv"


def get_db_connection():
    """
    Connects to the PostgreSQL database using environment variables or standard defaults.
    Supports DATABASE_URL for hosted providers, with fallback to local defaults.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    dbname = os.getenv("PGDATABASE", "roleradar")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    host = os.getenv("PGHOST")
    port = os.getenv("PGPORT")

    conn_params = {"dbname": dbname}
    if user:
        conn_params["user"] = user
    if password:
        conn_params["password"] = password
    if host:
        conn_params["host"] = host
    if port:
        conn_params["port"] = port

    return psycopg2.connect(**conn_params)


def get_or_create_company(cur, company_name: str) -> Tuple[int, bool]:
    """
    Retrieves company ID if existing, otherwise inserts and returns new ID.
    Returns (company_id, was_created).
    """
    cur.execute("SELECT id FROM companies WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s));", (company_name,))
    row = cur.fetchone()
    if row:
        return row[0], False
    cur.execute(
        "INSERT INTO companies (name) VALUES (%s) RETURNING id;",
        (company_name,),
    )
    return cur.fetchone()[0], True


def get_or_create_location(cur, location: str, country: str) -> Tuple[int, bool]:
    """
    Retrieves location ID if existing, otherwise inserts and returns new ID.
    Returns (location_id, was_created).
    """
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
    """
    Retrieves skill ID if existing, otherwise inserts and returns new ID.
    Returns (skill_id, was_created).
    """
    cur.execute("SELECT id FROM skills WHERE name = %s;", (skill_name,))
    row = cur.fetchone()
    if row:
        return row[0], False
    cur.execute(
        "INSERT INTO skills (name) VALUES (%s) RETURNING id;",
        (skill_name,),
    )
    return cur.fetchone()[0], True


def upsert_job_posting(
    cur, job_id: str, company_id: int, title: str, location_id: int
) -> Tuple[int, bool]:
    """
    Retrieves job posting ID if existing, otherwise inserts and returns new ID.
    Returns (job_posting_id, was_created).
    """
    cur.execute("SELECT id FROM job_postings WHERE job_id = %s;", (job_id,))
    row = cur.fetchone()
    if row:
        posting_id = row[0]
        cur.execute(
            """
            UPDATE job_postings
            SET company_id = %s, title = %s, location_id = %s
            WHERE id = %s;
            """,
            (company_id, title, location_id, posting_id),
        )
        return posting_id, False

    cur.execute(
        """
        INSERT INTO job_postings (job_id, company_id, title, location_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id;
        """,
        (job_id, company_id, title, location_id),
    )
    return cur.fetchone()[0], True


def link_job_posting_skill(cur, job_posting_id: int, skill_id: int) -> bool:
    """
    Links a job posting to a skill avoiding duplicate relations.
    Returns True if a new relationship was created, False if it already existed.
    """
    cur.execute(
        """
        INSERT INTO job_posting_skills (job_posting_id, skill_id)
        VALUES (%s, %s)
        ON CONFLICT (job_posting_id, skill_id) DO NOTHING
        RETURNING job_posting_id;
        """,
        (job_posting_id, skill_id),
    )
    return cur.fetchone() is not None


def ingest_postings(cur, postings: List[Dict[str, str]]) -> Dict[str, Dict[str, int]]:
    """
    Ingests parsed postings into PostgreSQL tables.
    Returns statistics on processed, newly created, and existing rows.
    """
    stats = {
        "postings": {"total": 0, "created": 0, "existing": 0},
        "companies": {"total": 0, "created": 0, "existing": 0},
        "locations": {"total": 0, "created": 0, "existing": 0},
        "skills": {"total": 0, "created": 0, "existing": 0},
        "relationships": {"total": 0, "created": 0, "existing": 0},
    }

    seen_companies: Set[str] = set()
    seen_locations: Set[Tuple[str, str]] = set()
    seen_skills: Set[str] = set()

    for item in postings:
        stats["postings"]["total"] += 1
        company_name = item["company"]
        location_str = item["location"]
        country_str = item["country"]  # already normalized by load_job_postings
        job_id = item["job_id"]
        title = item["title"]

        # 1. Company
        company_id, comp_created = get_or_create_company(cur, company_name)
        if company_name not in seen_companies:
            seen_companies.add(company_name)
            stats["companies"]["total"] += 1
            if comp_created:
                stats["companies"]["created"] += 1
            else:
                stats["companies"]["existing"] += 1

        # 2. Location
        loc_key = (location_str, country_str)
        location_id, loc_created = get_or_create_location(cur, location_str, country_str)
        if loc_key not in seen_locations:
            seen_locations.add(loc_key)
            stats["locations"]["total"] += 1
            if loc_created:
                stats["locations"]["created"] += 1
            else:
                stats["locations"]["existing"] += 1

        # 3. Job Posting
        posting_id, post_created = upsert_job_posting(
            cur, job_id, company_id, title, location_id
        )
        if post_created:
            stats["postings"]["created"] += 1
        else:
            stats["postings"]["existing"] += 1

        # 4. Skills (normalized and deduplicated per posting)
        skills = extract_skills_from_posting(item.get("skills", ""))
        for skill_name in skills:
            skill_id, skill_created = get_or_create_skill(cur, skill_name)
            if skill_name not in seen_skills:
                seen_skills.add(skill_name)
                stats["skills"]["total"] += 1
                if skill_created:
                    stats["skills"]["created"] += 1
                else:
                    stats["skills"]["existing"] += 1

            # 5. Link Posting to Skill
            stats["relationships"]["total"] += 1
            rel_created = link_job_posting_skill(cur, posting_id, skill_id)
            if rel_created:
                stats["relationships"]["created"] += 1
            else:
                stats["relationships"]["existing"] += 1

    return stats


def print_summary(stats: Dict[str, Dict[str, int]], dbname: str, csv_path: Path) -> None:
    """
    Prints a concise success summary to stdout.
    """
    print("=" * 66)
    print(" CAREER INTELLIGENCE / POSTGRESQL DATA INGESTION SUMMARY")
    print("=" * 66)
    print(f"Target Database     : {dbname}")
    print(f"Source CSV Path     : {csv_path}")
    print("-" * 66)
    print(
        f"Postings Imported   : {stats['postings']['total']} "
        f"(New: {stats['postings']['created']}, Existing: {stats['postings']['existing']})"
    )
    print(
        f"Companies Processed : {stats['companies']['total']} "
        f"(New: {stats['companies']['created']}, Existing: {stats['companies']['existing']})"
    )
    print(
        f"Locations Processed : {stats['locations']['total']} "
        f"(New: {stats['locations']['created']}, Existing: {stats['locations']['existing']})"
    )
    print(
        f"Skills Processed    : {stats['skills']['total']} "
        f"(New: {stats['skills']['created']}, Existing: {stats['skills']['existing']})"
    )
    print(
        f"Posting-Skill Links : {stats['relationships']['total']} "
        f"(New: {stats['relationships']['created']}, Existing: {stats['relationships']['existing']})"
    )
    print("=" * 66)
    print("Import completed successfully.")
    print("=" * 66)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest job postings from CSV into PostgreSQL."
    )
    parser.add_argument(
        "file_path",
        nargs="?",
        default=str(DEFAULT_DATA_PATH),
        help=f"Path to the job postings CSV file (default: {DEFAULT_DATA_PATH})",
    )
    args = parser.parse_args(argv)

    csv_path = Path(args.file_path).resolve()

    try:
        postings = load_job_postings(csv_path)
    except (FileNotFoundError, ValueError) as err:
        print(f"Error loading CSV: {err}", file=sys.stderr)
        return 1

    try:
        conn = get_db_connection()
    except Exception as err:
        print(f"Database connection error: {err}", file=sys.stderr)
        return 1

    dbname = getattr(conn.info, "dbname", None) or os.getenv("PGDATABASE", "roleradar")

    try:
        # Atomic transaction: commits on clean exit, rolls back on error
        with conn:
            with conn.cursor() as cur:
                stats = ingest_postings(cur, postings)
        print_summary(stats, dbname, csv_path)
        return 0
    except Exception as err:
        print(f"Ingestion failed and transaction was rolled back: {err}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
