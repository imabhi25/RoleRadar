"""Compensation must survive ingestion: Lever salaryRange/salaryDescription and Greenhouse pay_input_ranges."""
import json
from pathlib import Path

from ingestion.clients.greenhouse import GreenhouseClient
from ingestion.clients.lever import LeverClient
from ingestion.compensation import build_compensation, interval_from_text, text_mentions_amount

# Real shape of https://api.lever.co/v0/postings/pointclickcare/150b07cd-04e9-46c4-9015-114498f3798c (trimmed text fields)
PCC = {
    "id": "150b07cd-04e9-46c4-9015-114498f3798c", "text": "Senior Machine Learning Systems Engineer (CAD)",
    "createdAt": 1790000000000, "hostedUrl": "https://jobs.lever.co/pointclickcare/150b07cd-04e9-46c4-9015-114498f3798c",
    "applyUrl": "https://jobs.lever.co/pointclickcare/150b07cd-04e9-46c4-9015-114498f3798c/apply",
    "categories": {"location": "Mississauga, Ontario", "commitment": "Full-time", "allLocations": ["Mississauga, Ontario"]},
    "workplaceType": "hybrid",
    "description": "<div>Build ML systems for senior living.</div>", "lists": [{"text": "What you'll do", "content": "<li>Ship models</li>"}],
    "additional": "<div>Equal opportunity employer.</div>",
    "salaryRange": {"min": 154000, "max": 193000, "interval": "per-year-salary", "currency": "CAD"},
    "salaryDescription": ("<div><em>At PointClickCare, base salary is one of the many components that make up our total rewards package. "
                          "The CAD base salary range for this position is $154,000-$193, 000 (not overtime eligible) + bonus + benefits.&nbsp;"
                          "<span data-teams=\"true\">Compensation is assessed individually and aligned to experience.</span></em></div>"),
}


class FakeHttp:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get_json(self, url, params=None, **kwargs):
        self.urls.append((url, params))
        if isinstance(self.payload, list) and params and params.get("skip"):
            return []
        return self.payload


def lever(jobs):
    return LeverClient(http_client=FakeHttp(jobs)).fetch_jobs("PointClickCare", "pointclickcare")


def test_pointclickcare_salary_range_and_narrative_are_preserved():
    job = lever([PCC]).jobs[0]
    assert job.compensation == {
        "compensationTierSummary": "CA$154K – CA$193K", "currency": "CAD", "min": 154000, "max": 193000, "source": "lever",
        "interval": "year",
        "note": "At PointClickCare, base salary is one of the many components that make up our total rewards package. The CAD base salary range "
                "for this position is $154,000-$193, 000 (not overtime eligible) + bonus + benefits. Compensation is assessed individually and aligned to experience.",
    }
    # the bonus/benefits caveat lives in the description, once, as its own section at the end
    assert job.raw_description.count("<h3>Compensation</h3>") == 1
    assert "not overtime eligible) + bonus + benefits" in job.raw_description
    assert job.raw_description.index("Equal opportunity employer") < job.raw_description.index("<h3>Compensation</h3>")


def test_salary_is_not_duplicated_when_the_body_already_states_it():
    job = dict(PCC, description="<div>The range is $154,000 - $193,000 per year.</div>")
    result = lever([job]).jobs[0]
    assert result.compensation["compensationTierSummary"] == "CA$154K – CA$193K"
    assert "bonus + benefits" in result.raw_description
    assert result.raw_description.count("<h3>Compensation</h3>") == 1
    job = dict(PCC, additional="<h3>Compensation</h3><p>See below</p>")
    result = lever([job]).jobs[0]
    assert result.raw_description.count("Compensation</h3>") == 1
    assert "bonus + benefits" in result.raw_description
    duplicated = dict(PCC, description=PCC["salaryDescription"])
    assert lever([duplicated]).jobs[0].raw_description.count("bonus + benefits") == 1


def test_range_without_narrative_and_narrative_without_range():
    only_range = dict(PCC); del only_range["salaryDescription"]
    result = lever([only_range]).jobs[0]
    assert result.compensation["max"] == 193000 and "<h3>Compensation</h3>" not in result.raw_description
    only_text = dict(PCC); del only_text["salaryRange"]
    result = lever([only_text]).jobs[0]
    assert result.compensation is None and "<h3>Compensation</h3>" in result.raw_description   # nothing invented: just the employer's words
    none = {k: v for k, v in PCC.items() if not k.startswith("salary")}
    result = lever([none]).jobs[0]
    assert result.compensation is None and "Compensation" not in result.raw_description


def test_interval_and_currency_are_kept():
    hourly = dict(PCC, salaryRange={"min": 30, "max": 45.5, "interval": "per-hour-wage", "currency": "USD"}, salaryDescription="")
    comp = lever([hourly]).jobs[0].compensation
    assert comp["interval"] == "hour" and comp["currency"] == "USD" and comp["compensationTierSummary"] == "$30 – $45.5 / hour"
    daily = dict(PCC, salaryRange={"min": 400, "max": 400, "interval": "per-day-wage", "currency": "CAD"}, salaryDescription="")
    assert lever([daily]).jobs[0].compensation["compensationTierSummary"] == "CA$400 / day"
    assert interval_from_text("per-month-salary") == "month" and interval_from_text("one-time") is None
    # unusable figures produce nothing rather than a guess
    assert build_compensation("CAD", 0, None, "year", "lever") is None
    assert build_compensation(None, 10, 20, "year", "lever") is None
    assert build_compensation("CAD", 200, 100, "year", "lever")["min"] == 100


