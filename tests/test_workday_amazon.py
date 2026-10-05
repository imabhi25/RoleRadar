"""Workday / Amazon adapters: pagination, partial-fetch safety and tombstone protection."""
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from api.database import get_db_connection
from ingestion.clients import get_ats_client
from ingestion.clients.amazon import AmazonClient
from ingestion.clients.workday import WorkdayClient, parse_workday_identifier, parse_workday_job_url
from ingestion.http_client import IngestionFetchError
from ingestion.pipeline import sync_company

LIST_URL = "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"


def make_listing(n, title=None, location="Toronto, Ontario, Canada"):
    return {
        "title": title or f"Software Developer {n}",
        "externalPath": f"/job/Toronto/Software-Developer-{n}_R-{n}",
        "locationsText": location,
        "postedOn": "Posted Today",
        "bulletFields": [f"R-{n}"],
    }


class FakeWorkday:
    """Minimal fake of the Workday CXS list + detail endpoints."""

    def __init__(self, listings, page_size=20, fail_offsets=(), fail_details=(), reported_total=None,
                 facets=None, head_shift_after=None):
        self.listings = listings
        self.fail_offsets = set(fail_offsets)
        self.fail_details = set(fail_details)
        self.reported_total = reported_total
        self.facets = facets or []
        self.head_shift_after = head_shift_after
        self.list_calls = 0
        self.bodies = []

    def post_json(self, url, body, headers=None, timeout=None, attempts=3):
        assert url == LIST_URL
        self.bodies.append(body)
        self.list_calls += 1
        offset, limit = body["offset"], body["limit"]
        if offset in self.fail_offsets:
            raise IngestionFetchError("HTTP 503")
        rows = list(self.listings)
        if self.head_shift_after is not None and self.list_calls > self.head_shift_after:
            rows = [make_listing(9999)] + rows   # a new job appeared at the top mid-crawl
        total = self.reported_total if self.reported_total is not None else len(rows)
        return {"total": total if offset == 0 else 0, "jobPostings": rows[offset:offset + limit], "facets": self.facets}

    def get_json(self, url, params=None, headers=None, timeout=None):
        path = url.split("/Careers", 1)[1]
        if path in self.fail_details:
            raise IngestionFetchError("HTTP 500")
        n = path.rsplit("_R-", 1)[1]
        return {"jobPostingInfo": {
            "title": f"Software Developer {n}", "jobDescription": f"<p>Python and Java role {n}</p>",
            "location": "Toronto, Ontario, Canada", "additionalLocations": ["Remote - United States"],
            "country": {"descriptor": "Canada"}, "startDate": "2026-09-20", "timeType": "Full time",
            "externalUrl": f"https://acme.wd3.myworkdayjobs.com/Careers{path}",
        }}


def client(fake):
    return WorkdayClient(http_client=fake)


def test_identifier_and_url_parsing():
    assert parse_workday_identifier("RBC.wd3/RBCGLOBAL1") == ("rbc", "wd3", "RBCGLOBAL1")
    for bad in ("rbc", "rbc.wd3", "rbc/RBCGLOBAL1", "https://rbc.wd3.myworkdayjobs.com/x", ""):
        with pytest.raises(ValueError):
            parse_workday_identifier(bad)
    assert parse_workday_job_url("https://td.wd3.myworkdayjobs.com/en-US/TD_Bank_Careers/job/Toronto/Dev_R1?x=1") == (
        "td", "wd3", "TD_Bank_Careers", "/job/Toronto/Dev_R1")
    assert parse_workday_job_url("https://example.com/job/x") is None


def test_full_crawl_is_complete_and_maps_fields():
    fake = FakeWorkday([make_listing(i) for i in range(45)] + [make_listing(100, title="Payroll Manager")])
    result = client(fake).fetch_jobs("Acme", "acme.wd3/Careers")
    assert result.fetch_complete and result.parse_error_count == 0
    assert len(result.jobs) == result.total_raw_records == 46
    job = next(j for j in result.jobs if j.title == "Software Developer 7")
    assert job.source_name == "workday" and job.source_job_id == "acme.wd3/Careers/Software-Developer-7_R-7"
    assert job.posted_at == datetime(2026, 9, 20, tzinfo=timezone.utc)
    assert job.source_url == "https://acme.wd3.myworkdayjobs.com/Careers/job/Toronto/Software-Developer-7_R-7"
    assert job.company_apply_url == job.source_url
    assert [l["location"] for l in job.raw_locations] == ["Toronto, Ontario, Canada", "Remote - United States"]
    assert job.raw_locations[0]["country"] == "Canada" and "country" not in job.raw_locations[1]
    assert "Python" in job.raw_description
    # Non-software titles are listed (so tombstoning sees them) but never cost a detail request.
    payroll = next(j for j in result.jobs if j.title == "Payroll Manager")
    assert payroll.raw_description == ""


