"""Workday location normalization at ingest: canonical labels, raw label preserved, nothing guessed."""
import pytest

from ingestion.clients.workday import WorkdayClient
from ingestion.normalizer import is_user_facing_location_eligible, normalize_job_locations
from ingestion.workday_locations import normalize_workday_location
from tests.test_workday_amazon import FakeWorkday, make_listing

CANONICAL = [
    # NVIDIA: "<country>, <state>, <city|remote>"
    ("US, CA, Santa Clara", "Santa Clara, CA, United States", "United States"),
    ("US, CA, Remote", "Remote - California, United States", "United States"),
    ("US, TX", "Texas, United States", "United States"),
    ("US, WA, Redmond", "Redmond, WA, United States", "United States"),
    ("US, NY, New York", "New York, NY, United States", "United States"),
    ("US, MA, Remote", "Remote - Massachusetts, United States", "United States"),
    ("Austin, TX", "Austin, TX, United States", "United States"),
    # RBC / Sun Life: street address : CITY
    ("745 THURLOW ST:VANCOUVER", "Vancouver, British Columbia, Canada", "Canada"),
    ("16 YORK ST:TORONTO", "Toronto, Ontario, Canada", "Canada"),
    ("Sun Life Toronto One York", "Toronto, Ontario, Canada", "Canada"),
    # Toronto variants and prefixed regions
    ("AMER - Canada - Ontario - Toronto - University Ave", "Toronto, Ontario, Canada", "Canada"),
    ("TORONTO, Ontario, Canada", "Toronto, Ontario, Canada", "Canada"),
    ("Toronto, Ontario", "Toronto, Ontario, Canada", "Canada"),
    ("Toronto, ON, Canada", "Toronto, Ontario, Canada", "Canada"),
    ("Toronto, ON", "Toronto, Ontario, Canada", "Canada"),
    ("CA, ON, Toronto", "Toronto, Ontario, Canada", "Canada"),
    ("Waterloo, ON", "Waterloo, Ontario, Canada", "Canada"),
    ("Montréal, QC", "Montréal, Quebec, Canada", "Canada"),
    ("Remote - Canada", "Remote - Canada", "Canada"),
]


@pytest.mark.parametrize("raw,expected,country", CANONICAL)
def test_canonical_labels(raw, expected, country):
    result = normalize_workday_location(raw)
    assert result == {"location": expected, "country": country}
    # every canonical label stays inside the public US/Canada geography rules
    assert is_user_facing_location_eligible(result["location"], result["country"])


@pytest.mark.parametrize("raw", [
    "Remote", "Hybrid", "London", "CA", "", "   ", "Some Random Campus", "Building 4", "Headquarters",
    "Bengaluru, Karnataka, India", "New York and Toronto Hub",
])
def test_unresolvable_labels_are_left_exactly_as_published(raw):
    assert normalize_workday_location(raw) is None


def test_nothing_is_invented():
    # a bare city outside the tables gets no province; an unknown region gets no country
    assert normalize_workday_location("Austin") is None
    assert normalize_workday_location("745 THURLOW ST") is None            # street only: no reliable city
    # "CA" is only Canada/California when the tokens around it say which
    assert normalize_workday_location("CA, Santa Clara") is None
    assert normalize_workday_location("US, CA, Santa Clara")["country"] == "United States"
    assert normalize_workday_location("CA, ON, Toronto")["country"] == "Canada"
    # conflicting evidence is not resolved
    assert normalize_workday_location("US, ON, Toronto") is None
    assert normalize_workday_location("Canada, TX") is None


def test_casing_and_workplace_words():
    assert normalize_workday_location("SANTA CLARA, CA, USA")["location"] == "Santa Clara, CA, United States"
    assert normalize_workday_location("vancouver, bc")["location"] == "Vancouver, British Columbia, Canada"
    # Hybrid / On-site describe the workplace, which has its own field: not part of the location
    assert normalize_workday_location("Toronto, ON, Hybrid")["location"] == "Toronto, Ontario, Canada"
    # Remote is preserved
    assert normalize_workday_location("Toronto, ON, Remote")["location"] == "Remote - Toronto, Ontario, Canada"


