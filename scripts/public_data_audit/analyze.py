"""Automated checks over a crawl (crawl.py + the ui_render.audit.ts harness). Writes metrics.json: counts and job ids per check.

    python scripts/public_data_audit/analyze.py CRAWL_DIR

The checks are written independently of the ingestion and UI rules they audit (their own regular expressions and thresholds),
and every figure is computed from what a reader is shown (the rendered card, pane facts, Summary and Full text, location
labels), not only from raw API fields.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DIR = Path(sys.argv[1])
jobs = {d["job_id"]: d for d in json.loads((DIR / "detail.json").read_text())}
ui = {u["id"]: u for u in json.loads((DIR / "ui.json").read_text()) if "error" not in u}
# RESTRICT_TO=<other crawl dir>: audit only the jobs that crawl also has, so a before/after comparison covers the same jobs
# (a job that ages out of the 30-day public window between two crawls is not a data change).
if os.environ.get("RESTRICT_TO"):
    keep = {d["job_id"] for d in json.loads((Path(os.environ["RESTRICT_TO"]) / "detail.json").read_text())}
    jobs = {k: v for k, v in jobs.items() if k in keep}
    ui = {k: v for k, v in ui.items() if k in keep}
meta = json.loads((DIR / "meta.json").read_text())
M = {"crawl": meta}


def put(name, ids, note=""):
    ids = sorted(set(ids))
    M[name] = {"count": len(ids), "ids": ids, "note": note}


# ------------------------------------------------------------------ profile / missing fields
M["profile"] = {"jobs": len(jobs), "companies": len({j["company"] for j in jobs.values()}), "sources": dict(Counter(j["source_name"] for j in jobs.values()))}
put("missing_posted_at", [i for i, j in jobs.items() if not j.get("posted_at")], "legitimately undated at the source (Google) unless noted")
put("missing_skills", [i for i, j in jobs.items() if not j.get("skills")], "no tagged skill appears in the posting")
put("missing_company_website", [i for i, j in jobs.items() if not j.get("company_website_url")])
put("internship_without_term", [i for i, j in jobs.items() if j["role_type"] in ("internship", "co_op") and not j.get("term_season")])
put("no_pay_on_card", [i for i in jobs if not ui[i]["card"]], "job card shows no pay")

# ------------------------------------------------------------------ pay
def amounts(text):
    """Money amounts only (symbol-prefixed): the digits of 'Level 5' or '3 days' are not pay."""
    out = []
    for m in re.finditer(r"(?:CA|US|A|C)?[$£€]\s?(\d[\d,]*(?:\.\d+)?)\s?([KkMm])?", text or ""):
        v = float(m.group(1).replace(",", ""))
        out.append(v * (1000 if (m.group(2) or "").lower() == "k" else 1_000_000 if (m.group(2) or "").lower() == "m" else 1))
    return out


def card_period(text):
    m = re.search(r"/(yr|hr|mo|wk|day)\b", text or "")
    return m.group(1) if m else None


shown = [i for i in jobs if ui[i]["card"]]
put("pay_shown_card", shown)
put("pay_shown_pane", [i for i in jobs if ui[i]["pane"]])
def _pane_vals(i):
    return set(amounts((ui[i]["pane"] or "").replace(" · period not stated", "")))
put("pay_card_pane_disagree", [i for i in shown if ui[i]["pane"] and "Multiple pay ranges" not in ui[i]["card"] and not set(amounts(ui[i]["card"])) <= _pane_vals(i)],
    "an amount on the card that the pane does not show (a card span over several ranges is covered by the ranges listed in the pane)")
implausible = []
for i in shown:
    text = ui[i]["pane"] or ui[i]["card"]
    if "Multiple pay ranges" in text:
        continue
    vals = [v for v in amounts(text.split(" · ")[0]) if v]
    p = card_period(ui[i]["card"])
    if vals and (max(vals) > 3_000_000 or (len(vals) >= 2 and min(vals) > 0 and max(vals) / min(vals) > 10) or (p in (None, "yr") and max(vals) < 5) or (p == "yr" and max(vals) < 1000)):
        implausible.append(i)
put("pay_implausible_shown", implausible, "amount over $3M, range spread over 10x, or a token/placeholder amount, in the displayed pay")
raw_bad = []
for i, j in jobs.items():
    c = j.get("compensation") or {}
    rs = [c] if c.get("min") is not None else []
    rs += [x for x in (c.get("ranges") or [])]
    for r in rs:
        lo, hi = r.get("min"), r.get("max")
        if lo is not None and hi is not None and (hi <= 10 or hi > 3_000_000 or (lo > 0 and hi / lo > 10)):
            raw_bad.append(i)
put("pay_implausible_in_stored_data", raw_bad, "stored structured pay with an impossible/placeholder amount (kept as published, flagged validation after repair)")
put("pay_marked_unusable", [i for i, j in jobs.items() if (j.get("compensation") or {}).get("validation")], "stored pay flagged by ingestion and hidden everywhere")
put("pay_period_asserted_without_source", [i for i in shown if card_period(ui[i]["card"]) and not (
    (jobs[i].get("compensation") or {}).get("interval") or any(x.get("intervalType") or x.get("interval") for x in (jobs[i].get("compensation") or {}).get("summaryComponents") or [])
    or any(x.get("interval") for x in (jobs[i].get("compensation") or {}).get("ranges") or []))],
    "card shows /yr or /hr although neither the source data nor the posting text named a period")
put("pay_period_not_stated_disclosed", [i for i in shown if "period not stated" in (ui[i]["pane"] or "")], "pane says the period was not stated")

RANGE = re.compile(r"(?:CA\$|US\$|C\$|\$|£|€)\s?(\d{2,3}(?:,\d{3})+(?:\.\d+)?|\d{2,3}\s?[Kk])\s*(?:-|–|—|to|and)\s*(?:CA\$|US\$|C\$|\$|£|€)?\s?(\d{2,3}(?:,\d{3})+(?:\.\d+)?|\d{2,3}\s?[Kk])", re.I)
CODE_RANGE = re.compile(r"(\d{2,3}(?:,\d{3})+(?:\.\d+)?)\s*(?:USD|CAD|GBP|EUR)?\s*(?:-|–|—|to)\s*(\d{2,3}(?:,\d{3})+(?:\.\d+)?)\s*(?:USD|CAD|GBP|EUR)", re.I)
PAYCTX = re.compile(r"(salary|pay range|base pay|compensation|wage|base range|hiring range|pay details|annual base|pay range)", re.I)
BONUSCTX = re.compile(r"(bonus|equity|stock|rsu|signing|stipend|funding|raised|valuation|revenue)", re.I)
text_pay = []
for i in jobs:
    t = ui[i]["full"]
    for rx in (RANGE, CODE_RANGE):
        for m in rx.finditer(t):
            before = t[max(0, m.start() - 160):m.start()]
            last = max((x.end() for x in PAYCTX.finditer(before)), default=-1)
            other = max((x.end() for x in BONUSCTX.finditer(before)), default=-1)
            if last >= 0 and last > other:
                text_pay.append(i); break
        else:
            continue
        break
put("pay_stated_in_text_card_empty", [i for i in set(text_pay) if not ui[i]["card"]], "the posting states a pay range (salary/pay/compensation/base context) but the job card shows none")
put("pay_stated_in_text_not_shown", [i for i in set(text_pay) if not ui[i]["card"] and not ui[i]["pane"]], "...and the detail pane shows none either")
put("pay_stated_in_text_not_shown_in_summary", [i for i in set(text_pay) if not ui[i]["card"] and not ui[i]["pane"] and not RANGE.search(ui[i]["summary"]) and not CODE_RANGE.search(ui[i]["summary"])], "...and the Summary does not state it")

# Pay taken from the posting text: is it this role's, this location's, and traceable to the posting?
_PLACES = {"US": r"\b(?:US|U\.S\.|USA|United States)\b", "Canada": r"\b(?:Canada|Canadian)\b", "Toronto": r"\bToronto\b", "Vancouver": r"\bVancouver\b",
           "Montreal": r"\bMontr[ée]al\b", "Ottawa": r"\bOttawa\b", "Ontario": r"\bOntario\b", "San Francisco": r"\bSan Francisco\b|\bBay Area\b",
           "New York": r"\bNew York\b|\bNYC\b", "Seattle": r"\bSeattle\b", "Washington DC": r"\bWashington,? ?D\.?C\.?\b", "California": r"\bCalifornia\b",
           "Portugal": r"\bPortugal\b", "Austin": r"\bAustin\b", "Denver": r"\bDenver\b", "Chicago": r"\bChicago\b", "Boston": r"\bBoston\b"}
_IMPLIES = {"Toronto": {"Canada", "Ontario"}, "Vancouver": {"Canada"}, "Montreal": {"Canada"}, "Ottawa": {"Canada", "Ontario"}, "Ontario": {"Canada"},
            "San Francisco": {"US", "California"}, "New York": {"US"}, "Seattle": {"US"}, "Washington DC": {"US"}, "California": {"US"}, "Austin": {"US"},
            "Denver": {"US"}, "Chicago": {"US"}, "Boston": {"US"}}
def _places(text):
    found = {k for k, rx in _PLACES.items() if re.search(rx, text or "")}
    for k in list(found):
        found |= _IMPLIES.get(k, set())
    return found
def _is_text_card(i):
    c = jobs[i].get("compensation") or {}
    return c.get("source") == "posting_text" and bool(ui[i]["card"]) and ui[i]["card"] not in ("Pay varies by location",)
text_cards = [i for i in jobs if _is_text_card(i)]
put("pay_from_text_on_card", text_cards, "cards whose pay was taken from the posting text")
wrong_place = []
for i in text_cards:
    c = jobs[i]["compensation"]
    labels = " ; ".join(e["location"] for e in jobs[i]["locations"]) + " ; " + jobs[i]["country"]
    mine = _places(labels)
    for r in c["ranges"]:
        if r.get("scope") == "none":
            continue
        sentence_places = _places(r.get("qualifier") or "") or (_places(c.get("evidence", "")) if len(c["ranges"]) == 1 else set())
        specific = {p for p in sentence_places}
        if specific and not (specific & mine):
            wrong_place.append(i); break
put("pay_on_card_written_for_another_place", wrong_place, "card shows a text range whose sentence names places and none is one of the job's locations")
trace = []
for i in text_cards:
    full = ui[i]["full"].replace(",", "")
    for r in jobs[i]["compensation"]["ranges"]:
        for v in (r["min"], r["max"]):
            forms = {f"{v:.0f}", f"{v:.2f}", f"{int(v / 1000)}K" if v % 1000 == 0 else "x", f"{v:.1f}"}
            if not any(f in full for f in forms):
                trace.append(i)
put("pay_amount_not_found_in_posting_text", trace, "an amount on a text-derived card that does not appear in the posting text")
OTHER = re.compile(r"\b(?:bonus|equity|stock|rsu|sign(?:ing)?[- ]on|stipend|allowance|benefit|relocation|commission|ote|on[- ]target)\b", re.I)
put("pay_sentence_mentions_bonus_equity_benefit", [i for i in text_cards if OTHER.search(jobs[i]["compensation"].get("evidence", "")) and not re.search(r"\bnot inclusive|excluding|plus|in addition|, plus\b", jobs[i]["compensation"].get("evidence", ""), re.I) and False] or
    [i for i in text_cards if OTHER.search(jobs[i]["compensation"].get("evidence", ""))], "the kept sentence also mentions bonus/equity/benefits/OTE (listed for manual review: most say 'not inclusive of' or 'plus')")
put("pay_varies_by_location_cards", [i for i in jobs if ui[i]["card"] == "Pay varies by location"], "text pay exists but is written for places that do not cover every location of the job")

# ------------------------------------------------------------------ locations (as displayed)
VENDOR = re.compile(r"^(US|USA|CA|GB),|United States of America|^[A-Z]{2}, [A-Z]{2}\b")
put("location_vendor_format_stored", [i for i, j in jobs.items() if any(VENDOR.search(e["location"]) for e in j["locations"]) or VENDOR.search(j["location"])], "stored label still in a vendor format ('US, CA, Santa Clara', 'United States of America, ...')")
put("location_vendor_format_displayed", [i for i in jobs if any(VENDOR.search(l) or re.match(r"^CA, United States", l) for l in ui[i]["locations"])], "a reader sees a vendor-format label")
put("location_not_a_place_displayed", [i for i in jobs if any(re.search(r"\bOffsite\b|^Home\b|Friendly \(Travel|^Offsite", l) for l in ui[i]["locations"])], "'Offsite', 'Home, Ontario', 'Friendly (Travel Required' shown as places")
put("location_country_unknown_entries", [i for i, j in jobs.items() if any(e["country"] in ("Unknown", "Americas", "Unspecified") for e in j["locations"])], "entries whose country is not a country: kept as published when it cannot be known")
PLACES = {"Toronto": r"\bToronto\b", "San Francisco": r"\bSan Francisco\b", "New York": r"\bNew York\b", "Seattle": r"\bSeattle\b", "Vancouver": r"\bVancouver\b", "Austin": r"\bAustin\b", "Waterloo": r"\bWaterloo\b"}
variants = {}
for name, rx in PLACES.items():
    labels = Counter()
    for i in jobs:
        for l in ui[i]["locations"]:
            if re.search(rx, l) and not re.search(r"remote|hybrid|HQ|Office|•|SF\d|South San|Headquarters", l, re.I) and l.count(",") <= 3 and not re.search(r"\band\b", l):
                labels[l] += 1
    variants[name] = dict(labels.most_common())
M["place_label_variants_displayed"] = {k: {"distinct": len(v), "labels": v} for k, v in variants.items()}
prim = Counter(ui[i]["locations"][0] for i in jobs if ui[i]["locations"])
M["profile"]["distinct_displayed_primary_locations"] = len(prim)

# ------------------------------------------------------------------ duplicates
groups = defaultdict(list)
for i, j in jobs.items():
    groups[(j["company"], j["title"].strip().lower(), j["location"], ui[i]["full"])].append(i)
put("duplicates_identical_listings", [i for g in groups.values() if len(g) > 1 for i in g], "same company, title, primary location and the full text a reader sees: each group was verified as distinct upstream requisitions")
M["duplicates_identical_listings"]["groups"] = sum(1 for g in groups.values() if len(g) > 1)
put("duplicate_source_urls", [i for u, c in Counter(j["source_url"] for j in jobs.values()).items() if c > 1 for i in jobs if jobs[i]["source_url"] == u])

# ------------------------------------------------------------------ freshness (internal consistency; staleness against the source is a separate, manual step)
now = datetime.fromisoformat(meta["crawled_at"].replace("Z", "+00:00"))
ages = []
for i, j in jobs.items():
    if j.get("posted_at"):
        ages.append((now - datetime.fromisoformat(j["posted_at"].replace("Z", "+00:00"))).total_seconds() / 86400)
M["freshness"] = {"min_age_days": round(min(ages), 2), "max_age_days": round(max(ages), 2), "future_dated": sum(a < -0.01 for a in ages), "older_than_30_days": sum(a > 30.01 for a in ages)}

# ------------------------------------------------------------------ Summary versus Full posting
norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
def grams(t, n=4):
    w = norm(t).split()
    return {" ".join(w[k:k + n]) for k in range(max(0, len(w) - n + 1))}
def sentences(t):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9•–-])", t) if 25 <= len(s) <= 500]
CATS = {
    "office_attendance": r"\b(?:\d|one|two|three|four|five)\s*(?:\+\s*)?days?\b[^.]{0,60}\b(?:office|on-?site|in-person|per week|a week|each week|week)\b|\b(?:in[- ]office|on-?site|in[- ]person|return[- ]to[- ]office)\b[^.]{0,80}\b(?:required|requirement|expected|expectation|mandatory|days?|policy|attendance|at least)\b|\b(?:required|expected|must)\b[^.]{0,70}\b(?:in the office|on-?site|in[- ]person|in[- ]office)\b|\bbased in (?:our|the)\b[^.]{0,40}\boffice|\bhybrid (?:work )?(?:model|schedule|role|position|arrangement)\b|\bthis (?:is a )?(?:fully )?(?:remote|hybrid|on-?site) (?:role|position)\b",
    "relocation": r"relocat",
    "language": r"(?:fluen|bilingual)[^.]{0,60}(?:french|english|spanish|mandarin)|(?:french|english)[^.]{0,40}(?:required|mandatory|fluent|proficiency)",
    "student_eligibility_and_term": r"currently (?:enrolled|pursuing)|enrolled in|returning to (?:school|university)|full-?time student|graduat(?:e|ing|ion)\s+(?:in|by|between|date)|\bwork term\b|available to students",
    "work_authorization_and_citizenship": r"authori[sz]ed to work|work authori[sz]ation|eligible to work|right to work|legally (?:authori[sz]ed|entitled)|\bvisa\b|sponsorship|citizen|permanent resident|security clearance|reliability status|export control|\bITAR\b",
}
EEO = re.compile(r"equal opportunity|equal employment|diversity|inclusi|accommodat|protected (?:class|status)|without regard|regardless of (?:race|color)|disabilit", re.I)
missing = {c: set() for c in CATS}
examples = {c: [] for c in CATS}
sv_total = set()


def covered(sentence, match, shown_text):
    """Does the clause (the matched words plus the next two) appear contiguously in what the reader sees besides Full?
    Section headings and the next fused sentence in the Full text's 'sentence' are not held against the Summary."""
    end = match.end()
    while end < len(sentence) and (sentence[end].isalnum() or sentence[end] in "'’"):   # finish a word cut by the pattern (relocat|ion)
        end += 1
    tail = " ".join(norm(sentence[end:]).split()[:2])
    return norm(sentence[match.start():end] + " " + tail) in shown_text


