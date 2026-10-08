"""Public-data audit: the repair of stored rows and the same rules at ingestion, end to end through PostgreSQL.

* the shared pay rules agree in Python, the ``jobber_pay_ranges`` SQL function and (via the same fixture) the front end;
* a posting ingested tomorrow gets exactly what the backfill gives a posting stored today;
* a company with a verified logo but no website gets its curated official website, and an existing one is never replaced.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from psycopg2.extras import Json

from db.repair_public_data import repair_public_data
from ingestion.company_resolver import _seed_and_audit, known_company_website
from ingestion.compensation import resolve_compensation
from tests.test_ingestion_safety import company, conn  # noqa: F401  (pytest fixtures)
from tests.test_public_visibility import _api

FIX = Path(__file__).parent / "fixtures"
EXAMPLES = json.loads((FIX / "data_audit_pay_examples.json").read_text())
RULES = json.loads((FIX / "pay_rules.json").read_text())["cases"]


def stored_compensation(conn, job_id):
    with conn.cursor() as cur:
        cur.execute("SELECT compensation, pay_ranges FROM job_postings WHERE job_id=%s", (job_id,))
        return cur.fetchone()


# ------------------------------------------------------------------------------------------------ SQL parity
@pytest.mark.parametrize("case", [c for c in RULES if c["interval"]], ids=lambda c: f"{c['min']}-{c['max']}-{c['currency']}-{c['interval']}")
def test_sql_pay_ranges_agree_with_the_shared_rules(conn, case):
    pay = {"min": case["min"], "max": case["max"], "currency": case["currency"], "interval": case["interval"]}
    with conn.cursor() as cur:
        cur.execute("SELECT jobber_pay_ranges(%s::jsonb)", (json.dumps(pay),))
        ranges = cur.fetchone()[0]
    # The SQL function keeps a range exactly when the shared rules call it believable.
    assert bool(ranges) == (case["problem"] is None), (case, ranges)


def test_sql_skips_validated_and_ote_ranges(conn):
    flagged = {"min": 152405, "max": 179300152, "currency": "USD", "interval": "year", "validation": {"status": "above_ceiling"}}
    ote = {"source": "posting_text", "ranges": [{"min": 204000, "max": 348000, "currency": "USD", "interval": "year", "kind": "ote"}]}
    stated = {"source": "posting_text", "ranges": [{"min": 184000, "max": 287500, "currency": "USD", "interval": "year"}, {"min": 10, "max": 20, "symbol": "$"}]}
    with conn.cursor() as cur:
        results = []
        for pay in (flagged, ote, stated):
            cur.execute("SELECT jobber_pay_ranges(%s::jsonb)", (json.dumps(pay),))
            results.append(cur.fetchone()[0])
    assert results[0] == [] and results[1] == []
    assert [(r["min_annual"], r["period"]) for r in results[2]] == [(184000, "year")]       # a range with no currency or period is not filterable


# ------------------------------------------------------------------------------------------------ the same rules at ingestion and in the backfill
def ingest(company, key, example_id, **over):
    example = EXAMPLES[example_id]
    job = company.job(key, title="Software Engineer", compensation=example["compensation"],
                      raw_description=example["description_excerpt"] + "<p>Python and SQL</p>", **over)
    assert company.sync([job])["status"] == "success"
    return job, f"greenhouse:{company.name}{key}"


def test_ingestion_marks_impossible_pay_and_keeps_the_published_figures(company, conn):
    job, job_id = ingest(company, "coinbase", "greenhouse:8177946")
    compensation, pay_ranges = stored_compensation(conn, job_id)
    assert compensation["validation"] == {"status": "above_ceiling"} and compensation["max"] == 179300152.0
    assert pay_ranges == []                               # the salary filter never sees $179,300,152


def test_ingestion_adds_the_ranges_the_posting_states_and_keeps_the_placeholder(company, conn):
    job, job_id = ingest(company, "samsara", "greenhouse:8223645")
    compensation, pay_ranges = stored_compensation(conn, job_id)
    assert compensation["source"] == "posting_text" and compensation["source_structured"]["min"] == 1.0
    assert [(r["min"], r["max"]) for r in compensation["ranges"]] == [(113645.0, 191000.0), (106675.0, 138050.0)]
    assert pay_ranges == []      # bare "$": the currency is not stated, so the amount is shown but never filtered on as USD or CAD


def test_ingestion_takes_the_period_the_posting_states_and_no_other(company, conn):
    job, job_id = ingest(company, "robinhood", "greenhouse:8199744")
    compensation, pay_ranges = stored_compensation(conn, job_id)
    assert compensation["interval"] == "hour" and compensation["interval_source"] == "posting_text"
    assert [(r["currency"], r["min_annual"]) for r in pay_ranges] == [("CAD", 40 * 2080)]
    job, job_id = ingest(company, "reddit", "greenhouse:8250389")
    compensation, pay_ranges = stored_compensation(conn, job_id)
    assert "interval" not in compensation and pay_ranges == []         # no period stated: nothing is annualized or guessed


def test_backfill_gives_stored_rows_what_ingestion_gives_new_ones(company, conn):
    # Rows as production holds them today: the adapter's output, no resolution applied.
    ids = {}
    for key, example_id in (("a", "greenhouse:8177946"), ("b", "greenhouse:8223645"), ("c", "greenhouse:8226602"), ("d", "greenhouse:8199744"),
                            ("e", "workday:Senior-Compute-Platform-Engineer--LSF-_JR2023960"), ("f", "greenhouse:8243997")):
        job, job_id = ingest(company, key, example_id)
        with conn.cursor() as cur:
            cur.execute("UPDATE job_postings SET compensation=%s WHERE job_id=%s", (Json(EXAMPLES[example_id]["compensation"]), job_id))
        ids[key] = (job_id, example_id)
    before = {k: stored_compensation(conn, jid)[0] for k, (jid, _) in ids.items()}
    assert before["b"]["min"] == 1.0 and "validation" not in before["a"]            # the old shapes, as in production

    repair_public_data(conn)
    for key, (job_id, example_id) in ids.items():
        compensation, _ = stored_compensation(conn, job_id)
        with conn.cursor() as cur:
            cur.execute("SELECT description, locations FROM job_postings WHERE job_id=%s", (job_id,))
            html, locations = cur.fetchone()
        assert compensation == json.loads(json.dumps(resolve_compensation(EXAMPLES[example_id]["compensation"], html, locations))), key
    assert stored_compensation(conn, ids["a"][0])[0]["validation"]["status"] == "above_ceiling"
    assert stored_compensation(conn, ids["c"][0])[0]["validation"]["status"] == "below_floor"
    assert stored_compensation(conn, ids["f"][0])[0] == EXAMPLES["greenhouse:8243997"]["compensation"]    # believable pay untouched

    snapshot = {k: stored_compensation(conn, jid)[0] for k, (jid, _) in ids.items()}
    repair_public_data(conn)                                      # idempotent
    assert {k: stored_compensation(conn, jid)[0] for k, (jid, _) in ids.items()} == snapshot


def test_salary_filter_never_returns_a_typo_or_a_placeholder(company, conn):
    ingest(company, "coinbase", "greenhouse:8177946")
    ingest(company, "anthropic", "greenhouse:5428950008")
    ingest(company, "robinhood", "greenhouse:8199744")
    with _api(conn) as client:
        # min $1,000,000 a year: the $179,300,152 typo used to satisfy it
        found = client.get("/api/jobs", params={"company": company.name, "min_compensation": 1_000_000, "compensation_currency": "USD"}).json()
        assert found["total"] == 0
        found = client.get("/api/jobs", params={"company": company.name, "min_compensation": 80_000, "compensation_currency": "CAD"}).json()
        assert [j["job_id"] for j in found["jobs"]] == [f"greenhouse:{company.name}robinhood"]      # $40/hour CAD = $83,200 a year


# ------------------------------------------------------------------------------------------------ company website
def test_braze_gets_its_curated_website_and_other_companies_keep_theirs():
    assert known_company_website("Braze") == known_company_website("Braze, Inc.") == "https://www.braze.com"
    assert known_company_website("Figma") == "https://figma.com"        # from the verified catalog
    assert known_company_website("Unknown Corp") is None
    cur = MagicMock()
    cur.fetchall.return_value = [(332, "Braze", "/api/company-logos/332", "verified", b"png")]    # production: verified logo, website NULL
    cur.fetchone.return_value = (1,)
    _seed_and_audit(cur)
    updates = [c for c in cur.execute.call_args_list if "website_url = %s" in c.args[0] and "website_url IS NULL" in c.args[0]]
    assert [c.args[1] for c in updates] == [("https://www.braze.com", 332)]       # fills a missing website only: the SQL never overwrites one
