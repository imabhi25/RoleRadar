"""Simplify discovery: parsing, official-source verification and the guarantee that candidates are never public."""
from contextlib import contextmanager
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.database import get_db_connection
from api.main import app
from ingestion.base import RawJobPosting
from ingestion.http_client import IngestionFetchError
from ingestion.normalizer import classify_application_urls
from ingestion.simplify import (
    BoardSnapshot,
    attach_simplify_urls,
    detect_provider,
    parse_listing,
    parse_listings,
    persist_candidates,
    resolve_candidates,
    run_simplify_discovery,
    verify_workday_posting,
)

INTERN_SRC = {"repo": "SimplifyJobs/Summer2027-Internships", "branch": "dev", "path": "x", "kind": "internship"}
GRAD_SRC = {"repo": "SimplifyJobs/New-Grad-Positions", "branch": "dev", "path": "x", "kind": "new_grad"}
UUID_A = "b6f276b1-e348-4c1e-a17d-6c451056fecc"

TARGETS = [
    {"name": "Cohere", "ats": "ashby", "identifier": "cohere"},
    {"name": "RBC", "ats": "workday", "identifier": "rbc.wd3/RBCGLOBAL1", "aliases": ["Royal Bank of Canada"]},
    {"name": "Stripe", "ats": "greenhouse", "identifier": "stripe"},
]


def raw(**over):
    row = {
        "source": "Simplify", "category": "Software", "company_name": "Cohere", "id": UUID_A,
        "title": "Software Engineer Intern - Summer 2027", "active": True, "is_visible": True,
        "terms": ["Summer 2027"], "date_posted": 1769988342,
        "url": "https://jobs.ashbyhq.com/cohere/8c035d3d-081d-4c8a-914a-72f4efaad254/application",
        "locations": ["Toronto, ON, Canada", "SF"], "company_url": "https://simplify.jobs/c/Cohere",
    }
    row.update(over)
    return row


def job(job_id, url="https://jobs.ashbyhq.com/cohere/x", apply_url=None):
    return RawJobPosting("ashby", job_id, "Cohere", "Software Engineer Intern", "Toronto, ON", url, None, "", company_apply_url=apply_url)


# --------------------------------------------------------------------------- parsing

def test_parse_candidate_fields():
    c = parse_listing(raw(), INTERN_SRC)
    assert (c.company_name, c.title, c.role_type) == ("Cohere", "Software Engineer Intern - Summer 2027", "internship")
    assert (c.term_season, c.term_year) == ("summer", 2027)
    assert c.has_canada and c.eligible_country == "Canada" and c.in_scope and c.status == "discovered"
    assert c.candidate_key == f"{INTERN_SRC['repo']}:{UUID_A}"
    assert {l["country"] for l in c.locations} == {"Canada", "United States"}   # 'SF' expanded
    assert c.discovered_url.startswith("https://jobs.ashbyhq.com/cohere/")
    assert c.official_url is None and not c.official_url_verified   # nothing is official until verified


def test_role_type_uses_title_first_then_repo_kind():
    assert parse_listing(raw(title="Software Developer Co-op"), INTERN_SRC).role_type == "co_op"
    assert parse_listing(raw(title="Software Engineer"), GRAD_SRC).role_type == "new_grad"
    assert parse_listing(raw(title="Software Engineer"), INTERN_SRC).role_type == "internship"
    assert parse_listing(raw(title="Entry Level Software Developer"), GRAD_SRC).role_type == "entry_level"


def test_term_from_structured_terms_and_unknown_when_absent_or_ambiguous():
    assert parse_listing(raw(title="Software Engineer Intern", terms=["Fall 2026"]), INTERN_SRC).term_season == "fall"
    assert parse_listing(raw(title="Software Engineer Intern", terms=["N/A"]), INTERN_SRC).term_season is None
    assert parse_listing(raw(title="Software Engineer Intern", terms=["Fall 2026", "Winter 2026"]), INTERN_SRC).term_season is None


