"""Tests for regional Canadian metro location matching, experience-level, minimum-compensation, and sponsorship filters."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from api.main import app, resolve_metro_regex, CANADIAN_METROS
from tests.test_public_visibility import conn  # noqa: F401  (pytest fixture)

client = TestClient(app)


def test_canadian_metro_definitions():
    """Verify regex patterns for all defined Canadian metros."""
    assert resolve_metro_regex("toronto") is not None
    assert resolve_metro_regex("Toronto (GTA)") is not None
    assert resolve_metro_regex("GTA") is not None
    assert resolve_metro_regex("vancouver") is not None
    assert resolve_metro_regex("montreal") is not None
    assert resolve_metro_regex("ottawa") is not None
    assert resolve_metro_regex("waterloo") is not None
    assert resolve_metro_regex("calgary") is not None
    assert resolve_metro_regex("edmonton") is not None
    assert resolve_metro_regex("San Francisco") is None


def test_filter_options_include_experience_levels():
    """/api/jobs/filters always describes the four experience levels."""
    response = client.get("/api/jobs/filters")
    assert response.status_code == 200
    assert set(response.json()["experience_levels"]) == {"internship", "entry", "mid", "senior"}


def test_location_options_follow_the_public_results_population(conn):
    """A metro is offered only if the public list would return a job for it (same population, same matching)."""
    from tests.test_public_visibility import _api, _company, _insert
    name, cid = _company(conn)

    def offered(client):
        return client.get("/api/jobs/filters").json()["locations"]

    with _api(conn) as client:
        before = offered(client)
        assert "Edmonton" not in before          # nothing public in Edmonton: no dead-end option
    with conn.cursor() as cur:
        _insert(cur, cid, name + "edm", days_old=0, location="Edmonton, AB")
        _insert(cur, cid, name + "old", days_old=45, location="Calgary, AB")            # outside the 30-day public window
        _insert(cur, cid, name + "gone", days_old=0, location="Ottawa, ON")
        cur.execute("UPDATE job_postings SET is_active=FALSE WHERE job_id=%s", (name + "gone",))   # closed at the source
    with _api(conn) as client:
        after = offered(client)
        assert "Edmonton" in after
        # hidden-by-age and inactive jobs never make an option appear (unless real public jobs exist for it)
        assert ("Calgary" in after) == ("Calgary" in before)
        assert ("Ottawa" in after) == ("Ottawa" in before)
        # The promise: every offered option returns results from the list endpoint.
        for label in after:
            total = client.get("/api/jobs", params={"location": label, "limit": 1}).json()["total"]
            assert total > 0, f"{label} is offered but the list returns nothing"
        assert client.get("/api/jobs", params={"location": "Edmonton", "company": name}).json()["total"] == 1


@patch("api.main.get_db_cursor")
def test_location_filter_canadian_metro_sql(mock_get_db):
    """Regional Toronto search includes GTA regex matching both l.location and jp.locations with country='Canada'."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (10,)
    mock_cur.fetchall.return_value = []
    mock_get_db.return_value.__enter__.return_value = mock_cur

    response = client.get("/api/jobs?location=Toronto%20(GTA)")
    assert response.status_code == 200

    count_query, params = mock_cur.execute.call_args_list[0][0]
    assert "l.country = 'Canada' AND l.location ~* %s" in count_query
    assert "jl.country = 'Canada' AND jl.location ~* %s" in count_query
    assert any("mississauga" in str(p) for p in params)


def test_toronto_metro_regex_excludes_new_york():
    """Toronto metro regex matches GTA cities and York, but strictly excludes New York."""
    import re
    toronto_pattern = CANADIAN_METROS["toronto"]
    # Replaces postgres \y with python \b for unit verification
    py_pattern = toronto_pattern.replace(r"\y", r"\b")

    # Positive matches
    for pos in ["Toronto, ON", "York, ON", "North York, ON", "East York, ON", "Mississauga, ON", "Markham, ON"]:
        assert re.search(py_pattern, pos, re.IGNORECASE) is not None, f"Expected {pos} to match"

    # Negative matches
    for neg in ["New York, NY", "New York", "new york, ny", "New York City"]:
        assert re.search(py_pattern, neg, re.IGNORECASE) is None, f"Expected {neg} to NOT match"


