"""Regressions from the production beta audit: stored location debris and company-name casing."""
import json
from pathlib import Path
from uuid import uuid4

from psycopg2.extras import Json

from db.repair_public_data import repair_public_data
from ingestion.company_resolver import sync_canonical_company_names
from ingestion.normalizer import normalize_job_locations, tidy_location_label
from tests.test_public_visibility import conn, _company, _insert  # noqa: F401  (conn is a pytest fixture)

CONFIG = json.loads((Path(__file__).resolve().parent.parent / "config" / "target_companies.json").read_text())


def test_tidy_location_label_removes_separator_debris_only():
    assert tidy_location_label("Remote - , Canada") == "Remote - Canada"
    assert tidy_location_label("remote - , US") == "remote - US"
    assert tidy_location_label("Toronto, ON") == "Toronto, ON"
    assert tidy_location_label("Remote - Canada") == "Remote - Canada"
    assert tidy_location_label("A,, B") == "A, B"


def test_normalizer_repairs_already_malformed_stored_labels():
    entries = [{"location": "Remote - , Canada", "country": "Canada"}, {"location": "Remote - , United States", "country": "United States"}]
    result = normalize_job_locations("Remote - , Canada", entries)
    assert [item["location"] for item in result] == ["Remote - Canada", "Remote - United States"]


def test_repair_job_fixes_stored_rows_in_place(conn):
    name, cid = _company(conn)
    with conn.cursor() as cur:
        _insert(cur, cid, name, days_old=0, location="Remote - Canada")
        cur.execute("INSERT INTO locations(location,country) VALUES ('Remote - , Canada','Canada') ON CONFLICT DO NOTHING")
        cur.execute("SELECT id FROM locations WHERE location='Remote - , Canada' AND country='Canada'")
        bad_location = cur.fetchone()[0]
        cur.execute(
            "UPDATE job_postings SET location_id=%s, locations=%s WHERE job_id=%s",
            (bad_location, Json([{"location": "Remote - , Canada", "country": "Canada"}, {"location": "Remote - , United States", "country": "United States"}]), name),
        )
    repair_public_data(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT l.location, jp.locations FROM job_postings jp JOIN locations l ON l.id=jp.location_id WHERE jp.job_id=%s", (name,))
        label, locations = cur.fetchone()
    assert label == "Remote - Canada"
    assert [item["location"] for item in locations] == ["Remote - Canada", "Remote - United States"]
    assert "- ," not in json.dumps(locations)


def test_configured_company_spelling_wins_over_a_merged_case_variant(conn):
    configured = next(t["name"] for t in CONFIG if t["name"] != t["name"].capitalize() and t["name"].lower() != t["name"])
    mangled = configured.capitalize()
    assert mangled != configured
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM companies WHERE lower(trim(name))=lower(trim(%s))", (configured,))
        existing = cur.fetchone()
        if existing:
            cur.execute("UPDATE companies SET name=%s WHERE id=%s", (mangled, existing[0]))
            company_id = existing[0]
        else:
            cur.execute("INSERT INTO companies(name) VALUES (%s) RETURNING id", (mangled,))
            company_id = cur.fetchone()[0]
        _insert(cur, company_id, "beta-" + uuid4().hex[:10], days_old=0)
    assert sync_canonical_company_names(conn) >= 1
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM companies WHERE id=%s", (company_id,))
        assert cur.fetchone()[0] == configured
        cur.execute("SELECT count(*) FROM job_postings WHERE company_id=%s", (company_id,))
        assert cur.fetchone()[0] >= 1   # relationships are untouched
    assert sync_canonical_company_names(conn) == 0   # idempotent
