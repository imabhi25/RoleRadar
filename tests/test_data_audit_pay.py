"""Public-data audit: pay. Placeholder / impossible / contradictory published pay is marked (never edited or shown); pay the
posting text states is added beside what the source published; no pay period or currency is ever guessed.

Fixtures are the real production records named in the audit (tests/fixtures/data_audit_pay_examples.json: the stored
compensation exactly as the adapter produced it, plus the part of the description around the pay statement). The golden
results in data_audit_resolved_compensation.json are also asserted by the front-end tests, so both sides share one contract.
"""
import json
from pathlib import Path

import pytest

from ingestion.compensation import (
    compensation_from_text,
    resolve_compensation,
    structured_problem,
    structured_ranges,
    unwrap_source_compensation,
)
from ingestion.pay_rules import pay_range_problem
from tests.test_ingestion_safety import company, conn  # noqa: F401  (pytest fixtures)
from ingestion.pay_text import extract_pay_ranges, extract_pay_ranges_from_html, html_to_blocks

FIX = Path(__file__).parent / "fixtures"
EXAMPLES = json.loads((FIX / "data_audit_pay_examples.json").read_text())
GOLDEN = json.loads((FIX / "data_audit_resolved_compensation.json").read_text())
RULES = json.loads((FIX / "pay_rules.json").read_text())["cases"]


def resolve(job_id):
    example = EXAMPLES[job_id]
    return resolve_compensation(example["compensation"], example["description_excerpt"], example["locations"])


# ------------------------------------------------------------------------------------------------ rules shared with TS and SQL
@pytest.mark.parametrize("case", RULES, ids=lambda c: f"{c['min']}-{c['max']}-{c['currency']}-{c['interval']}")
def test_plausibility_rules_match_the_shared_fixture(case):
    assert pay_range_problem(case["min"], case["max"], case["currency"], case["interval"]) == case["problem"]


# ------------------------------------------------------------------------------------------------ the reported records
def test_golden_results_are_what_the_code_produces():
    # The front-end tests read this file, so a change here must be deliberate.
    for job_id in EXAMPLES:
        assert json.loads(json.dumps(resolve(job_id))) == GOLDEN[job_id], job_id


def test_coinbase_typo_is_marked_not_corrected_and_the_published_numbers_are_kept():
    result = resolve("greenhouse:8177946")      # $152,405 - $179,300,152 (the official API says max_cents 17930015200)
    assert result["validation"] == {"status": "above_ceiling"}
    assert (result["min"], result["max"]) == (152405.0, 179300152.0)
    assert structured_problem(unwrap_source_compensation(result)) == "above_ceiling"


def test_placeholder_one_to_two_dollars_is_marked_and_never_pay():
    anthropic = resolve("greenhouse:5428950008")
    assert anthropic["validation"] == {"status": "placeholder"} and (anthropic["min"], anthropic["max"]) == (1.0, 2.0)


def test_samsara_placeholder_is_replaced_by_the_real_ranges_the_posting_states_and_the_original_is_kept():
    result = resolve("greenhouse:8223645")
    assert result["source"] == "posting_text"
    assert result["source_structured"]["min"] == 1.0 and result["source_structured"]["max"] == 2.0
    # Each range keeps the place the employer wrote for it, and how far that place reaches over THIS job's locations (Remote - US).
    assert [(r["min"], r["max"], r["qualifier"], r["scope"]) for r in result["ranges"]] == [
        (113645.0, 191000.0, "for the US", "all"), (106675.0, 138050.0, "for Canada", "none"),
    ]
    # Bare "$" for two places is never merged into one span: US and Canadian dollars are not added up.
    assert "min" not in result and "currency" not in result
    assert {r["interval"] for r in result["ranges"]} == {"year"}      # "Annual Base Salary" governs both ranges
    assert "$113,645 - $191,000 for the US and $106,675 - $138,050 for Canada" in result["evidence"]


def test_annual_label_with_hourly_sized_amounts_is_marked_not_reinterpreted_as_hourly():
    result = resolve("greenhouse:8226602")      # "Annual Base Salary $38 - $58 USD": the label and the amount contradict
    assert result["validation"] == {"status": "below_floor"} and result["interval"] == "year"


def test_period_is_taken_from_the_posting_only_where_it_states_one():
    robinhood = resolve("greenhouse:8199744")   # "The expected hourly range for this role ..." above "Toronto, ON $40 - $40 CAD"
    assert robinhood["interval"] == "hour" and robinhood["interval_source"] == "posting_text"
    reddit = resolve("greenhouse:8250389")      # "The base salary range for this position is: $230,000 - $322,000 USD": no period
    assert "interval" not in reddit and (reddit["min"], reddit["max"]) == (230000.0, 322000.0)
    td_salary = resolve("workday:Data-Scientist-II_R_1514106")
    td_coop = resolve("workday:XMLNAME-2027-Spring-Co-op---Global-Technology---Solutions---Data-Engineer_R_1510111")
    assert "interval" not in td_salary and "interval" not in td_coop
    assert td_coop["ranges"][0]["currency"] == "USD" and td_coop["min"] == td_coop["max"] == 30.74