def test_iso3_country_suffixes_are_expanded():
    class Iso(FakeWorkday):
        def get_json(self, url, params=None, headers=None, timeout=None):
            data = super().get_json(url)
            data["jobPostingInfo"]["location"] = "Toronto, ON, CAN"
            data["jobPostingInfo"]["additionalLocations"] = ["Austin, TX, USA"]
            return data
    job = client(Iso([make_listing(1)])).fetch_jobs("Acme", "acme.wd3/Careers").jobs[0]
    # ISO-3 suffixes are expanded, then the label is normalized to its canonical form (source label kept as raw_location)
    assert job.raw_location == "Toronto, Ontario, Canada"
    assert [l["location"] for l in job.raw_locations] == ["Toronto, Ontario, Canada", "Austin, TX, United States"]
    assert [l.get("raw_location") for l in job.raw_locations] == ["Toronto, ON, Canada", "Austin, TX, United States"][:1] + [None]


def test_page_failure_yields_partial_incomplete_snapshot():
    fake = FakeWorkday([make_listing(i) for i in range(60)], fail_offsets={20})
    result = client(fake).fetch_jobs("Acme", "acme.wd3/Careers")
    assert not result.fetch_complete
    assert 0 < len(result.jobs) < 60


def test_first_page_failure_raises():
    fake = FakeWorkday([make_listing(1)], fail_offsets={0})
    with pytest.raises(IngestionFetchError):
        client(fake).fetch_jobs("Acme", "acme.wd3/Careers")


def test_detail_failure_is_counted_and_blocks_completeness():
    fake = FakeWorkday([make_listing(i) for i in range(5)], fail_details={"/job/Toronto/Software-Developer-2_R-2"})
    result = client(fake).fetch_jobs("Acme", "acme.wd3/Careers")
    assert not result.fetch_complete
    assert result.parse_error_count == 1
    assert len(result.jobs) == 4
    assert result.total_raw_records != len(result.jobs)   # the pipeline's own tombstone guard also trips


def test_result_at_workday_ceiling_is_never_complete():
    fake = FakeWorkday([make_listing(i) for i in range(20)], reported_total=2000)
    result = client(fake).fetch_jobs("Acme", "acme.wd3/Careers")
    assert not result.fetch_complete


def test_list_shifting_during_crawl_is_incomplete_but_stable_duplicates_are_not():
    rows = [make_listing(i) for i in range(40)]
    shifted = client(FakeWorkday(rows, head_shift_after=1)).fetch_jobs("Acme", "acme.wd3/Careers")
    assert not shifted.fetch_complete
    stable_dupes = FakeWorkday(rows[:20] + [rows[19]] + rows[20:39], reported_total=40)   # workday itself repeats a row
    assert client(stable_dupes).fetch_jobs("Acme", "acme.wd3/Careers").fetch_complete


def test_unrenderable_stubs_do_not_block_or_get_ingested():
    rows = [make_listing(i) for i in range(3)] + [{"bulletFields": ["R-777"]}]
    result = client(FakeWorkday(rows)).fetch_jobs("Acme", "acme.wd3/Careers")
    assert result.fetch_complete
    assert all("777" not in j.source_job_id for j in result.jobs)


def test_country_facet_restricts_to_us_and_canada():
    facets = [{"facetParameter": "Location_Country", "values": [
        {"descriptor": "Canada", "id": "ca-id", "count": 2}, {"descriptor": "India", "id": "in-id", "count": 9},
        {"descriptor": "United States of America", "id": "us-id", "count": 5}]}]
    fake = FakeWorkday([make_listing(i) for i in range(3)], facets=facets)
    result = client(fake).fetch_jobs("Acme", "acme.wd3/Careers")
    assert result.fetch_complete
    assert fake.bodies[-1]["appliedFacets"] == {"Location_Country": ["ca-id", "us-id"]}


def test_factory_registers_new_sources():
    assert isinstance(get_ats_client("workday"), WorkdayClient)
    assert isinstance(get_ats_client("amazon"), AmazonClient)


# --------------------------------------------------------------------------- pipeline tombstone protection

@pytest.fixture
def conn():
    try:
        connection = get_db_connection()
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    yield connection
    connection.rollback()
    connection.close()


