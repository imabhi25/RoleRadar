"""30-day PUBLIC visibility window: age hides a job from the public list, never deactivates it."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import Json

from api.database import get_db_connection
from api.main import app
from ingestion.freshness import (
    PUBLIC_VISIBILITY_DAYS,
    get_public_visibility_sql_predicate,
    is_publicly_visible,
)
from ingestion.normalizer import is_user_facing_location_eligible, normalize_job_locations
from tests.test_ingestion_safety import Company

NOW = datetime(2026, 9, 29, 15, 30, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- pure rule

def test_dated_boundaries_on_the_python_mirror():
    cutoff = NOW - timedelta(days=30)
    assert PUBLIC_VISIBILITY_DAYS == 30
    assert is_publicly_visible(cutoff, None, NOW)
    assert not is_publicly_visible(cutoff - timedelta(microseconds=1), None, NOW)
    assert is_publicly_visible(cutoff + timedelta(microseconds=1), None, NOW)
    assert not is_publicly_visible(NOW - timedelta(days=31), NOW, NOW)


def test_toronto_and_utc_midnight_cases():
    toronto = timezone(timedelta(hours=-4))
    for now in (datetime(2026, 9, 29, 23, 59, tzinfo=timezone.utc),
                datetime(2026, 9, 30, 0, 1, tzinfo=timezone.utc)):
        cutoff = now - timedelta(days=30)
        assert is_publicly_visible(cutoff.astimezone(toronto), None, now.astimezone(toronto))
        assert not is_publicly_visible(cutoff - timedelta(seconds=1), None, now)
    # Crossing UTC midnight moves the rolling cutoff two minutes, not a whole day.
    posting = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    assert not is_publicly_visible(posting, None, datetime(2026, 9, 29, 23, 59, tzinfo=timezone.utc))


def test_undated_and_future_dates_are_never_invented_into_fresh_jobs():
    seen = lambda hours: NOW - timedelta(hours=hours)
    # undated: first seen inside the window and still listed recently
    assert is_publicly_visible(None, seen(1), NOW, first_seen_at=NOW - timedelta(days=3))
    assert is_publicly_visible(None, seen(47), NOW, first_seen_at=NOW - timedelta(days=30))
    assert not is_publicly_visible(None, seen(49), NOW, first_seen_at=NOW - timedelta(days=3))     # no longer verified
    assert not is_publicly_visible(None, seen(1), NOW, first_seen_at=NOW - timedelta(days=90))      # old unknown-date job
    assert not is_publicly_visible(None, None, NOW)
    assert not is_publicly_visible(None, seen(1), NOW)  # last seen is not first-seen evidence
    # future dates: tomorrow is tolerated (date-only skew); further ahead is untrusted and treated as undated
    assert is_publicly_visible(NOW + timedelta(hours=20), None, NOW)
    assert not is_publicly_visible(NOW + timedelta(days=10), seen(1), NOW, first_seen_at=NOW - timedelta(days=90))
    assert is_publicly_visible(NOW + timedelta(days=10), seen(1), NOW, first_seen_at=NOW - timedelta(days=2))


def test_sql_predicate_mirrors_the_rule_and_uses_only_job_columns():
    sql = get_public_visibility_sql_predicate("jp")
    assert "INTERVAL '30 days'" in sql and "INTERVAL '48 hours'" in sql and "INTERVAL '2 days'" in sql
    assert "jp.posted_at IS NULL" in sql and "jp.last_seen_at" in sql and "jp.created_at" in sql
    assert "is_active" not in sql          # age never touches source-truth activity


# --------------------------------------------------------------------------- database behaviour

@pytest.fixture
def conn():
    try:
        connection = get_db_connection()
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    yield connection
    connection.rollback()
    connection.close()


@contextmanager
def _api(conn):
    @contextmanager
    def cursor():
        with conn.cursor() as cur:
            yield cur
    with patch("api.main.get_db_cursor", cursor):
        yield TestClient(app)


def _insert(cur, cid, key, days_old=None, seen_hours_ago=1, location="Toronto, ON", role="full_time", title="Software Engineer", workplace="unspecified", created_days_ago=0):
    locs = normalize_job_locations(location)
    primary = next((l for l in locs if is_user_facing_location_eligible(l["location"], l["country"])), locs[0])
    cur.execute("INSERT INTO locations(location,country) VALUES (%s,%s) ON CONFLICT (location,country) DO UPDATE SET country=EXCLUDED.country RETURNING id",
                (primary["location"], primary["country"]))
    lid = cur.fetchone()[0]
    cur.execute("SELECT NOW()")
    posted = None if days_old is None else cur.fetchone()[0] - timedelta(days=days_old)
    cur.execute(
        """INSERT INTO job_postings(job_id,company_id,location_id,title,source_name,source_job_id,source_url,posted_at,is_active,
               description,locations,role_type,workplace_type,last_seen_at,created_at)
           VALUES (%s,%s,%s,%s,'greenhouse',%s,%s,%s,TRUE,'d',%s,%s,%s, NOW() - make_interval(hours => %s), NOW() - make_interval(days => %s))""",
        (key, cid, lid, title, key, "https://example.com/" + key, posted, Json(locs), role, workplace, seen_hours_ago, created_days_ago),
    )


def _company(conn):
    name = "Visible " + uuid4().hex[:10]
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(name) VALUES (%s) RETURNING id", (name,))
        return name, cur.fetchone()[0]


def test_30_day_window_in_the_public_list_with_source_active_rows_kept(conn):
    name, cid = _company(conn)
    cases = {"today": 0, "d29": 29, "d30": 30, "d31": 31, "d270": 270, "future_far": -10}
    with conn.cursor() as cur:
        for key, age in cases.items():
            _insert(cur, cid, name + key, days_old=age)
        _insert(cur, cid, name + "undated_seen", days_old=None, seen_hours_ago=2)          # verified by a sync moments ago
        _insert(cur, cid, name + "undated_stale", days_old=None, seen_hours_ago=24 * 10)   # not seen in a trustworthy sync lately
        _insert(cur, cid, name + "undated_old", days_old=None, seen_hours_ago=2, created_days_ago=90)   # listed now, but first seen long ago
    with _api(conn) as client:
        def ids(**params):
            data = client.get("/api/jobs", params={"company": name, "limit": 100, **params}).json()
            return {j["job_id"][len(name):] for j in data["jobs"]}, data["total"]
        visible, total = ids()
        # dated: today, 29 and exactly 30 days ago; undated: first seen now and listed moments ago; a date 10 days in the
        # future is untrusted, so it is treated as undated (first seen now + listed) rather than shown as "fresh"
        assert visible == {"today", "d29", "d30", "undated_seen", "future_far"} and total == 5
        assert ids(freshness="recent") == (visible, 5) and ids(freshness="30d") == (visible, 5)   # 30d IS the default window
        assert client.get("/api/jobs", params={"freshness": "45d"}).status_code == 400
        everything, all_total = ids(freshness="all")             # unbounded internal/debug view
        assert everything == set(cases) | {"undated_seen", "undated_stale", "undated_old"} and all_total == 9
        assert ids(freshness="14d")[0] == {"today"}          # (future_far is not "posted in the last 14 days")
        assert ids(freshness="week")[0] == {"today"}
        assert client.get("/api/jobs", params={"freshness": "yesterday"}).status_code == 400
        # search, role filter and country filter all run inside the same window
        assert ids(q="Software")[0] == visible
        assert ids(country="Canada")[0] == visible
        assert ids(role_type="full_time")[0] == visible
    # hidden-by-age jobs are still stored and still source-active: age never deactivates anything
    with conn.cursor() as cur:
        cur.execute("SELECT source_job_id, is_active FROM job_postings WHERE company_id=%s", (cid,))
        rows = {r[0][len(name):]: r[1] for r in cur.fetchall()}
    assert rows["d31"] is True and rows["d270"] is True and rows["undated_stale"] is True and rows["undated_old"] is True and len(rows) == 9


def test_every_visible_count_agrees_with_what_can_be_browsed(conn):
    with _api(conn) as client:
        base_overview = client.get("/api/stats/overview").json()["total_postings"]
        base_countries = {c["country"]: c["postings"] for c in client.get("/api/stats/countries").json()}
    name, cid = _company(conn)
    with conn.cursor() as cur:
        for i in range(3):
            _insert(cur, cid, f"{name}fresh{i}", days_old=i + 1)
        for i in range(4):
            _insert(cur, cid, f"{name}old{i}", days_old=100 + i * 50)
    with _api(conn) as client:
        assert client.get("/api/jobs", params={"company": name}).json()["total"] == 3
        assert client.get("/api/stats/overview").json()["total_postings"] - base_overview == 3       # header/stat total
        countries = {c["country"]: c["postings"] for c in client.get("/api/stats/countries").json()}
        assert countries["Canada"] - base_countries.get("Canada", 0) == 3
        company = client.get(f"/api/companies/{name}").json()
        assert company["active_jobs_count"] == 3                                                     # company counts too
        assert name in client.get("/api/jobs/filters").json()["companies"]
    # a company whose only jobs are old disappears from the public filter options
    other, other_id = _company(conn)
    with conn.cursor() as cur:
        _insert(cur, other_id, other + "ancient", days_old=300)
    with _api(conn) as client:
        assert other not in client.get("/api/jobs/filters").json()["companies"]
        assert client.get(f"/api/companies/{other}").json()["active_jobs_count"] == 0
        assert client.get("/api/jobs", params={"company": other}).json()["total"] == 0


def test_recommended_ordering_applies_after_the_freshness_filter(conn):
    name, cid = _company(conn)
    with conn.cursor() as cur:
        _insert(cur, cid, name + "us_new", days_old=2, location="Austin, TX")
        _insert(cur, cid, name + "ca_new", days_old=20, location="Toronto, ON")
        _insert(cur, cid, name + "ca_old", days_old=200, location="Waterloo, ON")        # Canada, but outside the window
        _insert(cur, cid, name + "ca_coop_old", days_old=300, location="Vancouver, BC", role="co_op")
    with _api(conn) as client:
        def order(**params):
            return [j["job_id"][len(name):] for j in client.get("/api/jobs", params={"company": name, "limit": 100, **params}).json()["jobs"]]
        # old Canadian jobs no longer outrank fresh ones: they are simply not listed
        assert order() == ["ca_new", "us_new"]
        # the unbounded view still uses the Canada-first buckets (old Canadian jobs beat the fresh US one)
        assert order(freshness="all") == ["ca_new", "ca_old", "ca_coop_old", "us_new"]
        assert order(sort="newest") == ["us_new", "ca_new"]


def test_multi_location_and_country_filters_still_work_inside_the_window(conn):
    name, cid = _company(conn)
    with conn.cursor() as cur:
        _insert(cur, cid, name + "multi", days_old=5, location="Toronto, ON; Seattle, WA; Remote - Canada")
        _insert(cur, cid, name + "old_multi", days_old=90, location="Vancouver, BC; New York, NY")
    with _api(conn) as client:
        for country in ("Canada", "United States"):
            data = client.get("/api/jobs", params={"company": name, "country": country}).json()
            assert [j["job_id"][len(name):] for j in data["jobs"]] == ["multi"] and len(data["jobs"][0]["locations"]) == 3


# --------------------------------------------------------------------------- source truth is untouched by age

def test_old_active_job_stays_stored_and_ingestion_still_controls_is_active(conn):
    company = Company(conn)
    try:
        ancient = datetime.now(timezone.utc) - timedelta(days=270)
        fresh_job = company.job("fresh", posted_at=datetime.now(timezone.utc) - timedelta(days=3))
        old_job = company.job("old", posted_at=ancient)
        assert company.sync([fresh_job, old_job])["status"] == "success"
        with _api(conn) as client:
            listed = lambda **p: {j["job_id"].split(":", 1)[1][len(company.name):] for j in client.get("/api/jobs", params={"company": company.name, **p}).json()["jobs"]}
            assert listed() == {"fresh"} and listed(freshness="all") == {"fresh", "old"}
            # the employer still lists the old job: it is active in the database but not on the public list
            with conn.cursor() as cur:
                cur.execute("SELECT is_active FROM job_postings WHERE source_job_id=%s", (company.name + "old",))
                assert cur.fetchone() == (True,)
            # the job leaves the official source: normal ingestion deactivates it (row kept, never deleted)
            assert company.sync([fresh_job])["jobs_deactivated"] == 1
            with conn.cursor() as cur:
                cur.execute("SELECT is_active FROM job_postings WHERE source_job_id=%s", (company.name + "old",))
                assert cur.fetchone() == (False,)
            assert listed(freshness="all") == {"fresh"}
            # and it can reactivate when the source lists it again (still hidden from the public list by age)
            assert company.sync([fresh_job, old_job])["jobs_upserted"] == 2
            with conn.cursor() as cur:
                cur.execute("SELECT is_active FROM job_postings WHERE source_job_id=%s", (company.name + "old",))
                assert cur.fetchone() == (True,)
            assert listed() == {"fresh"} and listed(freshness="all") == {"fresh", "old"}
    finally:
        company.cleanup()


def test_country_scoped_overview_matches_the_country_filtered_list(conn):
    """The header count and Market Overview follow the selected country with the exact rule /api/jobs uses."""
    name, cid = _company(conn)
    with conn.cursor() as cur:
        _insert(cur, cid, name + "ca1", days_old=1, location="Toronto, ON")
        _insert(cur, cid, name + "ca2", days_old=2, location="Vancouver, BC")
        _insert(cur, cid, name + "us1", days_old=1, location="New York, NY")
        _insert(cur, cid, name + "multi", days_old=1, location="Toronto, ON; Austin, TX")
        _insert(cur, cid, name + "old_ca", days_old=200, location="Toronto, ON")         # hidden by the 30-day window
    with _api(conn) as client:
        overview = lambda **p: client.get("/api/stats/overview", params=p)
        listing = lambda **p: client.get("/api/jobs", params={"limit": 1, **p}).json()["total"]
        everything = overview().json()["total_postings"]
        for countries in (["Canada"], ["United States"], ["Canada", "United States"]):
            scoped = overview(country=countries)
            assert scoped.status_code == 200
            assert scoped.json()["total_postings"] == listing(country=countries), countries
        ca = overview(country="Canada").json()["total_postings"]
        us = overview(country="United States").json()["total_postings"]
        assert ca <= everything and us <= everything
        # Canada: ca1, ca2, multi (any location counts); United States: us1, multi
        assert client.get("/api/jobs", params={"company": name, "country": "Canada", "limit": 50}).json()["total"] == 3
        assert client.get("/api/jobs", params={"company": name, "country": "United States", "limit": 50}).json()["total"] == 2
        assert overview(country="canada").json()["total_postings"] == ca                # same aliases as /api/jobs
        assert overview(country="Narnia").status_code == 400
        for key in ("total_companies", "total_locations", "total_skills", "recently_posted_postings"):
            assert overview(country="Canada").json()[key] >= 0


def test_country_counts_overlap_for_multi_country_jobs_while_the_headline_stays_unique(conn):
    """A posting located in both countries counts once in the headline and once in EACH country (they may add up to more)."""
    with _api(conn) as client:
        before = client.get("/api/stats/overview").json()["total_postings"]
        before_countries = {c["country"]: c["postings"] for c in client.get("/api/stats/countries").json()}
    name, cid = _company(conn)
    with conn.cursor() as cur:
        _insert(cur, cid, name + "both", days_old=1, location="Toronto, ON; Austin, TX")
        _insert(cur, cid, name + "ca", days_old=1, location="Vancouver, BC")
        _insert(cur, cid, name + "us", days_old=1, location="Seattle, WA")
    with _api(conn) as client:
        overview = client.get("/api/stats/overview").json()["total_postings"]
        countries = {c["country"]: c["postings"] for c in client.get("/api/stats/countries").json()}
        assert overview - before == 3                                                    # unique postings
        assert countries["Canada"] - before_countries.get("Canada", 0) == 2              # both + ca
        assert countries["United States"] - before_countries.get("United States", 0) == 2   # both + us
        added = (countries["Canada"] - before_countries.get("Canada", 0)) + (countries["United States"] - before_countries.get("United States", 0))
        assert added == 4 > overview - before                                            # overlap, by design
        # the same job is returned by both country filters
        for country in ("Canada", "United States"):
            listed = client.get("/api/jobs", params={"company": name, "country": country, "limit": 50}).json()
            assert name + "both" in {j["job_id"] for j in listed["jobs"]}
