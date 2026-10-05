"""Early-career classification, academic terms and Canada-first behaviour."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import Json

from api.database import get_db_connection
from api.main import app
from ingestion.normalizer import (
    classify_role_type,
    extract_academic_term,
    is_swe_role,
    is_user_facing_location_eligible,
    job_has_canada_location,
    normalize_job_locations,
)


@pytest.fixture
def conn():
    try:
        connection = get_db_connection()
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name='job_postings' AND column_name='term_season'")
        if not cur.fetchone():
            pytest.skip("migration 008 not applied to the test database")
    yield connection
    connection.rollback()
    connection.close()


# --------------------------------------------------------------------------- classification

@pytest.mark.parametrize("title", [
    "Software Developer Co-op", "Software Engineering Co-op", "4 month co-op - Software Developer",
    "8 Month Co-op Software Engineer", "12 month co-op, Software Developer", "Co-op Software Developer (Winter 2027)",
])
def test_canadian_coop_titles(title):
    assert is_swe_role(title)
    assert classify_role_type(title) == "co_op"


@pytest.mark.parametrize("title", [
    "Software Developer Intern", "Software Engineering Intern", "Winter Intern - Software Engineer",
    "Summer Intern, Software Developer", "Fall Intern Software Engineer", "Student Developer",
    "Student Software Engineer", "Student, Software Engineering", "Developer Student",
    "Software Development Engineer Intern",
])
def test_internship_and_student_titles(title):
    assert is_swe_role(title)
    assert classify_role_type(title) == "internship"


@pytest.mark.parametrize("title", [
    "New Graduate Software Engineer", "Software Engineer, New Grad", "Recent Graduate Software Developer",
    "University Graduate Software Developer", "Early Career Software Engineer", "Campus Hire Software Engineer",
])
def test_new_grad_titles(title):
    assert is_swe_role(title)
    assert classify_role_type(title) == "new_grad"


@pytest.mark.parametrize("title", ["Entry Level Software Developer", "Entry-Level Software Engineer", "Junior Software Developer"])
def test_entry_level_titles(title):
    assert is_swe_role(title)
    assert classify_role_type(title) == "entry_level"


def test_regular_and_senior_roles_stay_full_time():
    assert classify_role_type("Software Engineer") == "full_time"
    assert classify_role_type("Senior Software Engineer") == "full_time"
    assert classify_role_type("Internal Tools Software Engineer") == "full_time"  # 'Internal' is not 'Intern'


def test_structured_job_type_marks_early_career_only_when_title_is_silent():
    assert classify_role_type("Software Engineer", raw_job_type="Intern") == "internship"
    assert classify_role_type("Software Engineer", raw_job_type="Co-op") == "co_op"
    assert classify_role_type("Senior Software Engineer", raw_job_type="Intern") == "full_time"
    # A description that merely mentions internships must not promote a full-time role.
    assert classify_role_type("Software Engineer", "We also run an internship program.") == "full_time"


@pytest.mark.parametrize("title", [
    "Finance Intern", "Marketing Intern", "Business Analyst Intern", "Recruiting Intern", "Financial Analyst Co-op",
    "Business Co-op", "Human Resources Intern", "Sales Development Intern", "Data Analyst Intern - Marketing",
    "Product Manager Intern", "Talent Acquisition Co-op", "Software Engineering Recruiting Intern",
])
def test_non_swe_early_career_titles_are_rejected(title):
    assert not is_swe_role(title)


def test_engineering_student_needs_software_evidence_in_description():
    assert not is_swe_role("Engineering Student")
    assert not is_swe_role("Engineering Student", "Assist with CAD drawings and site visits.")
    assert is_swe_role("Engineering Student", "Write Python and Java software, use git, learn algorithms and APIs.")
    assert classify_role_type("Engineering Student") == "internship"


# --------------------------------------------------------------------------- academic terms

@pytest.mark.parametrize("title,expected", [
    ("Software Engineering Intern - Summer 2027", "Summer 2027"),
    ("Winter 2027 Software Developer Co-op", "Winter 2027"),
    ("Software Intern (Fall 2026)", "Fall 2026"),
    ("2027 Summer Software Intern", "Summer 2027"),
    ("Software Intern, Fall '26", "Fall 2026"),
    ("Autumn 2026 Software Co-op", "Fall 2026"),
])
def test_academic_term_from_title(title, expected):
    assert extract_academic_term(title)["label"] == expected


@pytest.mark.parametrize("title", [
    "Software Developer Intern", "Software Intern Spring 2027", "Fall/Winter 2027 Software Intern",
    "Summer 2027 or Fall 2027 Software Intern", "Software Engineer", "Summer Intern",
])
def test_unknown_term_is_never_inferred(title):
    assert extract_academic_term(title) is None


def test_term_priority_structured_then_title_then_description():
    assert extract_academic_term("Software Intern - Summer 2027", structured_terms=["Fall 2026"])["label"] == "Fall 2026"
    assert extract_academic_term("Software Intern", structured_terms=["N/A"]) is None
    # Description is a last resort, early-career roles only, and only when unambiguous.
    desc = "This internship runs Summer 2027 in Toronto."
    assert extract_academic_term("Software Intern", description=desc, role_type="internship")["label"] == "Summer 2027"
    assert extract_academic_term("Software Engineer", description=desc, role_type="full_time") is None
    assert extract_academic_term("Software Intern", description="Summer 2027 or Fall 2027", role_type="internship") is None
    # Title wins over a conflicting description
    assert extract_academic_term("Software Intern - Winter 2027", description=desc, role_type="internship")["label"] == "Winter 2027"


# --------------------------------------------------------------------------- Canada matching

CANADA_LOCATIONS = [
    "Toronto, ON", "Waterloo, ON", "Vancouver, BC", "Montréal, QC", "Ottawa, ON", "Calgary, AB", "Canada",
    "Remote - Canada", "Canada Remote", "Remote (Canada)", "United States / Canada", "Toronto / New York",
    "Vancouver / Seattle",
]


@pytest.mark.parametrize("label", CANADA_LOCATIONS)
def test_every_canadian_location_shape_matches_canada(label):
    locations = normalize_job_locations(label)
    assert job_has_canada_location(locations)
    assert any(l["country"] == "Canada" and is_user_facing_location_eligible(l["location"], l["country"]) for l in locations)


def _insert_job(cur, cid, key, title, locations, role_type="full_time", workplace="unspecified",
                days_old=1, source="greenhouse", term=(None, None)):
    """Insert a job the way the pipeline would (primary = first eligible location)."""
    normalized = normalize_job_locations(locations) if isinstance(locations, str) else locations
    primary = next((l for l in normalized if is_user_facing_location_eligible(l["location"], l["country"])), normalized[0])
    cur.execute("INSERT INTO locations(location,country) VALUES (%s,%s) ON CONFLICT (location,country) DO UPDATE SET country=EXCLUDED.country RETURNING id",
                (primary["location"], primary["country"]))
    lid = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO job_postings(job_id,company_id,location_id,title,source_name,source_job_id,source_url,
               posted_at,is_active,description,locations,role_type,workplace_type,term_season,term_year)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE,'desc',%s,%s,%s,%s,%s)""",
        (key, cid, lid, title, source, key, f"https://example.com/{key}",
         datetime.now(timezone.utc) - timedelta(days=days_old), Json(normalized), role_type, workplace, term[0], term[1]),
    )