def test_text_pay_for_postings_with_no_usable_structured_pay():
    nvidia = resolve("workday:Senior-Compute-Platform-Engineer--LSF-_JR2023960")   # "124,000 USD - 195,500 USD" style, no symbol
    assert [(r["min"], r["max"], r["currency"], r["label"]) for r in nvidia["ranges"]] == [
        (184000.0, 287500.0, "USD", "for Level 4"), (224000.0, 356500.0, "USD", "for Level 5")]
    assert nvidia["min"] == 184000.0 and nvidia["max"] == 356500.0       # one explicit currency: a span is honest
    notion = resolve("ashby:d82a0b31-59b8-4699-ae8d-6fb3fe47518c")             # Ashby sent no salary component at all
    assert (notion["min"], notion["max"], notion["interval"]) == (150000.0, 168000.0, "year")
    assert notion["source_structured"]["summaryComponents"] == []


def test_base_range_wins_over_on_target_earnings_and_currencies_are_not_blended():
    braze = resolve("greenhouse:8238548")       # base $184,000-$314,079 annually; OTE $204,000-$348,000
    assert (braze["min"], braze["max"], braze["interval"]) == (184000.0, 314079.0, "year")
    mercury = resolve("greenhouse:6184992004")  # "US employees: $200,700-$250,900 USD / Canadian employees: $189,700-$237,100 CAD"
    assert [(r["currency"], r["min"], r["qualifier"]) for r in mercury["ranges"]] == [
        ("USD", 200700.0, "US employees (any location)"), ("CAD", 189700.0, "Canadian employees (any location)")]
    assert "min" not in mercury


def test_believable_source_pay_is_left_exactly_as_published():
    for job_id in ("greenhouse:8243997", "greenhouse:8249493"):
        assert resolve(job_id) == EXAMPLES[job_id]["compensation"]


def test_resolution_is_idempotent_on_every_example():
    for job_id, example in EXAMPLES.items():
        once = resolve_compensation(example["compensation"], example["description_excerpt"], example["locations"])
        assert resolve_compensation(once, example["description_excerpt"], example["locations"]) == once, job_id
        assert unwrap_source_compensation(once) in (example["compensation"], None) or once.get("interval_source"), job_id


# ------------------------------------------------------------------------------------------------ the extractor itself
@pytest.mark.parametrize("text", [
    "We offer a $50,000 - $100,000 equity grant and a signing bonus of $10,000 - $20,000.",
    "Eligible for a bonus between $5,000 and $15,000 each year.",
    "The company raised $100 - $200 million in funding.",
    "3 - 5 years of experience, 2020 - 2025 roadmap, 10 - 20 engineers.",
    "A stipend of $1,000 - $2,000 per month for housing.",
])
def test_equity_bonus_benefits_and_non_money_ranges_are_not_pay(text):
    assert extract_pay_ranges(text) == []


def test_period_and_currency_are_never_guessed():
    [r] = extract_pay_ranges("The salary range for this role is $150,000 - $180,000.")
    assert r["interval"] is None and r["currency"] is None and r["symbol"] == "$"
    [r] = extract_pay_ranges("The hourly pay range is CAD $40 - $55 per hour.")
    assert (r["interval"], r["currency"]) == ("hour", "CAD")
    [r] = extract_pay_ranges("Base salary: £60,000 - £75,000 per annum.")
    assert (r["interval"], r["currency"]) == ("year", "GBP")


def test_inline_markup_does_not_split_a_range_but_block_boundaries_do():
    html = "<p>Pay range:</p><p><span>$200,700</span><span> — </span><span>$250,900 USD</span></p>"
    assert "$200,700 — $250,900 USD" in html_to_blocks(html)
    [r] = extract_pay_ranges_from_html(html)
    assert (r["min"], r["max"], r["currency"]) == (200700.0, 250900.0, "USD")


def test_typo_in_thousands_separator_never_becomes_pay():
    # Real Lever text: "$154,000-$193, 000". The structured Lever range stays; the broken text range is rejected.
    text = "The CAD base salary range for this position is $154,000-$193, 000 (not overtime eligible)."
    assert compensation_from_text(extract_pay_ranges(text)) is None


