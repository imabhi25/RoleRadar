"""Public-data audit: locations. Vendor formats, "Offsite/Home" and "Remote-Friendly (Travel Required)" are not places,
the same city has one label, and nothing about where a job may be worked from is guessed.

Examples are the production records named in the audit: NVIDIA, Thomson Reuters and Autodesk (Workday), Anthropic (Greenhouse).
"""
import json
from contextlib import contextmanager

import pytest
from psycopg2.extras import Json

from db.repair_public_data import repair_public_data
from ingestion.clients.workday import WorkdayClient
from ingestion.normalizer import is_user_facing_location_eligible, normalize_job_locations
from ingestion.places import canonical_place_label
from ingestion.workday_locations import normalize_workday_location, repair_stored_workday_entries
from tests.test_public_visibility import _api, _company, _insert, conn  # noqa: F401  (conn is a pytest fixture)
from tests.test_workday_amazon import FakeWorkday, make_listing


class Tenant(FakeWorkday):
    """One Workday posting as a tenant publishes it: label, additional labels and Workday's own country descriptor."""

    def __init__(self, primary, extra, descriptor):
        super().__init__([make_listing(1)])
        self.primary, self.extra, self.descriptor = primary, extra, descriptor

    def get_json(self, url, params=None, headers=None, timeout=None):
        data = super().get_json(url)
        data["jobPostingInfo"].update({"location": self.primary, "additionalLocations": self.extra, "country": {"descriptor": self.descriptor}})
        return data


def fetch(primary, extra, descriptor):
    job = WorkdayClient(http_client=Tenant(primary, extra, descriptor)).fetch_jobs("Acme", "acme.wd3/Careers").jobs[0]
    return job, normalize_job_locations(job.raw_location, job.raw_locations)


# ------------------------------------------------------------------------------------------------ vendor formats (NVIDIA, Thomson Reuters)
def test_nvidia_primary_label_is_canonical_although_workday_says_united_states_of_america():
    # production: 188 jobs showed "US, CA, Santa Clara" (the primary label skipped parsing because the descriptor's spelling differed)
    job, locations = fetch("US, CA, Santa Clara", ["US, TX, Austin", "US, CA, Remote"], "United States of America")
    assert [(l["location"], l["country"]) for l in locations] == [
        ("Santa Clara, CA, United States", "United States"), ("Austin, TX, United States", "United States"),
        ("Remote - California, United States", "United States"),
    ]
    assert [l["raw_location"] for l in locations] == ["US, CA, Santa Clara", "US, TX, Austin", "US, CA, Remote"]    # the published labels are kept
    assert job.raw_location == "Santa Clara, CA, United States"
    assert all(is_user_facing_location_eligible(l["location"], l["country"]) for l in locations)


@pytest.mark.parametrize("raw,expected", [
    ("United States of America, Eagan, Minnesota", "Eagan, MN, United States"),
    ("United States of America, Washington, District of Columbia", "Washington, DC, United States"),   # the city, not the state of Washington
    ("United States of America", "United States"),
    ("Canada, Toronto, Ontario", "Toronto, Ontario, Canada"),
])
def test_thomson_reuters_labels(raw, expected):
    assert normalize_workday_location(raw)["location"] == expected


def test_thomson_reuters_primary_keeps_its_city():
    # production: primary became just "United States" with the city only in source_location
    job, locations = fetch("United States of America, Eagan, Minnesota", ["Canada, Toronto, Ontario"], "United States of America")
    assert [l["location"] for l in locations] == ["Eagan, MN, United States", "Toronto, Ontario, Canada"]


# ------------------------------------------------------------------------------------------------ Autodesk "Offsite/Home"
def test_autodesk_offsite_home_is_not_a_place_and_no_bogus_city_is_made():
    # production: "AMER - Canada - Ontario - Offsite/Home" became "Offsite" (country Unknown) and "Home, Ontario, Canada"
    job, locations = fetch("AMER - Canada - Ontario - Offsite/Home", ["AMER - United States - Washington - Offsite/Home", "Offsite"], "Canada")
    assert [(l["location"], l["country"]) for l in locations] == [("Ontario, Canada", "Canada"), ("Washington, United States", "United States")]
    assert locations[0]["raw_location"] == "AMER - Canada - Ontario - Offsite/Home"
    assert not any("Offsite" in l["location"] or l["location"].startswith("Home") for l in locations)