@patch("api.main.get_db_cursor")
def test_experience_level_filter_sql(mock_get_db):
    """Experience-level filters construct correct role_type and title regex predicates."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (5,)
    mock_cur.fetchall.return_value = []
    mock_get_db.return_value.__enter__.return_value = mock_cur

    for level in ('senior', 'entry', 'internship'):
        mock_cur.reset_mock()
        response = client.get('/api/jobs', params={'experience_level':level})
        assert response.status_code == 200
        query, params = mock_cur.execute.call_args_list[0][0]
        assert 'jp.experience_level = ANY(%s)' in query
        assert [level] in params


@patch("api.main.get_db_cursor")
def test_min_compensation_filter_sql(mock_get_db):
    """Min compensation checks both summaryComponents and compensationTiers with normalized periods and explicit currency."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (3,)
    mock_cur.fetchall.return_value = []
    mock_get_db.return_value.__enter__.return_value = mock_cur

    response = client.get("/api/jobs?min_compensation=120000&compensation_currency=CAD")
    assert response.status_code == 200

    query, params = mock_cur.execute.call_args_list[0][0]
    assert 'jsonb_to_recordset(jp.pay_ranges)' in query
    assert 'pay.max_annual >= %s AND pay.currency = %s' in query
    assert 120000 in params
    assert "CAD" in params


@patch("api.main.get_db_cursor")
def test_min_compensation_currency_inference(mock_get_db):
    """Min compensation infers CAD for country=Canada and USD for country=United States."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (2,)
    mock_cur.fetchall.return_value = []
    mock_get_db.return_value.__enter__.return_value = mock_cur

    # Canada -> CAD
    res_ca = client.get("/api/jobs?min_compensation=100000&country=Canada")
    assert res_ca.status_code == 200
    _, params_ca = mock_cur.execute.call_args_list[0][0]
    assert "CAD" in params_ca

    # United States -> USD
    mock_cur.reset_mock()
    res_us = client.get("/api/jobs?min_compensation=100000&country=United%20States")
    assert res_us.status_code == 200
    _, params_us = mock_cur.execute.call_args_list[0][0]
    assert "USD" in params_us


def test_min_compensation_requires_currency_or_country():
    """Min compensation without currency or single country returns 400 Bad Request."""
    res = client.get("/api/jobs?min_compensation=100000")
    assert res.status_code == 400
    assert "compensation_currency" in res.json()["detail"]


@patch("api.main.get_db_cursor")
def test_location_commas_preserved_and_us_metros_sql(mock_get_db):
    """Preserve commas inside location values and resolve US metro regional queries."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (5,)
    mock_cur.fetchall.return_value = []
    mock_get_db.return_value.__enter__.return_value = mock_cur

    # 1. San Francisco, CA individually
    res_sf = client.get("/api/jobs?location=San%20Francisco%2C%20CA")
    assert res_sf.status_code == 200
    query_sf, params_sf = mock_cur.execute.call_args_list[0][0]
    assert "l.country = 'United States' AND l.location ~* %s" in query_sf
    assert any("san francisco" in str(p) for p in params_sf)

    # 2. New York, NY individually
    mock_cur.reset_mock()
    res_ny = client.get("/api/jobs?location=New%20York%2C%20NY")
    assert res_ny.status_code == 200
    query_ny, params_ny = mock_cur.execute.call_args_list[0][0]
    assert "l.country = 'United States' AND l.location ~* %s" in query_ny
    assert any("new york" in str(p) for p in params_ny)

    # 3. Together with repeated parameters
    mock_cur.reset_mock()
    res_both = client.get("/api/jobs?location=San%20Francisco%2C%20CA&location=New%20York%2C%20NY")
    assert res_both.status_code == 200
    query_both, params_both = mock_cur.execute.call_args_list[0][0]
    assert any("san francisco" in str(p) for p in params_both)
    assert any("new york" in str(p) for p in params_both)
    # Both US metro clauses are combined with OR
    assert " OR " in query_both


