"""Load a crawl (crawl.py output) into a scratch PostgreSQL database, so a repair can be rehearsed on real production rows.

    createdb roleradar_replay && psql roleradar_replay -f db/schema.sql
    python -c "from db.migrate import run_migrations; run_migrations(defer_versions={'015_pay_rules_and_audit_repair.sql'})"   # up to 014
    python scripts/public_data_audit/replay_snapshot.py CRAWL_DIR          # load the snapshot
    python -m db.migrate                                                    # apply the migration under test, as production will

Uses the PG* environment variables. Never point it at a production database: it inserts rows.
"""
import json
import sys
from pathlib import Path

from psycopg2.extras import Json

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api.database import get_db_connection  # noqa: E402


def main(crawl_dir):
    jobs = json.loads((Path(crawl_dir) / "detail.json").read_text())
    conn = get_db_connection()
    with conn.cursor() as cur:
        for job in jobs:
            cur.execute("INSERT INTO companies(name, website_url, logo_status) VALUES (%s,%s,'unresolved') ON CONFLICT(name) DO UPDATE SET website_url=COALESCE(companies.website_url, EXCLUDED.website_url) RETURNING id",
                        (job["company"], job.get("company_website_url")))
            company_id = cur.fetchone()[0]
            cur.execute("INSERT INTO locations(location,country) VALUES (%s,%s) ON CONFLICT(location,country) DO UPDATE SET country=EXCLUDED.country RETURNING id",
                        (job["location"], job["country"]))
            location_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO job_postings(job_id,company_id,title,location_id,description,locations,compensation,workplace_type,role_type,
                       source_name,source_job_id,source_url,company_apply_url,linkedin_url,simplify_url,term_season,term_year,posted_at,
                       is_active,last_seen_at,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NOW(),%s) RETURNING id""",
                (job["job_id"], company_id, job["title"], location_id, job["description"], Json(job["locations"]),
                 Json(job["compensation"]) if job.get("compensation") else None, job["workplace_type"], job["role_type"],
                 job["source_name"], job["job_id"].split(":", 1)[1], job["source_url"], job.get("company_apply_url"),
                 job.get("linkedin_url"), job.get("simplify_url"), job.get("term_season"), job.get("term_year"),
                 job.get("posted_at"), job["created_at"]))
            posting_id = cur.fetchone()[0]
            for skill in job.get("skills") or []:
                cur.execute("INSERT INTO skills(name) VALUES (%s) ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id", (skill,))
                cur.execute("INSERT INTO job_posting_skills VALUES (%s,%s) ON CONFLICT DO NOTHING", (posting_id, cur.fetchone()[0]))
    conn.commit()
    print(f"loaded {len(jobs)} jobs")


if __name__ == "__main__":
    main(sys.argv[1])