class Shapes(FakeWorkday):
    def __init__(self, primary, extra):
        super().__init__([make_listing(1)])
        self.primary, self.extra = primary, extra

    def get_json(self, url, params=None, headers=None, timeout=None):
        data = super().get_json(url)
        data["jobPostingInfo"]["location"] = self.primary
        data["jobPostingInfo"]["additionalLocations"] = self.extra
        data["jobPostingInfo"]["country"] = {"descriptor": "Canada"} if "Canada" in self.primary or ":" in self.primary else {"descriptor": "United States"}
        return data


def fetch(primary, extra):
    return WorkdayClient(http_client=Shapes(primary, extra)).fetch_jobs("Acme", "acme.wd3/Careers").jobs[0]


def test_client_keeps_raw_label_and_multi_location_arrays_intact():
    job = fetch("16 YORK ST:TORONTO", ["745 THURLOW ST:VANCOUVER", "Sun Life Toronto One York", "Remote - Canada", "Building 4"])
    locations = job.raw_locations
    assert [l["location"] for l in locations] == [
        "Toronto, Ontario, Canada", "Vancouver, British Columbia, Canada", "Toronto, Ontario, Canada", "Remote - Canada", "Building 4",
    ]
    assert [l.get("raw_location") for l in locations] == ["16 YORK ST:TORONTO", "745 THURLOW ST:VANCOUVER", "Sun Life Toronto One York", None, None]
    assert job.raw_location == "Toronto, Ontario, Canada"
    normalized = normalize_job_locations(job.raw_location, job.raw_locations)
    # multi-location arrays stay intact (the duplicate Toronto collapses; the unknown building stays as published)
    assert [l["location"] for l in normalized][:3] == ["Toronto, Ontario, Canada", "Vancouver, British Columbia, Canada", "Remote - Canada"]
    assert normalized[0]["raw_location"] == "16 YORK ST:TORONTO"
    assert normalized[0]["country"] == "Canada" and normalized[1]["country"] == "Canada"


def test_nvidia_style_us_labels_survive_the_pipeline_normalizer():
    job = fetch("US, CA, Santa Clara", ["US, TX", "US, CA, Remote"])
    normalized = normalize_job_locations(job.raw_location, job.raw_locations)
    assert [(l["location"], l["country"]) for l in normalized] == [
        ("Santa Clara, CA, United States", "United States"),
        ("Texas, United States", "United States"),
        ("Remote - California, United States", "United States"),
    ]
    assert [l["raw_location"] for l in normalized] == ["US, CA, Santa Clara", "US, TX", "US, CA, Remote"]
    assert all(is_user_facing_location_eligible(l["location"], l["country"]) for l in normalized)


def test_disagreeing_country_evidence_keeps_the_source_label():
    # Workday says Canada for the primary location but the label parses as US: trust neither, keep the label
    class Conflict(Shapes):
        def get_json(self, url, params=None, headers=None, timeout=None):
            data = super().get_json(url)
            data["jobPostingInfo"]["country"] = {"descriptor": "Canada"}
            return data
    job = WorkdayClient(http_client=Conflict("US, TX", [])).fetch_jobs("Acme", "acme.wd3/Careers").jobs[0]
    assert job.raw_locations[0]["location"] == "US, TX"
    assert "raw_location" not in job.raw_locations[0]


def test_other_sources_are_unaffected():
    # Workday tenant shapes are only parsed for Workday: another source's street-address label stays as published.
    plain = normalize_job_locations("Toronto, ON", [{"location": "Toronto, ON"}, {"location": "16 YORK ST:TORONTO"}])
    assert plain[1] == {"location": "16 YORK ST:TORONTO", "country": "Canada"}
    # A plain well-known city has one canonical shape for every source, with the published label kept as raw_location.
    assert plain[0] == {"location": "Toronto, Ontario, Canada", "country": "Canada", "raw_location": "Toronto, ON"}