def test_ineligible_rows_are_kept_with_a_reason_but_out_of_scope():
    cases = {
        "closed": raw(active=False), "invalid": raw(title="Finance Intern"),
    }
    assert parse_listing(cases["closed"], INTERN_SRC).status == "closed"
    inv = parse_listing(cases["invalid"], INTERN_SRC)
    assert inv.status == "invalid" and "software" in inv.reason
    uk = parse_listing(raw(locations=["London, UK"]), INTERN_SRC)
    assert uk.status == "invalid" and "United States or Canada" in uk.reason
    assert parse_listing(raw(is_visible=False), INTERN_SRC).status == "invalid"
    assert parse_listing(raw(url=None), INTERN_SRC).status == "invalid"
    assert not any(parse_listing(v, INTERN_SRC).in_scope for v in (raw(active=False), raw(title="Finance Intern")))


def test_malformed_rows_are_counted_not_crashing():
    candidates, malformed = parse_listings([raw(), "junk", {"id": "x"}, {"company_name": "A", "title": "B"}, None], INTERN_SRC)
    assert len(candidates) == 1 and malformed == 4


def test_simplify_url_is_only_ever_a_real_listing_link():
    assert parse_listing(raw(), INTERN_SRC).simplify_url == f"https://simplify.jobs/p/{UUID_A}"
    assert parse_listing(raw(source="AlmondCroffle"), INTERN_SRC).simplify_url is None   # community row: no Simplify posting
    assert parse_listing(raw(id="not-a-uuid"), INTERN_SRC).simplify_url is None
    # the company page is never used as a job link
    assert "/c/" not in (parse_listing(raw(), INTERN_SRC).simplify_url or "")


# --------------------------------------------------------------------------- provider detection

@pytest.mark.parametrize("url,provider,identifier,job_id,official", [
    ("https://job-boards.greenhouse.io/cresta/jobs/5106468008", "greenhouse", "cresta", "5106468008", True),
    ("https://boards.greenhouse.io/embed/job_app?token=7231006", "greenhouse", None, "7231006", True),
    ("https://jobs.lever.co/waabi/0d14f3b0-2b9d-4c62-9e57-32d0bda7d3f2/apply", "lever", "waabi", "0d14f3b0-2b9d-4c62-9e57-32d0bda7d3f2", True),
    ("https://jobs.ashbyhq.com/bree/5e79b2fd-164c-4e72-91ef-1b8fd1c5518a/application", "ashby", "bree", "5e79b2fd-164c-4e72-91ef-1b8fd1c5518a", True),
    ("https://aptiv.wd5.myworkdayjobs.com/aptiv_careers/job/CAN-Kanata/Engineering-Intern_R1", "workday", "aptiv.wd5/aptiv_careers", "Engineering-Intern_R1", True),
    ("https://www.amazon.jobs/en/jobs/10559397/sde", "amazon", None, "10559397", True),
    ("https://careers-amd.icims.com/jobs/1234/job", "icims", None, None, True),
    ("https://acme.com/careers/role?gh_jid=4001", "greenhouse", None, "4001", True),
    ("https://acme.com/careers/role", "custom", None, None, True),
    ("https://www.linkedin.com/jobs/view/123", None, None, None, False),
    ("https://simplify.jobs/p/" + UUID_A, None, None, None, False),
    (None, None, None, None, False),
])
def test_detect_provider(url, provider, identifier, job_id, official):
    info = detect_provider(url)
    assert (info.provider, info.identifier, info.job_id, info.official) == (provider, identifier, job_id, official)


# --------------------------------------------------------------------------- verification

def cand(url, company="Cohere", **over):
    return parse_listing(raw(url=url, company_name=company, **over), INTERN_SRC)


def snapshot(*ids, complete=True):
    return BoardSnapshot(True, complete, {i: job(i, apply_url=f"https://jobs.ashbyhq.com/cohere/{i}/application") for i in ids})