@pytest.mark.parametrize("raw,expected", [
    ("AMER - United States - Massachusetts - Boston - Drydock", "Boston, MA, United States"),            # site name dropped, city kept
    ("AMER - United States - Georgia - Atlanta - Peachtree St NW", "Atlanta, GA, United States"),
    ("AMER - Canada - Quebec - Montreal - 10 Rue Duke", "Montreal, Quebec, Canada"),
    ("AMER - United States - Oregon - Portland", "Portland, OR, United States"),
    ("California, USA - Remote", "Remote - California, United States"),
])
def test_autodesk_hierarchical_labels(raw, expected):
    assert normalize_workday_location(raw)["location"] == expected


def test_stored_autodesk_rows_are_repaired_from_the_labels_that_were_published():
    stored = [
        {"country": "United States", "location": "United States", "source_location": "AMER - United States - Oregon - Portland"},
        {"country": "Unknown", "location": "Offsite"},
        {"country": "United States", "location": "Home, WA, United States"},
        {"country": "United States", "location": "US, CA, Santa Clara"},
    ]
    assert repair_stored_workday_entries(stored) == [
        {"location": "Portland, OR, United States", "country": "United States", "raw_location": "AMER - United States - Oregon - Portland"},
        {"location": "Washington, United States", "country": "United States", "raw_location": "Home, WA, United States"},
        {"location": "Santa Clara, CA, United States", "country": "United States", "raw_location": "US, CA, Santa Clara"},
    ]
    # a stored country that disagrees with the label is not overridden
    assert repair_stored_workday_entries([{"country": "Canada", "location": "US, TX"}]) == [{"country": "Canada", "location": "US, TX"}]


# ------------------------------------------------------------------------------------------------ Anthropic "Remote-Friendly (Travel Required)"
def test_work_policy_notes_are_not_locations_and_do_not_make_real_locations_remote():
    # production: "Remote-Friendly (Travel Required) | San Francisco, CA" -> a bogus place and every location marked Remote
    result = normalize_job_locations("Remote-Friendly (Travel Required) | San Francisco, CA")
    assert [(l["location"], l["country"]) for l in result] == [("San Francisco, CA, United States", "United States")]
    # rows stored by the older normalizer carried the mangled form
    stored = [{"location": "Remote - Friendly (Travel Required", "country": "Unknown"}, {"location": "Remote - San Francisco, CA", "country": "United States"}]
    assert [l["location"] for l in normalize_job_locations("Remote - San Francisco, CA", stored)] == ["Remote - San Francisco, CA"]


# ------------------------------------------------------------------------------------------------ one label per well-known city
@pytest.mark.parametrize("label,country,expected", [
    ("Toronto", "Canada", "Toronto, Ontario, Canada"),
    ("Toronto, ON", None, "Toronto, Ontario, Canada"),
    ("Toronto, ON, CA", None, "Toronto, Ontario, Canada"),
    ("Toronto, Canada", None, "Toronto, Ontario, Canada"),
    ("Toronto, Ontario", None, "Toronto, Ontario, Canada"),
    ("Vancouver, BC", None, "Vancouver, British Columbia, Canada"),
    ("San Francisco", "United States", "San Francisco, CA, United States"),
    ("San Francisco, CA", None, "San Francisco, CA, United States"),
    ("San Francisco, California, United States", None, "San Francisco, CA, United States"),
    ("San Francisco, CA, USA", None, "San Francisco, CA, United States"),
    ("New York City, NY", None, "New York, NY, United States"),
    ("New York, New York", None, "New York, NY, United States"),
    ("Waterloo, ON", "Canada", "Waterloo, Ontario, Canada"),
])
def test_the_same_city_has_one_label(label, country, expected):
    assert canonical_place_label(label, country) == expected


@pytest.mark.parametrize("label,country", [
    ("San Francisco HQ", "United States"), ("Hybrid - San Francisco", "United States"), ("Remote - San Francisco, CA", "United States"),
    ("Toronto Headquarters", "Canada"), ("San Francisco, CA • New York, NY", "United States"), ("Toronto, Winnipeg", "Canada"),
    ("Waterloo", "United States"),                 # Waterloo, Iowa: only Canada-labelled Waterloo is rewritten
    ("Toronto, ON, USA", "Canada"),                # a region or country that does not belong to the city: left as published
    ("San Francisco, ON", None), ("Toronto, TX", None),
    ("Springfield", "United States"), ("London", "United Kingdom"), ("Kitchener-Waterloo, ON", "Canada"),
])
def test_anything_else_is_left_exactly_as_published(label, country):
    assert canonical_place_label(label, country) is None


def test_canonical_labels_keep_the_published_label_and_stay_public_and_filterable():
    locations = normalize_job_locations("Toronto, ON; Seattle, WA")
    assert locations == [
        {"location": "Toronto, Ontario, Canada", "country": "Canada", "raw_location": "Toronto, ON"},
        {"location": "Seattle, WA, United States", "country": "United States", "raw_location": "Seattle, WA"},
    ]
    assert all(is_user_facing_location_eligible(l["location"], l["country"]) for l in locations)