@contextmanager
def _api(conn):
    @contextmanager
    def cursor():
        with conn.cursor() as cur:
            yield cur
    with patch("api.main.get_db_cursor", cursor):
        yield TestClient(app)


def _company(conn):
    name = "CanadaFirst " + uuid4().hex[:12]
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(name) VALUES (%s) RETURNING id", (name,))
        return name, cur.fetchone()[0]


def test_canada_first_default_ranking_and_explicit_sort_override(conn):
    name, cid = _company(conn)
    with conn.cursor() as cur:
        # (key, title, location, role, workplace, days_old)
        rows = [
            ("us_regular", "Software Engineer", "San Francisco, CA", "full_time", "unspecified", 1),
            ("us_early", "Software Engineer Intern", "New York, NY", "internship", "unspecified", 4),
            ("us_remote", "Software Engineer", "Remote - United States", "full_time", "remote", 5),
            ("ca_old_regular", "Software Engineer", "Waterloo, ON", "full_time", "unspecified", 200),
            ("ca_old_early", "Software Developer Co-op", "Vancouver, BC", "co_op", "unspecified", 400),
            ("ca_early_50d", "Software Developer Intern", "Ottawa, ON", "internship", "unspecified", 50),
            ("ca_regular_50d", "Software Engineer", "Calgary, AB", "full_time", "unspecified", 51),
            ("ca_20d", "Software Engineer", "Toronto, ON", "full_time", "unspecified", 20),
            ("ca_multi_3d", "Software Engineer", "Seattle, WA / Toronto, ON", "full_time", "unspecified", 3),
            ("ca_1d", "Software Engineer", "Montréal, QC", "full_time", "unspecified", 2),
        ]
        for key, title, loc, role, wp, days in rows:
            _insert_job(cur, cid, name + key, title, loc, role, wp, days_old=days)
        # unknown posting date: never hidden, ranks by the bucket it falls into
        _insert_job(cur, cid, name + "ca_undated", "Software Engineer", "Toronto, ON", days_old=0)
        cur.execute("UPDATE job_postings SET posted_at = NULL WHERE job_id = %s", (name + "ca_undated",))
    expected = ["ca_1d", "ca_multi_3d",            # 1: Canada <= 7 days
                "ca_20d",                          # 2: Canada <= 30 days
                "ca_early_50d",                    # 3: Canada early-career <= 60 days
                "ca_regular_50d", "ca_old_regular", "ca_old_early", "ca_undated",  # 4: other Canada (posted_at DESC NULLS LAST)
                "us_remote", "us_early", "us_regular"]
    with _api(conn) as client:
        def ids(**params):
            return [j["job_id"][len(name):] for j in client.get("/api/jobs", params={"company": name, "limit": 100, "freshness": "all", **params}).json()["jobs"]]
        assert ids() == expected
        assert ids(sort="recommended") == expected
        # the unbounded debug view hides nothing because of age (the public default window is tested in test_public_visibility.py)
        assert len(ids()) == len(rows) + 1
        # explicit sorts are unchanged
        newest = ids(sort="newest")
        assert [r[0] for r in sorted(rows, key=lambda r: r[5])] == [k for k in newest if k != "ca_undated"]
        assert ids(sort="oldest")[:len(rows)] == [k for k in newest if k != "ca_undated"][::-1]
        titles = [j["title"] for j in client.get("/api/jobs", params={"company": name, "sort": "title", "limit": 100, "freshness": "all"}).json()["jobs"]]
        assert titles == sorted(titles, key=str.lower)
        companies = client.get("/api/jobs", params={"company": name, "sort": "company", "freshness": "all"}).json()
        assert companies["total"] == len(rows) + 1
        # old official jobs stay searchable
        assert client.get("/api/jobs", params={"company": name, "q": "co-op", "freshness": "all"}).json()["total"] >= 1