def test_verified_through_official_board_and_company_configured():
    c = cand("https://jobs.ashbyhq.com/cohere/8c035d3d-081d-4c8a-914a-72f4efaad254/application")
    resolve_candidates([c], TARGETS, fetch_board=lambda *a: snapshot("8c035d3d-081d-4c8a-914a-72f4efaad254"))
    assert c.status == "verified" and c.verification_status == "verified" and c.official_url_verified
    assert c.official_url == "https://jobs.ashbyhq.com/cohere/8c035d3d-081d-4c8a-914a-72f4efaad254/application"
    assert c.company_configured and c.matched_source_name == "ashby"
    assert c.matched_source_job_id == "8c035d3d-081d-4c8a-914a-72f4efaad254"


def test_verified_but_company_not_configured_is_still_not_public():
    c = cand("https://jobs.ashbyhq.com/newco/8c035d3d-081d-4c8a-914a-72f4efaad254", company="NewCo")
    resolve_candidates([c], TARGETS, fetch_board=lambda *a: snapshot("8c035d3d-081d-4c8a-914a-72f4efaad254"))
    assert c.status == "verified" and not c.company_configured
    assert "not public" in c.reason


def test_closed_only_when_official_snapshot_is_complete():
    url = "https://jobs.ashbyhq.com/cohere/00000000-0000-0000-0000-000000000000"
    complete, partial = cand(url), cand(url)
    resolve_candidates([complete], TARGETS, fetch_board=lambda *a: snapshot("other"))
    assert complete.status == "closed" and not complete.official_url_verified
    resolve_candidates([partial], TARGETS, fetch_board=lambda *a: snapshot("other", complete=False))
    assert partial.status == "official_not_found" and partial.status != "closed"


def test_board_fetch_failure_is_reported_not_verified():
    c = cand("https://jobs.lever.co/ghost/0d14f3b0-2b9d-4c62-9e57-32d0bda7d3f2", company="Ghost")
    stats = resolve_candidates([c], TARGETS, fetch_board=lambda *a: BoardSnapshot(False, error="HTTP 404"))
    assert c.status == "official_not_found" and not c.official_url_verified
    assert stats["boards_failed"] == [{"board": "lever:ghost", "error": "HTTP 404"}]


def test_unsupported_platforms_aggregators_and_unresolvable_urls():
    icims = cand("https://careers-amd.icims.com/jobs/1234/job", company="AMD")
    custom = cand("https://acme.com/careers/role", company="Acme")
    linkedin = cand("https://www.linkedin.com/jobs/view/123", company="Acme")
    embed = cand("https://boards.greenhouse.io/embed/job_app?token=7231006", company="Squarepoint")
    resolve_candidates([icims, custom, linkedin, embed], TARGETS, fetch_board=Mock(side_effect=AssertionError("must not fetch")))
    assert icims.status == "unsupported_source" and "icims" in icims.reason and icims.official_url
    assert custom.status == "unsupported_source"
    assert linkedin.status == "official_not_found" and linkedin.official_url is None
    assert embed.status == "official_url_resolved" and not embed.official_url_verified


def test_workday_direct_verification():
    url = "https://rbc.wd3.myworkdayjobs.com/RBCGLOBAL1/job/TORONTO/Dev_R-1"
    ok, gone, err = cand(url, company="Royal Bank of Canada"), cand(url + "2", company="Royal Bank of Canada"), cand(url + "3", company="Royal Bank of Canada")
    results = {"Dev_R-1": ("verified", url), "Dev_R-12": ("not_found", None), "Dev_R-13": ("error", None)}
    resolve_candidates([ok, gone, err], TARGETS, verify_workday=lambda wd: results[wd[3].rsplit("/", 1)[-1]])
    assert ok.status == "verified" and ok.company_configured   # matched by tenant identity, not just the name
    assert gone.status == "closed"
    assert err.status == "deferred" and err.verification_status == "error"