def test_unknown_country_entries_stay_unknown_when_the_country_cannot_be_known():
    # "SF", "Americas", "Dublin" at an employer with no country evidence: kept as published, never guessed
    for label in ("SF", "Americas", "Dublin"):
        assert normalize_job_locations(label)[0]["location"] == label


# ------------------------------------------------------------------------------------------------ backfill of stored rows, end to end
def test_backfill_repairs_stored_workday_rows_and_the_location_filter_still_finds_them(conn):
    name, cid = _company(conn)
    with conn.cursor() as cur:
        _insert(cur, cid, name + "-nv", days_old=1, location="Toronto, ON")
        stored = [{"country": "United States", "location": "US, CA, Santa Clara"}, {"country": "United States", "location": "US, TX, Austin", "raw_location": "US, TX, Austin"}]
        cur.execute("INSERT INTO locations(location,country) VALUES ('US, CA, Santa Clara','United States') ON CONFLICT DO NOTHING")
        cur.execute("SELECT id FROM locations WHERE location='US, CA, Santa Clara' AND country='United States'")
        raw_label = cur.fetchone()[0]
        cur.execute("UPDATE job_postings SET source_name='workday', location_id=%s, locations=%s WHERE job_id=%s", (raw_label, Json(stored), name + "-nv"))
        _insert(cur, cid, name + "-au", days_old=1, location="Toronto, ON")
        cur.execute("UPDATE job_postings SET source_name='workday', locations=%s WHERE job_id=%s", (Json([
            {"country": "Unknown", "location": "Offsite"}, {"country": "Canada", "location": "Home, Ontario, Canada"}]), name + "-au"))
    repair_public_data(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT l.location, jp.locations FROM job_postings jp JOIN locations l ON l.id=jp.location_id WHERE jp.job_id=%s", (name + "-nv",))
        label, locations = cur.fetchone()
        cur.execute("SELECT locations FROM job_postings WHERE job_id=%s", (name + "-au",))
        autodesk = cur.fetchone()[0]
    assert label == "Santa Clara, CA, United States"
    assert [l["location"] for l in locations] == ["Santa Clara, CA, United States", "Austin, TX, United States"]
    assert locations[0]["raw_location"] == "US, CA, Santa Clara"
    assert [(l["location"], l["country"]) for l in autodesk] == [("Ontario, Canada", "Canada")]
    repair_public_data(conn)        # idempotent
    with conn.cursor() as cur:
        cur.execute("SELECT locations FROM job_postings WHERE job_id=%s", (name + "-nv",))
        assert cur.fetchone()[0] == locations
    with _api(conn) as client:
        found = client.get("/api/jobs", params={"company": name, "location": "San Francisco, CA"}).json()
        assert found["total"] == 0                      # no San Francisco job here
        found = client.get("/api/jobs", params={"company": name, "country": "United States"}).json()
        assert {j["job_id"] for j in found["jobs"]} == {name + "-nv"}      # the Santa Clara/Austin job is found by country
        toronto = client.get("/api/jobs", params={"company": name, "location": "Toronto (GTA)"}).json()
        assert toronto["total"] == 0 or all("Toronto" in json.dumps(j["locations"]) for j in toronto["jobs"])


def test_backfill_drops_the_non_place_but_never_un_remotes_a_stored_label_that_lost_its_source():
    # Why Anthropic's location is finished by the next ingestion run, not by the backfill: the stored "Remote - San Francisco, CA" has no
    # raw label, so it cannot be told from a genuine remote posting. Only the entry that is plainly not a place is removed.
    stored = [{"location": "Remote - Friendly (Travel Required", "country": "Unknown"}, {"location": "Remote - San Francisco, CA", "country": "United States"}]
    assert [l["location"] for l in normalize_job_locations("Remote - San Francisco, CA", stored)] == ["Remote - San Francisco, CA"]
    # From the source's own string, ingestion gets it right (and does not mark the real city remote).
    assert [(l["location"], l["country"]) for l in normalize_job_locations("Remote-Friendly (Travel Required) | San Francisco, CA")] == [("San Francisco, CA, United States", "United States")]


def test_merged_spellings_keep_every_published_label_and_the_merge_is_idempotent():
    first = normalize_job_locations("x", [{"location": "New York", "country": "United States"}, {"location": "New York, USA", "country": "United States"}])
    assert first == [{"location": "New York, NY, United States", "country": "United States", "raw_location": "New York", "also_published": ["New York, USA"]}]
    assert normalize_job_locations("x", first) == first