def test_canada_filter_matches_any_location_and_remote_shapes(conn):
    name, cid = _company(conn)
    with conn.cursor() as cur:
        for i, label in enumerate(CANADA_LOCATIONS):
            _insert_job(cur, cid, f"{name}ca{i}", f"Software Engineer {i}", label)
        _insert_job(cur, cid, name + "us_only", "Software Engineer US", "Austin, TX")
        _insert_job(cur, cid, name + "uk_and_ca", "Software Engineer UK", "London, UK / Remote - Canada")
    with _api(conn) as client:
        data = client.get("/api/jobs", params={"company": name, "country": "Canada", "limit": 100}).json()
        ids = {j["job_id"] for j in data["jobs"]}
        assert ids == {f"{name}ca{i}" for i in range(len(CANADA_LOCATIONS))} | {name + "uk_and_ca"}
        us = client.get("/api/jobs", params={"company": name, "country": "United States", "limit": 100}).json()
        us_ids = {j["job_id"] for j in us["jobs"]}
        assert name + "us_only" in us_ids
        # multi-location jobs appear under BOTH countries
        assert {name + "ca10", name + "ca11", name + "ca12"} <= us_ids  # 'US / Canada', 'Toronto / New York', 'Vancouver / Seattle'


def test_new_role_and_term_filters(conn):
    name, cid = _company(conn)
    with conn.cursor() as cur:
        _insert_job(cur, cid, name + "a", "Software Engineering Intern - Summer 2027", "Toronto, ON", "internship", term=("summer", 2027))
        _insert_job(cur, cid, name + "b", "Winter 2027 Software Developer Co-op", "Toronto, ON", "co_op", term=("winter", 2027))
        _insert_job(cur, cid, name + "c", "Entry Level Software Developer", "Ottawa, ON", "entry_level")
        _insert_job(cur, cid, name + "d", "Software Developer Intern", "Toronto, ON", "internship")
        _insert_job(cur, cid, name + "e", "Software Engineer", "Toronto, ON", "full_time")
    with _api(conn) as client:
        def ids(**params):
            return {j["job_id"][len(name):] for j in client.get("/api/jobs", params={"company": name, **params}).json()["jobs"]}
        assert ids(term="summer") == {"a"}
        assert ids(term="winter,summer") == {"a", "b"}
        assert ids(term="fall") == set()
        assert ids(role_type="entry_level") == {"c"}
        assert ids(role_type="entry-level") == {"c"}
        assert ids(role_type="internship", term="summer") == {"a"}
        for bad in ({"term": "bogus"}, {"role_type": "nonsense"}, {"country": "Narnia"}, {"workplace_type": "moon"}):
            assert client.get("/api/jobs", params={"company": name, **bad}).status_code == 400   # rejected, not ignored
        assert ids(term="autumn") == set()   # accepted alias for fall
        job = client.get("/api/jobs", params={"company": name, "term": "summer"}).json()["jobs"][0]
        assert (job["term_season"], job["term_year"], job["academic_term"]) == ("summer", 2027, "Summer 2027")
        unknown = client.get("/api/jobs/" + name + "d").json()
        assert unknown["academic_term"] is None and unknown["term_season"] is None
        assert client.get("/api/jobs/" + name + "a").json()["academic_term"] == "Summer 2027"