def test_verify_workday_posting_uses_official_detail_endpoint():
    http = Mock()
    http.get_json.return_value = {"jobPostingInfo": {"title": "Dev", "canApply": True}}
    state, official = verify_workday_posting(("rbc", "wd3", "RBCGLOBAL1", "/job/T/Dev_R-1"), http)
    assert state == "verified" and official == "https://rbc.wd3.myworkdayjobs.com/RBCGLOBAL1/job/T/Dev_R-1"
    http.get_json.assert_called_with("https://rbc.wd3.myworkdayjobs.com/wday/cxs/rbc/RBCGLOBAL1/job/T/Dev_R-1")
    http.get_json.side_effect = IngestionFetchError("HTTP 404 error from x")
    assert verify_workday_posting(("rbc", "wd3", "RBCGLOBAL1", "/job/T/Dev_R-1"), http)[0] == "not_found"
    http.get_json.side_effect = IngestionFetchError("Network error")
    assert verify_workday_posting(("rbc", "wd3", "RBCGLOBAL1", "/job/T/Dev_R-1"), http)[0] == "error"


def test_duplicates_and_already_known_and_budget():
    a = cand("https://jobs.ashbyhq.com/cohere/8c035d3d-081d-4c8a-914a-72f4efaad254/application")
    b = cand("https://jobs.ashbyhq.com/cohere/8c035d3d-081d-4c8a-914a-72f4efaad254?utm_source=x")
    b.source_id = "second"
    resolve_candidates([a, b], TARGETS, fetch_board=lambda *x: snapshot("8c035d3d-081d-4c8a-914a-72f4efaad254"),
                       known_jobs={("ashby", "8c035d3d-081d-4c8a-914a-72f4efaad254")})
    assert a.status == "already_known" and a.official_url_verified
    assert b.duplicate_of == a.candidate_key and b.status == "already_known"

    c1, c2 = cand("https://jobs.ashbyhq.com/aaa/8c035d3d-081d-4c8a-914a-72f4efaad254"), cand("https://jobs.ashbyhq.com/bbb/9c035d3d-081d-4c8a-914a-72f4efaad254")
    c2.locations = []; c2.has_canada = False
    c1.has_canada = True
    resolve_candidates([c2, c1], TARGETS, fetch_board=lambda *x: snapshot("8c035d3d-081d-4c8a-914a-72f4efaad254"), max_boards=1)
    assert c1.status == "verified" and c2.status == "deferred"   # Canada-first budget


def test_run_discovery_reports_failed_sources_and_continues():
    listings = {GRAD_SRC["repo"]: [raw(company_name="Stripe", title="Software Engineer, New Grad",
                                       url="https://job-boards.greenhouse.io/stripe/jobs/777", id="c6f276b1-e348-4c1e-a17d-6c451056fecc")]}
    with patch("ingestion.simplify.fetch_listings", side_effect=IngestionFetchError("boom")):
        candidates, report = run_simplify_discovery(
            TARGETS, sources=[INTERN_SRC, GRAD_SRC], listings_override=listings,
            fetch_board=lambda *a: BoardSnapshot(True, True, {"777": job("777", "https://job-boards.greenhouse.io/stripe/jobs/777")}))
    assert report["failed_sources"] == [{"source": INTERN_SRC["repo"], "error": "boom"}]
    assert report["candidates_parsed"] == 1 and report["verified_through_official_source"] == 1
    assert candidates[0].status == "verified"


def test_simplify_link_never_duplicates_primary_route():
    routes = classify_application_urls("https://jobs.ashbyhq.com/cohere/1", None, None, "https://simplify.jobs/p/" + UUID_A)
    assert routes["company_apply_url"] == "https://jobs.ashbyhq.com/cohere/1"
    assert routes["simplify_url"] == "https://simplify.jobs/p/" + UUID_A
    # a Simplify-only source URL is never promoted to the official company route
    only = classify_application_urls("https://simplify.jobs/p/" + UUID_A, None, None, None)
    assert only["company_apply_url"] is None
    assert classify_application_urls("https://simplify.jobs/c/Cohere", None, None, "https://simplify.jobs/c/Cohere")["company_apply_url"] is None


# --------------------------------------------------------------------------- database guarantees

@pytest.fixture
def conn():
    try:
        connection = get_db_connection()
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('discovery_candidates')")
        if cur.fetchone()[0] is None:
            pytest.skip("migration 008 not applied to the test database")
    yield connection
    connection.rollback()
    connection.close()