def test_text_mentions_amount():
    assert text_mentions_amount("from $154,000-$193, 000 per year", 154000)
    assert text_mentions_amount("pay $45/hr", 45) and not text_mentions_amount("45 positions", 45)
    assert not text_mentions_amount("competitive pay", 154000)


GREENHOUSE_JOB = {
    "id": 8200001, "title": "Backend Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/8200001",
    "location": {"name": "Toronto, ON"}, "first_published": "2026-09-20T12:00:00-04:00", "content": "<p>Role. Base pay $166,000 - $195,000.</p>",
    "pay_input_ranges": [{"min_cents": 16600000, "max_cents": 19500000, "currency_type": "USD", "title": "Annual Base Salary Range:", "blurb": "<p>caveat</p>"}],
}


def greenhouse(jobs):
    return GreenhouseClient(http_client=FakeHttp({"jobs": jobs})).fetch_jobs("Acme", "acme")


def test_greenhouse_pay_ranges_become_structured_compensation_without_touching_the_description():
    client = GreenhouseClient(http_client=FakeHttp({"jobs": [GREENHOUSE_JOB]}))
    job = client.fetch_jobs("Acme", "acme").jobs[0]
    assert "pay_transparency=true" in client.http_client.urls[0][0]
    assert job.compensation["compensationTierSummary"] == "$166K – $195K" and job.compensation["interval"] == "year"
    assert job.raw_description.startswith(GREENHOUSE_JOB["content"])
    assert job.raw_description.count("<p>caveat</p>") == 1
    existing = dict(GREENHOUSE_JOB, content=GREENHOUSE_JOB["content"] + "<p>caveat</p>")
    assert greenhouse([existing]).jobs[0].raw_description.count("<p>caveat</p>") == 1


def test_greenhouse_hourly_multiple_zones_and_mixed_currency():
    hourly = dict(GREENHOUSE_JOB, pay_input_ranges=[{"min_cents": 4000, "max_cents": 4000, "currency_type": "USD", "title": "Hourly Rate:"}])
    assert greenhouse([hourly]).jobs[0].compensation["compensationTierSummary"] == "$40 / hour"
    zones = dict(GREENHOUSE_JOB, pay_input_ranges=[
        {"min_cents": 16600000, "max_cents": 19500000, "currency_type": "USD", "title": "Zone 1"},
        {"min_cents": 14100000, "max_cents": 16500000, "currency_type": "USD", "title": "Zone 2"}])
    comp = greenhouse([zones]).jobs[0].compensation
    assert comp["compensationTierSummary"] == "$141K – $195K · Multiple ranges" and len(comp["ranges"]) == 2
    mixed = dict(GREENHOUSE_JOB, pay_input_ranges=[
        {"min_cents": 16600000, "max_cents": 19500000, "currency_type": "USD", "title": "US"},
        {"min_cents": 9000000, "max_cents": 12000000, "currency_type": "CAD", "title": "CA"}])
    assert greenhouse([mixed]).jobs[0].compensation is None
    assert greenhouse([{k: v for k, v in GREENHOUSE_JOB.items() if k != "pay_input_ranges"}]).jobs[0].compensation is None


def test_unseen_workday_or_amazon_employer_is_never_marked_verified():
    """Generic discovery only exists for ATS boards that publish a logo; everyone else stays honestly unresolved."""
    from unittest.mock import patch

    from ingestion.company_resolver import resolve_company_branding

    with patch("ingestion.company_resolver.requests.get", side_effect=AssertionError("no network for Workday/Amazon")):
        for name, ats, ident in [("Brand New Bank Corp", "workday", "newbank.wd3/External"), ("Amazon Web Sub Unit", "amazon", "amazon")]:
            branding = resolve_company_branding(name, ats_type=ats, identifier=ident)
            assert branding["logo_status"] == "unresolved"
            assert branding["logo_url"] is None and branding["logo_source_url"] is None


def test_greenhouse_does_not_guess_interval_or_combine_incompatible_intervals():
    for amount in (4000, 16000000):
        row = {"min_cents": amount, "max_cents": amount, "currency_type": "CAD", "title": "Base pay"}
        comp = greenhouse([dict(GREENHOUSE_JOB, pay_input_ranges=[row])]).jobs[0].compensation
        assert "interval" not in comp
    rows = [{"min_cents": 4000, "max_cents": 5000, "currency_type": "CAD", "title": "Hourly pay"},
            {"min_cents": 9000000, "max_cents": 10000000, "currency_type": "CAD", "title": "Annual pay"}]
    assert greenhouse([dict(GREENHOUSE_JOB, pay_input_ranges=rows)]).jobs[0].compensation is None