def test_workday_and_amazon_sources_are_public_but_unknown_sources_are_not(conn):
    name, cid = _company(conn)
    with conn.cursor() as cur:
        for src in ("workday", "amazon", "greenhouse", "jobicy"):
            _insert_job(cur, cid, f"{name}{src}", f"Software Engineer {src}", "Toronto, ON", source=src)
    with _api(conn) as client:
        ids = {j["source_name"] for j in client.get("/api/jobs", params={"company": name}).json()["jobs"]}
        assert ids == {"workday", "amazon", "greenhouse"}


def test_similar_requisitions_from_one_company_are_not_merged(conn):
    """Same company/title/location/description but different requisitions must all stay visible."""
    name, cid = _company(conn)
    with conn.cursor() as cur:
        for i in range(3):
            _insert_job(cur, cid, f"{name}req{i}", "Software Developer", "Toronto, ON", source="workday")
    with _api(conn) as client:
        assert client.get("/api/jobs", params={"company": name}).json()["total"] == 3


@pytest.mark.parametrize("title,expected", [
    ("Summer Intern 2027 - Software Engineering (12 Months)", "Summer 2027"),
    ("Fall Co-op 2026 - Software Developer", "Fall 2026"),
    ("Winter Internship 2027, Software Engineer", "Winter 2027"),
])
def test_term_with_role_word_between_season_and_year(title, expected):
    assert extract_academic_term(title)["label"] == expected


def test_summer_or_winter_without_a_year_stays_unknown():
    assert extract_academic_term("Software Engineer, Intern (Summer or Winter)") is None


def test_experience_rank_does_not_treat_associate_directors_as_entry_level(conn):
    """Exercise the actual PostgreSQL predicates, including incorrectly labelled historical rows."""
    name, cid = _company(conn)
    rows = [
        ("director", "Associate Director DevOps", "full_time"),
        ("old_metadata", "Associate Director Software Engineering", "entry_level"),
        ("associate", "Associate Platform Engineer", "full_time"),
        ("senior", "Senior Software Engineer", "full_time"),
        ("manager", "Engineering Manager", "full_time"),
        ("junior", "Junior Software Engineer", "full_time"),
        ("grad", "Software Engineer New Grad", "new_grad"),
        ("intern", "Software Engineer Intern", "internship"),
    ]
    with conn.cursor() as cur:
        for key, title, role in rows:
            _insert_job(cur, cid, name + key, title, "Toronto, ON", role_type=role)
    with _api(conn) as client:
        def ids(level):
            result = client.get("/api/jobs", params={"company": name, "experience_level": level, "limit": 100})
            assert result.status_code == 200
            return {j["job_id"][len(name):] for j in result.json()["jobs"]}
        assert ids("entry") == {"junior", "grad"}
        assert ids("senior") == {"director", "old_metadata", "senior", "manager"}
        assert ids("mid") == set()  # An unranked Associate title alone does not prove mid-level.
        assert ids("internship") == {"intern"}
        assert ids("entry,senior") == {"junior", "grad", "director", "old_metadata", "senior", "manager"}