def test_candidates_are_never_public_jobs_and_simplify_url_only_decorates_official_jobs(conn):
    tag = uuid4().hex[:10]
    verified = parse_listing(raw(id=str(uuid4()), company_name=f"Cohere {tag}"), INTERN_SRC)
    verified.official_url_verified = True
    verified.status = "verified"
    verified.official_url = "https://jobs.ashbyhq.com/cohere/official-1"
    verified.matched_source_name, verified.matched_source_job_id = "ashby", f"official-{tag}"
    unmatched = parse_listing(raw(id=str(uuid4()), company_name=f"Nowhere {tag}"), INTERN_SRC)
    unmatched.official_url_verified, unmatched.status = True, "verified"
    unmatched.matched_source_name, unmatched.matched_source_job_id = "ashby", f"missing-{tag}"
    community = parse_listing(raw(id=str(uuid4()), source="AlmondCroffle", company_name=f"Cohere {tag}"), INTERN_SRC)
    community.official_url_verified, community.status = True, "verified"
    community.matched_source_name, community.matched_source_job_id = "ashby", f"official-{tag}"
    pending = parse_listing(raw(id=str(uuid4()), company_name=f"Pending {tag}"), INTERN_SRC)

    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(name) VALUES (%s) RETURNING id", (f"Cohere {tag}",))
        cid = cur.fetchone()[0]
        cur.execute("INSERT INTO locations(location,country) VALUES ('Toronto, ON','Canada') ON CONFLICT (location,country) DO UPDATE SET country='Canada' RETURNING id")
        lid = cur.fetchone()[0]
        cur.execute("""INSERT INTO job_postings(job_id,company_id,location_id,title,source_name,source_job_id,source_url,
                       company_apply_url,description,locations) VALUES (%s,%s,%s,'Software Engineer Intern','ashby',%s,%s,%s,'d','[]')""",
                    (f"ashby:official-{tag}", cid, lid, f"official-{tag}", "https://jobs.ashbyhq.com/cohere/official-1", "https://jobs.ashbyhq.com/cohere/official-1"))
        cur.execute("SELECT COUNT(*) FROM job_postings")
        before = cur.fetchone()[0]

        written = persist_candidates(cur, [verified, unmatched, community, pending])
        assert written == 4
        persist_candidates(cur, [verified])          # idempotent upsert
        cur.execute("SELECT COUNT(*) FROM discovery_candidates WHERE company_name LIKE %s", (f"%{tag}",))
        assert cur.fetchone()[0] == 4

        # 1. persisting candidates created no job postings at all
        cur.execute("SELECT COUNT(*) FROM job_postings")
        assert cur.fetchone()[0] == before
        cur.execute("SELECT COUNT(*) FROM job_postings WHERE company_id IN (SELECT id FROM companies WHERE name LIKE %s)", (f"%{tag}",))
        assert cur.fetchone()[0] == 1

        # 2. attaching only decorates the already-ingested official job with a real Simplify link
        attached = attach_simplify_urls(cur, [verified, unmatched, community, pending])
        assert attached == 1
        cur.execute("SELECT simplify_url, company_apply_url FROM job_postings WHERE source_job_id=%s", (f"official-{tag}",))
        simplify_url, apply_url = cur.fetchone()
        assert simplify_url == verified.simplify_url and simplify_url.startswith("https://simplify.jobs/p/")
        assert apply_url == "https://jobs.ashbyhq.com/cohere/official-1"     # official stays the primary route
        cur.execute("SELECT COUNT(*) FROM job_postings")
        assert cur.fetchone()[0] == before

    @contextmanager
    def cursor():
        with conn.cursor() as cur:
            yield cur
    with patch("api.main.get_db_cursor", cursor):
        client = TestClient(app)
        for name in (f"Nowhere {tag}", f"Pending {tag}"):
            assert client.get("/api/jobs", params={"q": name}).json()["total"] == 0
        public = client.get("/api/jobs", params={"company": f"Cohere {tag}"}).json()
        assert public["total"] == 1
        assert public["jobs"][0]["simplify_url"] == verified.simplify_url
        assert public["jobs"][0]["company_apply_url"] == "https://jobs.ashbyhq.com/cohere/official-1"