def test_failed_or_partial_workday_fetch_never_tombstones_but_complete_one_does(conn):
    name = "WDLifecycle " + uuid4().hex[:10]
    config = {"name": name, "ats": "workday", "identifier": "acme.wd3/Careers"}
    rows = [make_listing(i) for i in range(3)]

    def run(fake):
        with patch("ingestion.pipeline.get_ats_client", return_value=WorkdayClient(http_client=fake)), \
             patch("ingestion.company_resolver._discover_ats_branding", return_value=None):
            return sync_company(config, db_conn=conn)

    def active():
        with conn.cursor() as cur:
            cur.execute("SELECT source_job_id FROM job_postings WHERE company_id=(SELECT id FROM companies WHERE name=%s) AND is_active", (name,))
            return {r[0] for r in cur.fetchall()}

    try:
        assert run(FakeWorkday(rows))["status"] == "success"
        assert len(active()) == 3
        # 1. a page fails mid-crawl (only the first 20 rows arrive)
        many = rows + [make_listing(i) for i in range(10, 45)]
        assert run(FakeWorkday(many))["status"] == "success"
        before = active()
        partial = run(FakeWorkday(many, fail_offsets={20}))
        assert partial["status"] == "partial_success" and partial["jobs_deactivated"] == 0
        assert active() == before
        # 2. a detail request fails
        broken = run(FakeWorkday(rows[:2], fail_details={"/job/Toronto/Software-Developer-0_R-0"}))
        assert broken["jobs_deactivated"] == 0 and active() == before
        # 3. the whole source is down
        down = FakeWorkday(rows, fail_offsets={0})
        assert run(down)["status"] == "failed" and active() == before
        # 4. a mass drop in an otherwise complete snapshot is suspicious: nothing is deactivated yet
        drop = run(FakeWorkday(rows[:2]))
        assert drop["status"] == "partial_success" and drop["jobs_deactivated"] == 0
        assert "large drop" in drop["tombstone_suppressed_reason"] and active() == before
        # 5. an ordinary complete snapshot lacking one job does deactivate exactly that job
        result = run(FakeWorkday(many[:-1]))
        assert result["status"] == "success" and result["jobs_deactivated"] == 1
        assert len(active()) == len(before) - 1
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM job_postings WHERE company_id=(SELECT id FROM companies WHERE name=%s)", (name,))
            cur.execute("DELETE FROM companies WHERE name=%s", (name,))
            cur.execute("DELETE FROM sync_runs WHERE company_identifier=%s", ("acme.wd3/Careers",))
        conn.commit()


# --------------------------------------------------------------------------- Amazon

def amazon_job(n):
    return {
        "id_icims": str(n), "title": f"Software Development Engineer {n}", "job_path": f"/en/jobs/{n}/sde-{n}",
        "normalized_location": "Toronto, Ontario, CAN", "posted_date": "September 24, 2026",
        "locations": ['{"normalizedCityName":"Toronto","region":"ON","normalizedCountryCode":"CAN"}'],
        "description": "Build services", "basic_qualifications": "Java", "job_schedule_type": "full-time", "is_intern": None,
    }


def test_amazon_complete_and_partial_snapshots():
    http = Mock()
    http.get_json.side_effect = lambda url, params=None, headers=None: {
        "hits": 5, "jobs": [amazon_job(i) for i in range(params["offset"], min(params["offset"] + params["result_limit"], 5))]}
    complete = AmazonClient(http_client=http).fetch_jobs("Amazon", "CAN")
    assert complete.fetch_complete and len(complete.jobs) == 5
    job = complete.jobs[0]
    assert job.source_name == "amazon" and job.source_url == "https://www.amazon.jobs/en/jobs/0/sde-0"
    assert job.raw_locations == [{"location": "Toronto, ON", "country": "CAN"}]
    assert job.posted_at == datetime(2026, 9, 24, tzinfo=timezone.utc)

    # Amazon says 250 hits but the second page fails: not a complete snapshot
    def flaky(url, params=None, headers=None):
        if params["offset"] > 0:
            raise IngestionFetchError("HTTP 500")
        return {"hits": 250, "jobs": [amazon_job(i) for i in range(100)]}
    http.get_json.side_effect = flaky
    partial = AmazonClient(http_client=http).fetch_jobs("Amazon", "CAN")
    assert not partial.fetch_complete and len(partial.jobs) == 100

    http.get_json.side_effect = IngestionFetchError("down")
    with pytest.raises(IngestionFetchError):
        AmazonClient(http_client=http).fetch_jobs("Amazon", "CAN")
    with pytest.raises(ValueError):
        AmazonClient(http_client=http).fetch_jobs("Amazon", "not-a-country")


def test_global_software_roles_fetch_details_outside_north_america():
    class International(FakeWorkday):
        def get_json(self, url, **kwargs):
            data = super().get_json(url)
            data["jobPostingInfo"].update(location="Berlin, Germany", additionalLocations=[], country={"descriptor": "Germany"})
            return data
    result = client(International([make_listing(1, location="Berlin, Germany")])).fetch_jobs("Acme", "acme.wd3/Careers")
    assert result.fetch_complete
    assert result.jobs[0].raw_description == "<p>Python and Java role 1</p>"
    assert result.jobs[0].posted_at is not None
