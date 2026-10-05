"""
Repeatable database migration runner for RoleRadar.
Safely applies SQL migrations in version order from db/migrations/
and tracks applied versions in a schema_migrations table.
"""

import logging
import os
from pathlib import Path
import sys

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.repair_public_data import repair_public_data
from ingestion.pipeline import get_db_connection
from ingestion.company_resolver import seed_and_audit_all_target_companies, sync_canonical_company_names

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("db.migrate")


def ensure_migration_table(conn):
    """Creates schema_migrations table if not already present."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(100) PRIMARY KEY,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    conn.commit()


def get_applied_migrations(conn):
    """Returns set of already-applied migration versions."""
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations;")
        return {row[0] for row in cur.fetchall()}


def run_migrations(conn=None, *, defer_versions=()):
    """
    Finds and applies pending migrations from db/migrations/ in order.
    Idempotent and safe to run repeatedly on any database environment.
    """
    owns_conn = False
    if conn is None:
        conn = get_db_connection()
        owns_conn = True

    try:
        ensure_migration_table(conn)
        applied = get_applied_migrations(conn)

        migrations_dir = PROJECT_ROOT / "db" / "migrations"
        if not migrations_dir.is_dir():
            logger.warning("Migrations directory not found at %s", migrations_dir)
            return

        migration_files = sorted(migrations_dir.glob("*.sql"))
        logger.info("Found %d total migration files in %s", len(migration_files), migrations_dir)

        applied_count = 0
        for m_file in migration_files:
            version = m_file.name
            if version in applied:
                logger.debug("Migration %s already applied, skipping", version)
                continue
            if version in defer_versions:
                logger.info("Deferring %s to the serialized production migration workflow", version)
                continue

            logger.info("Applying migration: %s", version)
            sql_content = m_file.read_text(encoding="utf-8")

            with conn.cursor() as cur:
                cur.execute(sql_content)
                if version in ("012_public_data_contracts.sql", "014_repair_locations_and_company_names.sql", "015_pay_rules_and_audit_repair.sql"):
                    logger.info("Repaired %d stored postings", repair_public_data(conn))
                cur.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, NOW());",
                    (version,),
                )
            conn.commit()
            applied_count += 1
            logger.info("Successfully applied migration %s", version)

        # Configured spellings win over merged case variants (idempotent, only touches case differences)
        logger.info("Restored %d configured company name spellings", sync_canonical_company_names(conn))

        # Audit and seed branding metadata for all target companies
        logger.info("Syncing verified company branding catalog...")
        seeded = seed_and_audit_all_target_companies(conn)
        logger.info("Company branding sync complete: %d verified target companies aligned", seeded["verified_count"])

        logger.info("Migration run complete: %d new migrations applied.", applied_count)
        return applied_count
    finally:
        if owns_conn:
            conn.close()


if __name__ == "__main__":
    run_migrations()