@patch("api.main.get_db_cursor")
def test_sponsorship_filter_sql(mock_get_db):
    """Sponsorship filter applies negation-aware matching and country-specific preservation."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (1,)
    mock_cur.fetchall.return_value = []
    mock_get_db.return_value.__enter__.return_value = mock_cur

    # Sponsorship available requires positive match AND negation exclusion
    response = client.get("/api/jobs?sponsorship=available")
    assert response.status_code == 200
    query, params = mock_cur.execute.call_args_list[0][0]
    assert "(jp.description ~* %s AND jp.description !~* %s)" in query
    assert any("visa sponsorship" in str(p) for p in params)

    # Sponsorship not required with Canada country filter
    mock_cur.reset_mock()
    response_ca = client.get("/api/jobs?sponsorship=not_required&country=Canada")
    assert response_ca.status_code == 200
    query_ca, params_ca = mock_cur.execute.call_args_list[0][0]
    assert any("canada" in str(p) for p in params_ca)

    # Sponsorship not required with US country filter
    mock_cur.reset_mock()
    response_us = client.get("/api/jobs?sponsorship=not_required&country=United%20States")
    assert response_us.status_code == 200
    query_us, params_us = mock_cur.execute.call_args_list[0][0]
    assert any("u\\.?s\\.?" in str(p) or "united states" in str(p) for p in params_us)


def test_sponsorship_classification_behavior():
    """Behavioral tests verifying negation-awareness, unknown defaults, and country requirements."""
    import re
    from api.main import (
        POSITIVE_SPONSORSHIP_REGEX,
        NEGATION_SPONSORSHIP_REGEX,
        GENERAL_NOT_REQUIRED_REGEX,
        CANADA_NOT_REQUIRED_REGEX,
        US_NOT_REQUIRED_REGEX,
    )

    pos_re = re.compile(POSITIVE_SPONSORSHIP_REGEX.replace(r"\y", r"\b"), re.I)
    neg_re = re.compile(NEGATION_SPONSORSHIP_REGEX.replace(r"\y", r"\b"), re.I)
    gen_re = re.compile(GENERAL_NOT_REQUIRED_REGEX.replace(r"\y", r"\b"), re.I)
    can_re = re.compile(CANADA_NOT_REQUIRED_REGEX.replace(r"\y", r"\b"), re.I)
    us_re = re.compile(US_NOT_REQUIRED_REGEX.replace(r"\y", r"\b"), re.I)

    def is_available(text: str) -> bool:
        return bool(pos_re.search(text)) and not bool(neg_re.search(text))

    def is_not_required(text: str, country: str = "all") -> bool:
        if country == "Canada":
            return bool(gen_re.search(text)) or bool(can_re.search(text))
        if country == "United States":
            return bool(gen_re.search(text)) or bool(us_re.search(text))
        return bool(gen_re.search(text)) or bool(can_re.search(text)) or bool(us_re.search(text))

    # 1. "We do not offer visa sponsorship" must NEVER match available
    no_offer = "We do not offer visa sponsorship for this role."
    assert not is_available(no_offer)
    assert is_not_required(no_offer)

    # 2. "Must be legally authorized to work" alone must remain unknown
    work_alone_us = "Must be legally authorized to work in the United States."
    work_alone_ca = "Must be legally authorized to work in Canada."
    work_alone_gen = "Candidates must be legally authorized to work."
    for s in [work_alone_us, work_alone_ca, work_alone_gen]:
        assert not is_available(s), f"{s} should not match available"
        assert not is_not_required(s), f"{s} should not match not_required (must remain unknown)"

    # 3. Explicit positive sponsorship
    positive_offer = "Visa sponsorship is available for qualified applicants."
    will_sponsor = "We will sponsor work visas for this position."
    for s in [positive_offer, will_sponsor]:
        assert is_available(s), f"{s} should match available"
        assert not is_not_required(s), f"{s} should not match not_required"

    # 4. Country-specific without sponsorship requirements
    ca_without_sponsorship = "Must be authorised to work in Canada without sponsorship."
    assert is_not_required(ca_without_sponsorship, "Canada")
    assert not is_available(ca_without_sponsorship)

    ca_pr = "Canadian citizen or permanent resident required."
    assert is_not_required(ca_pr, "Canada")
    assert not is_not_required(ca_pr, "United States")  # Preserves country specificity

    us_cit = "U.S. citizenship required for federal compliance."
    assert is_not_required(us_cit, "United States")
    assert not is_not_required(us_cit, "Canada")  # Preserves country specificity


def test_invalid_filter_values_return_400():
    """Invalid experience level or sponsorship values return 400 Bad Request."""
    res1 = client.get("/api/jobs?experience_level=ninja")
    assert res1.status_code == 400
    assert "Invalid experience_level" in res1.json()["detail"]

    res2 = client.get("/api/jobs?sponsorship=random_value")
    assert res2.status_code == 400
    assert "Invalid sponsorship" in res2.json()["detail"]
