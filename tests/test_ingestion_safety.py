"""Ingestion safety: tombstone guard, per-record isolation, partial success, API robustness, search, locations."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import io
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import Json

from api.database import get_db_connection
from api.main import app
from ingestion import cli
from ingestion.base import FetchResult, RawJobPosting
from ingestion.normalizer import normalize_job_locations
from ingestion.pipeline import (
    SOURCE_JOB_ID_MAX,
    TITLE_MAX,
    fit_text,
    normalize_source_job_id,
    sync_company,
)


@pytest.fixture
def conn():
    try:
        connection = get_db_connection()
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    with connection.cursor() as cur:
        cur.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='sync_runs'::regclass AND contype='c'")
        if not any("partial_success" in (r[0] or "") for r in cur.fetchall()):
            pytest.skip("migration 009 not applied to the test database")
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name='sync_runs' AND column_name='snapshot_trustworthy'")
        if not cur.fetchone():
            pytest.skip("migration 010 not applied to the test database")
    yield connection
    connection.rollback()
    connection.close()


class Company:
    """A throwaway company whose syncs run through the real pipeline against PostgreSQL."""

    def __init__(self, conn):
        self.conn = conn
        self.name = "Safety " + uuid4().hex[:10]
        self.config = {"name": self.name, "ats": "greenhouse", "identifier": self.name}

    def job(self, key, title="Software Engineer", **over):
        fields = dict(source_name="greenhouse", source_job_id=self.name + key, company_name=self.name, title=title,
                      raw_location="Remote - Canada", source_url=f"https://example.com/{self.name}{key}",
                      posted_at=datetime.now(timezone.utc) - timedelta(days=1), raw_description="Python and SQL")
        fields.update(over)
        return RawJobPosting(**fields)

    def sync(self, jobs, complete=True, errors=0, total=None):
        adapter = Mock()
        adapter.fetch_jobs.return_value = FetchResult(jobs, errors, complete, len(jobs) if total is None else total)
        with patch("ingestion.pipeline.get_ats_client", return_value=adapter), \
             patch("ingestion.company_resolver._discover_ats_branding", return_value=None):
            return sync_company(self.config, db_conn=self.conn)

    def active(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT source_job_id FROM job_postings WHERE company_id=(SELECT id FROM companies WHERE name=%s) AND is_active",
                        (self.name,))
            return {r[0][len(self.name):] for r in cur.fetchall()}

    def runs(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT status, jobs_fetched, error_message FROM sync_runs WHERE company_identifier=%s ORDER BY id", (self.name,))
            return cur.fetchall()

    def cleanup(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM job_postings WHERE company_id=(SELECT id FROM companies WHERE name=%s)", (self.name,))
            cur.execute("DELETE FROM companies WHERE name=%s", (self.name,))
            cur.execute("DELETE FROM sync_runs WHERE company_identifier=%s", (self.name,))
        self.conn.commit()


@pytest.fixture
def company(conn):
    c = Company(conn)
    yield c
    c.cleanup()


# --------------------------------------------------------------------------- zero-result / mass-drop guard

def test_complete_zero_result_snapshot_does_not_wipe_a_company_and_only_confirmed_shutdown_does(company):
    keys = [f"j{i}" for i in range(12)]
    assert company.sync([company.job(k) for k in keys])["status"] == "success"
    assert company.active() == set(keys)

    for attempt in range(2):
        result = company.sync([])
        assert result["status"] == "partial_success"
        assert result["jobs_deactivated"] == 0
        assert "EMPTY" in result["tombstone_suppressed_reason"] and "12" in result["tombstone_suppressed_reason"]
        assert company.active() == set(keys), f"attempt {attempt}"
    status, fetched, message = company.runs()[-1]
    assert status == "partial_success" and fetched == 0 and "Tombstoning suppressed" in message

    # three consecutive runs agree the board is empty: a genuine shutdown is finally applied
    confirmed = company.sync([])
    assert confirmed["status"] == "success" and confirmed["jobs_deactivated"] == 12
    assert company.active() == set()


def test_a_recovery_between_empty_snapshots_resets_the_confirmation(company):
    keys = [f"j{i}" for i in range(12)]
    company.sync([company.job(k) for k in keys])
    company.sync([])
    company.sync([])
    company.sync([company.job(k) for k in keys])      # the vendor recovered
    result = company.sync([])                          # a fresh outage starts counting again
    assert result["jobs_deactivated"] == 0 and company.active() == set(keys)


def test_large_drop_is_suppressed_until_it_persists_but_normal_changes_apply_at_once(company):
    keys = [f"j{i}" for i in range(20)]
    company.sync([company.job(k) for k in keys])
    # ordinary churn (2 of 20) is applied immediately
    assert company.sync([company.job(k) for k in keys[:18]])["jobs_deactivated"] == 2
    survivors = keys[:5]
    for _ in range(2):
        result = company.sync([company.job(k) for k in survivors])
        assert result["status"] == "partial_success" and result["jobs_deactivated"] == 0
        assert "large drop" in result["tombstone_suppressed_reason"]
        assert company.active() == set(keys[:18])
    persistent = company.sync([company.job(k) for k in survivors])
    assert persistent["status"] == "success" and persistent["jobs_deactivated"] == 13
    assert company.active() == set(survivors)


def test_small_companies_are_not_blocked_by_the_drop_ratio(company):
    company.sync([company.job("a"), company.job("b"), company.job("c")])
    result = company.sync([company.job("a")])
    assert result["status"] == "success" and result["jobs_deactivated"] == 2 and company.active() == {"a"}


def test_incomplete_or_failed_fetches_still_never_tombstone(company):
    keys = [f"j{i}" for i in range(12)]
    company.sync([company.job(k) for k in keys])
    for kwargs in (dict(complete=False), dict(errors=1, total=6), dict(total=9)):
        result = company.sync([company.job(k) for k in keys[:5]], **kwargs)
        assert result["status"] == "partial_success" and result["jobs_deactivated"] == 0
        assert company.active() == set(keys)
    with patch("ingestion.pipeline.get_ats_client") as factory:
        factory.return_value.fetch_jobs.side_effect = RuntimeError("vendor exploded")
        assert sync_company(company.config, db_conn=company.conn)["status"] == "failed"
    assert company.active() == set(keys)


def test_incomplete_snapshot_with_no_usable_rows_is_a_failure_not_partial_success(company):
    result = company.sync([], complete=False)
    assert result["status"] == "failed" and result["jobs_upserted"] == 0


# --------------------------------------------------------------------------- per-record failures

def test_field_helpers_fit_schema_limits():
    long_title = "Senior Software Engineer " + "x" * 400
    fitted = fit_text(long_title, TITLE_MAX)
    assert len(fitted) == TITLE_MAX and fitted.startswith("Senior Software Engineer") and fitted.endswith("…")
    assert fit_text("a\x00b", 10) == "ab" and fit_text(None, 10) == "" and fit_text("short", 10) == "short"
    key = normalize_source_job_id("k" * 500)
    assert len(key) <= SOURCE_JOB_ID_MAX and key == normalize_source_job_id("k" * 500) != normalize_source_job_id("k" * 501)
    assert normalize_source_job_id("plain-id") == "plain-id"


def test_overlong_title_source_id_and_nul_bytes_do_not_abort_the_company(company):
    long_id = company.name + "L" * 400
    jobs = [
        company.job("good1"),
        company.job("long", title="Staff Software Engineer, " + "Platform " * 80, source_job_id=long_id),
        company.job("nul", title="Backend\x00 Engineer", raw_description="desc\x00ription"),
        company.job("good2"),
    ]
    result = company.sync(jobs)
    assert result["status"] == "success" and result["jobs_upserted"] == 4 and result["record_error_count"] == 0
    with company.conn.cursor() as cur:
        cur.execute("SELECT title, source_job_id FROM job_postings WHERE company_id=(SELECT id FROM companies WHERE name=%s)", (company.name,))
        rows = cur.fetchall()
    assert len(rows) == 4
    titles = {t for t, _ in rows}
    assert any(t.startswith("Staff Software Engineer, Platform") and len(t) == TITLE_MAX for t in titles)
    assert "Backend Engineer" in titles
    assert all(len(sid) <= SOURCE_JOB_ID_MAX for _, sid in rows)
    # the hashed identity is stable: syncing again updates in place and keeps the job active
    again = company.sync(jobs)
    assert again["status"] == "success" and again["jobs_deactivated"] == 0
    with company.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM job_postings WHERE company_id=(SELECT id FROM companies WHERE name=%s)", (company.name,))
        assert cur.fetchone()[0] == 4


def test_one_record_failing_database_validation_never_blocks_the_valid_jobs(company):
    good = [company.job("g1"), company.job("g2"), company.job("g3")]
    bad = company.job("bad")
    assert company.sync(good + [company.job("bad"), company.job("gone")])["status"] == "success"
    assert company.active() == {"g1", "g2", "g3", "bad", "gone"}

    bad.posted_at = "definitely not a timestamp"          # PostgreSQL rejects this row only
    result = company.sync(good + [bad, company.job("new")])
    assert result["status"] == "partial_success"
    assert result["record_error_count"] == 1 and "skipped" in result["error_message"]
    # valid rows (including one brand-new job) were saved; the bad one is skipped but still listed by the source
    assert company.active() == {"g1", "g2", "g3", "bad", "new"}
    # tombstoning semantics are unchanged: 'gone' left the complete source listing and was deactivated
    assert result["jobs_deactivated"] == 1 and "gone" not in company.active()
    assert result["jobs_upserted"] == 4


# --------------------------------------------------------------------------- partial success / CLI semantics

def _run_cli(results, argv=("--all",)):
    with patch.object(cli, "load_target_companies", return_value=[{"name": r["company"], "ats": "greenhouse", "identifier": r["company"]} for r in results]), \
         patch.object(cli, "sync_company", side_effect=list(results)):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(list(argv))
    return code, buffer.getvalue()


def _res(name, status, **extra):
    base = {"company": name, "ats": "workday", "status": status, "jobs_fetched": 10, "swe_jobs_accepted": 5,
            "jobs_upserted": 5, "jobs_deactivated": 0, "error_message": None}
    base.update(extra)
    return base


def test_partial_success_keeps_the_scheduled_run_green_but_is_reported():
    code, out = _run_cli([
        _res("Solid", "success"),
        _res("NVIDIA", "partial_success", parse_error_count=3, record_error_count=1,
             error_message="3 malformed source record(s) skipped while parsing."),
    ])
    assert code == 0
    assert "WARNINGS: 1 company sync(s) partially succeeded" in out
    assert "NVIDIA" in out and "parse_errors=3" in out and "record_errors=1" in out
    assert "::warning title=Ingestion partial::NVIDIA" in out


def test_a_genuinely_failed_company_still_fails_the_run():
    code, _ = _run_cli([_res("Solid", "success"), _res("Dead", "failed", error_message="HTTP 500"), _res("Half", "partial_success")])
    assert code == 1


# --------------------------------------------------------------------------- API robustness

@contextmanager
def _api(conn):
    @contextmanager
    def cursor():
        with conn.cursor() as cur:
            yield cur
    with patch("api.main.get_db_cursor", cursor):
        yield TestClient(app)


def test_malformed_inputs_return_client_errors_not_500(conn):
    with _api(conn) as client:
        for params in ({"q": "a\x00b"}, {"search": "x\x00"}, {"company": "c\x00"}, {"skill": "s\x00"}, {"country": "Canada\x00"}):
            assert client.get("/api/jobs", params=params).status_code == 400, params
        assert client.get("/api/jobs/abc%00def").status_code == 400
        assert client.get("/api/companies/abc%00def").status_code == 400
        for offset in (10 ** 12, 10 ** 30, 100_001, -1):
            assert client.get("/api/jobs", params={"offset": offset}).status_code == 422, offset
        assert client.get("/api/jobs", params={"offset": 100_000}).status_code == 200
        assert client.get("/api/jobs", params={"limit": 101}).status_code == 422


def test_invalid_filters_are_rejected_and_valid_aliases_still_work(conn):
    with _api(conn) as client:
        for params in ({"role_type": "astronaut"}, {"role_type": "internship,astronaut"}, {"country": "Narnia"},
                       {"country": "Canada,Narnia"}, {"term": "spring"}, {"term": "summer,bogus"},
                       {"workplace_type": "moon"}, {"workplace_type": "remote,moon"}):
            response = client.get("/api/jobs", params=params)
            assert response.status_code == 400, params
            assert "Must be one of" in response.json()["detail"]
        for params in ({"role_type": "coop,intern,new-grad,fulltime,entry-level,entrylevel"}, {"country": "ca,us,USA,United_States,canada"},
                       {"term": "Winter,SUMMER,fall,autumn"}, {"workplace_type": "onsite,on-site,on_site,remote,hybrid"}):
            assert client.get("/api/jobs", params=params).status_code == 200, params


# --------------------------------------------------------------------------- search

def _insert(cur, cid, key, title, role_type, location="Toronto, ON"):
    loc = normalize_job_locations(location)
    cur.execute("INSERT INTO locations(location,country) VALUES (%s,%s) ON CONFLICT (location,country) DO UPDATE SET country=EXCLUDED.country RETURNING id",
                (loc[0]["location"], loc[0]["country"]))
    cur.execute("""INSERT INTO job_postings(job_id,company_id,location_id,title,source_name,source_job_id,source_url,posted_at,
                       is_active,description,locations,role_type) VALUES (%s,%s,%s,%s,'greenhouse',%s,%s,%s,TRUE,'d',%s,%s)""",
                (key, cid, cur.fetchone()[0], title, key, "https://example.com/" + key, datetime.now(timezone.utc) - timedelta(days=1),
                 Json(loc), role_type))


def test_early_career_search_words_match_role_type_not_just_titles(conn):
    name = "Search " + uuid4().hex[:10]
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(name) VALUES (%s) RETURNING id", (name,))
        cid = cur.fetchone()[0]
        _insert(cur, cid, name + "coop", "Software Developer", "co_op")                # title has no 'co-op'
        _insert(cur, cid, name + "grad", "Software Engineer", "new_grad")               # title has no 'new grad'
        _insert(cur, cid, name + "entry", "Software Engineer", "entry_level")           # title has no 'entry level'
        _insert(cur, cid, name + "coopt", "Software Engineer Co-op", "full_time")       # title-only signal
        _insert(cur, cid, name + "reg", "Software Engineer", "full_time")
    with _api(conn) as client:
        def ids(q):
            data = client.get("/api/jobs", params={"company": name, "q": q, "limit": 100}).json()
            return {j["job_id"][len(name):] for j in data["jobs"]}
        for query in ("coop", "co-op", "co op", "Co-Op", "co-ops"):
            assert ids(query) == {"coop", "coopt"}, query
        for query in ("new grad", "new-grad", "newgrad", "New Graduate"):
            assert ids(query) == {"grad"}, query
        for query in ("entry level", "entry-level", "entrylevel"):
            assert ids(query) == {"entry"}, query
        assert ids("co-op python") == set()          # words still combine with AND
        assert ids("software co-op") == {"coop", "coopt"}


# --------------------------------------------------------------------------- multi-location normalization

def test_mixed_multi_location_labels_are_not_all_remote():
    locations = normalize_job_locations("Toronto, ON; Seattle, WA; Remote - Canada")
    # Plain well-known cities take their canonical shape (published label kept as raw_location); Remote stays Remote.
    assert locations == [
        {"location": "Toronto, Ontario, Canada", "country": "Canada", "raw_location": "Toronto, ON"},
        {"location": "Seattle, WA, United States", "country": "United States", "raw_location": "Seattle, WA"},
        {"location": "Remote - Canada", "country": "Canada"},
    ]
    assert [l["location"] for l in normalize_job_locations("Remote - Canada; Toronto, ON")] == ["Remote - Canada", "Toronto, Ontario, Canada"]
    assert [l["location"] for l in normalize_job_locations("Toronto or Remote")] == ["Toronto, Ontario, Canada", "Remote"]
    # a leading remote still governs its own alternatives
    assert [l["location"] for l in normalize_job_locations("Remote (United States | Canada)")] == ["Remote - United States", "Remote - Canada"]


def test_one_requisition_keeps_all_its_normalized_locations_through_sync_and_api(company):
    result = company.sync([company.job("multi", raw_location="Toronto, ON; Seattle, WA; Remote - Canada")])
    assert result["status"] == "success"
    with company.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*), MAX(jsonb_array_length(locations)) FROM job_postings WHERE company_id=(SELECT id FROM companies WHERE name=%s)", (company.name,))
        assert cur.fetchone() == (1, 3)
        cur.execute("SELECT locations FROM job_postings WHERE company_id=(SELECT id FROM companies WHERE name=%s)", (company.name,))
        stored = cur.fetchone()[0]
    assert [l["location"] for l in stored] == ["Toronto, Ontario, Canada", "Seattle, WA, United States", "Remote - Canada"]
    with _api(company.conn) as client:
        for country in ("Canada", "United States"):
            data = client.get("/api/jobs", params={"company": company.name, "country": country}).json()
            assert data["total"] == 1 and len(data["jobs"][0]["locations"]) == 3


# =========================================================================== tombstone drop threshold

from ingestion.pipeline import is_suspicious_drop, record_failure_is_systemic  # noqa: E402

SUSPICIOUS = [(9, 1), (6, 2), (4, 1), (5, 2), (6, 3), (20, 8), (100, 40)]
ORDINARY = [(3, 2), (3, 1), (5, 3), (10, 7), (100, 95)]


@pytest.mark.parametrize("before,after", SUSPICIOUS)
def test_drop_rule_flags_at_least_three_jobs_and_half_of_active(before, after):
    assert is_suspicious_drop(before, before - after, after)


@pytest.mark.parametrize("before,after", ORDINARY)
def test_drop_rule_leaves_ordinary_churn_alone(before, after):
    assert not is_suspicious_drop(before, before - after, after)


def test_drop_rule_boundaries_and_zero_result():
    assert is_suspicious_drop(6, 3, 3)                  # exactly 50% counts (>=, not >)
    assert not is_suspicious_drop(7, 3, 4)              # 43%
    assert not is_suspicious_drop(4, 2, 2)              # 50% but fewer than 3 jobs
    assert is_suspicious_drop(1, 1, 0) and is_suspicious_drop(2, 2, 0)   # empty listing, any company size
    assert not is_suspicious_drop(0, 0, 0)              # nothing active: nothing to protect
    assert not is_suspicious_drop(50, 0, 50)            # nothing would be deactivated


def _seed_and_shrink(company, before, after):
    keys = [f"j{i}" for i in range(before)]
    assert company.sync([company.job(k) for k in keys])["status"] == "success"
    return keys, company.sync([company.job(k) for k in keys[:after]])


@pytest.mark.parametrize("before,after", SUSPICIOUS)
def test_suspicious_drops_are_suppressed_end_to_end(company, before, after):
    keys, result = _seed_and_shrink(company, before, after)
    assert result["status"] == "partial_success" and result["jobs_deactivated"] == 0
    assert "large drop" in result["tombstone_suppressed_reason"]
    assert company.active() == set(keys)


@pytest.mark.parametrize("before,after", ORDINARY)
def test_ordinary_drops_are_applied_immediately_end_to_end(company, before, after):
    keys, result = _seed_and_shrink(company, before, after)
    assert result["status"] == "success" and result["jobs_deactivated"] == before - after
    assert company.active() == set(keys[:after])


# =========================================================================== systematic record failures

@pytest.mark.parametrize("attempted,failed,expected", [
    (20, 0, False), (20, 1, False), (20, 4, False), (20, 15, False), (20, 16, True), (20, 20, True),
    (5, 4, True), (5, 3, False), (5, 5, True), (1, 1, True), (2, 1, False), (2, 2, True), (4, 3, False), (4, 4, True),
    (10, 7, False), (10, 8, True), (0, 0, False),
])
def test_record_failure_threshold(attempted, failed, expected):
    assert record_failure_is_systemic(attempted, failed) is expected


def _bad_jobs(company, total, bad):
    jobs = []
    for i in range(total):
        job = company.job(f"r{i}")
        if i < bad:
            job.posted_at = "not a timestamp"          # PostgreSQL rejects exactly these rows
        jobs.append(job)
    return jobs


@pytest.mark.parametrize("total,bad,status", [(20, 1, "partial_success"), (20, 4, "partial_success"),
                                              (20, 16, "failed"), (5, 5, "failed"), (1, 1, "failed")])
def test_record_failure_severity_end_to_end(company, total, bad, status):
    # a job the source stops listing: a systemic failure must NOT be allowed to tombstone it
    assert company.sync([company.job("gone")])["status"] == "success"
    result = company.sync(_bad_jobs(company, total, bad))
    assert result["status"] == status
    assert result["record_error_count"] == bad and result["jobs_upserted"] == total - bad
    if status == "failed":
        # systematic failure: no tombstoning at all, the unlisted job stays active
        assert result["jobs_deactivated"] == 0 and "gone" in company.active()
        assert "failed to persist" in result["tombstone_suppressed_reason"]
    else:
        # a few bad rows do not change normal tombstoning: the complete snapshot still retires 'gone'
        assert result["jobs_deactivated"] == 1 and "gone" not in company.active()
    good = {f"r{i}" for i in range(bad, total)}
    assert good <= company.active()                    # the valid rows stay committed either way
    assert company.runs()[-1][0] == status
    assert "skipped" in result["error_message"]


def test_systemic_record_failure_makes_the_scheduled_run_exit_nonzero(company):
    bad = _bad_jobs(company, 5, 5)
    with patch.object(cli, "load_target_companies", return_value=[company.config]), \
         patch.object(cli, "sync_company", side_effect=lambda cfg, dry_run=False: company.sync(bad)):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["--all"])
    assert code == 1


def test_partial_record_failures_keep_the_run_green_with_a_warning(company):
    jobs = _bad_jobs(company, 20, 1)
    with patch.object(cli, "load_target_companies", return_value=[company.config]), \
         patch.object(cli, "sync_company", side_effect=lambda cfg, dry_run=False: company.sync(jobs)):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["--all"])
    assert code == 0 and "record_errors=1" in buffer.getvalue()


# =========================================================================== trustworthy-only, time-bounded confirmation

def _runs_with_trust(company):
    with company.conn.cursor() as cur:
        cur.execute("SELECT status, snapshot_trustworthy FROM sync_runs WHERE company_identifier=%s ORDER BY id", (company.name,))
        return cur.fetchall()


def _age_all_runs(company, hours):
    with company.conn.cursor() as cur:
        cur.execute("""UPDATE sync_runs SET started_at = started_at - make_interval(hours => %s),
                       completed_at = completed_at - make_interval(hours => %s) WHERE company_identifier=%s""",
                    (hours, hours, company.name))


def _twelve(company):
    keys = [f"j{i}" for i in range(12)]
    company.sync([company.job(k) for k in keys])
    return keys


def test_trust_flag_is_stored_per_run(company):
    keys = _twelve(company)
    company.sync([company.job(k) for k in keys[:5]], complete=False)     # incomplete
    company.sync([company.job(k) for k in keys], errors=1, total=13)     # parse-integrity failure
    company.sync([company.job(k) for k in keys])                          # clean
    with patch("ingestion.pipeline.get_ats_client") as factory:
        factory.return_value.fetch_jobs.side_effect = RuntimeError("down")
        sync_company(company.config, db_conn=company.conn)
    assert _runs_with_trust(company) == [("success", True), ("partial_success", False), ("partial_success", False),
                                         ("success", True), ("failed", False)]


def test_incomplete_partial_success_does_not_shorten_confirmation(company):
    keys = _twelve(company)
    survivors = [company.job(k) for k in keys[:3]]
    assert company.sync(survivors)["jobs_deactivated"] == 0                       # suspicious, trusted observation #1
    assert company.sync(survivors, complete=False)["jobs_deactivated"] == 0        # incomplete: untrusted, ignored
    third = company.sync(survivors)
    assert third["jobs_deactivated"] == 0 and company.active() == set(keys)        # only ONE trusted prior so far
    fourth = company.sync(survivors)                                               # priors: third + first, both trusted
    assert fourth["status"] == "success" and fourth["jobs_deactivated"] == 9


def test_partial_success_from_record_failures_alone_can_still_confirm(company):
    keys = _twelve(company)
    survivors = [company.job(k) for k in keys[:3]]
    survivors[0].posted_at = "not a timestamp"          # one record cannot be saved; the SOURCE snapshot is complete
    for _ in range(2):
        result = company.sync(survivors)
        assert result["status"] == "partial_success" and result["jobs_deactivated"] == 0
    assert [t for _, t in _runs_with_trust(company)][-2:] == [True, True]
    clean = company.sync([company.job(k) for k in keys[:3]])
    assert clean["status"] == "success" and clean["jobs_deactivated"] == 9


def test_failed_runs_never_count_as_confirmation(company):
    keys = _twelve(company)
    survivors = [company.job(k) for k in keys[:3]]
    company.sync(survivors)                                             # trusted observation #1
    with patch("ingestion.pipeline.get_ats_client") as factory:
        factory.return_value.fetch_jobs.side_effect = RuntimeError("timeout")
        assert sync_company(company.config, db_conn=company.conn)["status"] == "failed"
    assert company.sync(survivors)["jobs_deactivated"] == 0             # failed run ignored: still only 1 prior
    assert company.sync(survivors)["jobs_deactivated"] == 9             # now 2 trusted priors


def test_stale_observations_cannot_confirm_a_new_drop_but_scheduled_ones_can(company):
    keys = _twelve(company)
    survivors = [company.job(k) for k in keys[:3]]
    company.sync(survivors)
    company.sync(survivors)
    _age_all_runs(company, 48)                                           # process was down for two days
    stale = company.sync(survivors)
    assert stale["jobs_deactivated"] == 0 and company.active() == set(keys)
    assert "large drop" in stale["tombstone_suppressed_reason"]
    # a further ordinary schedule (~6h apart) rebuilds confirmation from fresh observations
    company.sync(survivors)
    assert company.sync(survivors)["jobs_deactivated"] == 9


def test_confirmation_uses_the_24_hour_window_with_scheduling_slack(company):
    keys = _twelve(company)
    survivors = [company.job(k) for k in keys[:3]]
    company.sync(survivors)
    company.sync(survivors)
    _age_all_runs(company, 13)                                           # ~2 missed/late 6-hourly runs: still inside 24h
    assert company.sync(survivors)["jobs_deactivated"] == 9


def test_history_from_before_migration_010_never_confirms(company):
    keys = _twelve(company)
    survivors = [company.job(k) for k in keys[:3]]
    company.sync(survivors)
    company.sync(survivors)
    with company.conn.cursor() as cur:                                   # rows written before the column existed default to FALSE
        cur.execute("UPDATE sync_runs SET snapshot_trustworthy = FALSE WHERE company_identifier=%s", (company.name,))
    assert company.sync(survivors)["jobs_deactivated"] == 0