def test_ashby_and_lever_shapes_are_read_like_greenhouse():
    ashby = {"summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR", "minValue": 220000, "maxValue": 400000, "currencyCode": "USD"},
                                   {"compensationType": "EquityPercentage", "interval": "NONE", "minValue": 1, "maxValue": 2, "currencyCode": None}]}
    assert structured_ranges(ashby) == [{"min": 220000, "max": 400000, "currency": "USD", "interval": "year"}]
    assert structured_problem(ashby) is None
    assert structured_problem({"min": 1, "max": 2, "currency": "USD", "interval": "year"}) == "placeholder"
    assert structured_problem({"summaryComponents": []}) == "no_amount"


# ------------------------------------------------------------------------------------------------ pay is for THIS role and THIS location
@pytest.mark.parametrize("text,qualifier", [
    ("For Washington D.C. based hires: Estimated annual salary of $150,000 - $206,000", "For Washington D.C. based hires"),
    ("The expected base pay range for this position in the Toronto area is CAD $108,000 - CAD $135,000, not inclusive of equity.", "in the Toronto area"),
    ("For Canada based roles, we expect a starting base salary between $131,000 and $191,400.", "For Canada based roles"),
    ("For candidates based in the United States, the pay range for this position is expected to be between $184,000 and $314,079 annually.", "For candidates based in the United States"),
    ("For Ontario, Canada, the base compensation range for this role is $127,000 CAD - $235,000 CAD.", "For Ontario, Canada"),
    ("For any eligible US locations, unless otherwise noted, the base compensation range for this role is $102,200 USD - $189,800 USD.", "For any eligible US locations"),
    ("The San Francisco, CA base pay range for this role is $232,000 - $348,000.", "The San Francisco, CA"),
    ("The United States base range for this position is $151,942–$189,927 USD, plus equity.", "The United States"),
    ("San Francisco: the pay range for this role is $200,000 to $250,000 per year.", "San Francisco"),
])
def test_the_place_the_employer_wrote_for_a_range_is_kept_verbatim(text, qualifier):
    [r] = extract_pay_ranges(text)
    assert r["qualifier"] == qualifier


def test_levels_and_roles_are_labels_not_places():
    [a, b] = extract_pay_ranges("The base salary range is 184,000 USD - 287,500 USD for Level 4, and 224,000 USD - 356,500 USD for Level 5.")
    assert (a["label"], a["qualifier"], b["label"], b["qualifier"]) == ("for Level 4", None, "for Level 5", None)
    [r] = extract_pay_ranges("Pay range:\nAI Engineer: $135,000 - $230,000/per year")
    assert (r["label"], r["qualifier"]) == ("AI Engineer", None)


def test_a_range_written_for_another_place_is_not_this_jobs_pay():
    from ingestion.places import qualifier_scope
    toronto = [{"location": "Toronto, Ontario, Canada", "country": "Canada"}]
    austin_and_dc = [{"location": "Austin, TX, United States", "country": "United States"}, {"location": "Washington DC, US", "country": "United States"}]
    assert qualifier_scope("For candidates based in the United States", toronto) == "none"       # Braze's Toronto posting
    assert qualifier_scope("For Washington D.C. based hires", austin_and_dc) == "some"             # Cloudflare's Austin posting: DC pay only
    assert qualifier_scope("in the Toronto area", toronto) == "all" and qualifier_scope("For Canada based roles", toronto) == "all"
    assert qualifier_scope("The San Francisco, CA", [{"location": "Remote - United States", "country": "United States"}]) == "none"
    assert qualifier_scope("Local", toronto) == "unclear" and qualifier_scope(None, toronto) is None
    # nothing is inferred from the employer's other offices: only the job's own labels count
    assert qualifier_scope("for Canada", [{"location": "Remote - US", "country": "United States"}]) == "none"


def test_scope_is_stored_with_each_range_and_the_sql_filter_skips_other_places(conn, company):
    posting = company.job("braze", compensation=None, raw_location="Toronto, ON",
                          raw_description="<p>For candidates based in the United States, the pay range for this position is expected to be between CA$220,000 and CA$359,213 annually.</p><p>Python and SQL</p>")
    assert company.sync([posting])["status"] == "success"
    with conn.cursor() as cur:
        cur.execute("SELECT compensation, pay_ranges FROM job_postings WHERE job_id=%s", (f"greenhouse:{company.name}braze",))
        compensation, pay_ranges = cur.fetchone()
    [r] = compensation["ranges"]
    assert (r["qualifier"], r["scope"], r["currency"], r["interval"]) == ("For candidates based in the United States", "none", "CAD", "year")
    assert pay_ranges == []        # written for US-based candidates, the job is in Toronto: not this job's pay, so not filterable