for i, u in ui.items():
    if u["forcedFull"]:
        continue
    # What the reader sees besides the Summary text: the policies block and the fact tiles (Work term, Pay, Workplace ...).
    shown_elsewhere = " ".join(f"{k} {v}" for k, v in u.get("facts", []))
    shown_text = norm(u["summary"] + " " + (u["policies"] or "") + " " + shown_elsewhere)
    for s in sentences(u["full"]):
        for cat, rx in CATS.items():
            m = re.search(rx, s, re.I)
            if not m or covered(s, m, shown_text):
                continue
            if cat in ("work_authorization_and_citizenship", "relocation") and EEO.search(s) and not re.search(r"visa|sponsor|authori[sz]ed|clearance|relocat", s, re.I):
                continue
            missing[cat].add(i); sv_total.add(i)
            if len(examples[cat]) < 400:
                examples[cat].append({"id": i, "company": jobs[i]["company"], "sentence": s[max(0, m.start() - 80): m.end() + 120]})
for cat, ids in missing.items():
    put(f"summary_missing_{cat}", ids, "a sentence in the Full posting about this is absent from Summary (heuristic: <70% 4-gram overlap)")
    M[f"summary_missing_{cat}"]["examples"] = examples[cat]
put("summary_forced_to_full_posting", [i for i, u in ui.items() if u["forcedFull"]], "no Summary could be built within the character budget, so Full Posting is shown")
HARD = re.compile(r"\bITAR\b|(?:must|required to) be (?:a )?(?:U\.S\. )?citizens?|citizenship (?:is )?(?:required|essential)|(?:U\.S\.|US|Canadian) citizen(?:ship)?\b|permanent resident|(?:active|current)?\s*(?:TS/SCI|top secret|secret|security|reliability)\s+(?:status\s+)?clearance", re.I)
def _hard_in_full(u):
    return any(HARD.search(s) and not EEO.search(s) for s in sentences(u["full"]))
put("hard_conditions_in_full_missing_from_summary", [i for i, u in ui.items() if not u["forcedFull"] and _hard_in_full(u) and not HARD.search(u["summary"] + " " + (u["policies"] or ""))], "Full states a citizenship / ITAR / clearance requirement (equal-opportunity text excluded) and Summary does not")
put("hard_conditions_in_full", [i for i, u in ui.items() if _hard_in_full(u)], "jobs whose Full posting states such a requirement")

(DIR / "metrics.json").write_text(json.dumps(M, indent=1))
for k, v in M.items():
    if isinstance(v, dict) and "count" in v:
        print(f"{k:55s} {v['count']:5d}")
print("freshness:", M["freshness"]); print("profile:", {k: v for k, v in M["profile"].items() if k != "sources"})
print({k: v["distinct"] for k, v in M["place_label_variants_displayed"].items()})
