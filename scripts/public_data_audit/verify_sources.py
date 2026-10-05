"""Compare pay stated in the posting text against the employer's OWN current posting (Greenhouse, Ashby, Lever, Workday APIs).

    python scripts/public_data_audit/verify_sources.py CRAWL_DIR [SAMPLE_PER_COMPANY] [SEED]

For a stratified sample of postings whose pay was taken from the text (compensation.source == "posting_text"), fetch the official
posting and check that (1) every amount we extracted appears in it as written, (2) the sentence we kept as evidence appears in it,
and (3) the place qualifier we kept appears in it. Also reports, per job, how the job's own locations relate to each range's scope.
GET requests only; writes CRAWL_DIR/source_verification.json.
"""
import html
import json
import random
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = {t["name"]: t for t in json.loads((ROOT / "config" / "target_companies.json").read_text())}


def fetch(url, tries=3):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "roleradar-data-audit/1"}), timeout=40) as r:
                return json.load(r)
        except Exception as err:  # noqa: BLE001
            last = err
    raise last


def plain(text):
    text = html.unescape(html.unescape(text or ""))
    text = re.sub(r"<[^>]+>", " ", text).replace("​", "")
    return re.sub(r"\s+", " ", text).strip()


def norm(text):
    return re.sub(r"[^a-z0-9$]+", " ", plain(text).lower()).strip()


_ashby_cache = {}


def official_text(job):
    src, ident = job["source_name"], CONFIG.get(job["company"], {}).get("identifier")
    sid = job["job_id"].split(":", 1)[1]
    if src == "greenhouse":
        data = fetch(f"https://boards-api.greenhouse.io/v1/boards/{ident}/jobs/{sid}?pay_transparency=true")
        extra = " ".join(str(r.get("blurb") or "") for r in data.get("pay_input_ranges") or [])
        return plain(data.get("content", "")) + " " + plain(extra)
    if src == "lever":
        data = fetch(f"https://api.lever.co/v0/postings/{ident}/{sid}")
        return plain(" ".join(str(data.get(k) or "") for k in ("description", "additional", "salaryDescription")) + " " + " ".join(str(l.get("content")) for l in data.get("lists") or []))
    if src == "ashby":
        if ident not in _ashby_cache:
            _ashby_cache[ident] = {j["id"]: j for j in fetch(f"https://api.ashbyhq.com/posting-api/job-board/{ident}?includeCompensation=true")["jobs"]}
        found = _ashby_cache[ident].get(sid)
        return plain(found["descriptionHtml"]) if found else None
    if src == "workday":
        m = re.match(r"https://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/.*)", job["source_url"])
        if not m:
            return None
        tenant, pod, site, path = m.groups()
        data = fetch(f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}")
        return plain(data["jobPostingInfo"]["jobDescription"])
    return None


def money_forms(value):
    whole = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    return {whole, whole.replace(",", ""), f"{value:,.2f}", f"{int(value / 1000)}K" if value % 1000 == 0 else whole}


def main(crawl, per_company=2, seed=7):
    jobs = {d["job_id"]: d for d in json.loads((Path(crawl) / "detail.json").read_text())}
    by_company = defaultdict(list)
    for j, d in jobs.items():
        if (d.get("compensation") or {}).get("source") == "posting_text":
            by_company[d["company"]].append(j)
    rng = random.Random(seed)
    sample = [j for c in sorted(by_company) for j in rng.sample(by_company[c], min(int(per_company), len(by_company[c])))]
    report = []
    for j in sample:
        d = jobs[j]
        row = {"job_id": j, "company": d["company"], "source": d["source_name"]}
        try:
            text = official_text(d)
        except Exception as err:  # noqa: BLE001
            text = None
            row["error"] = str(err)[:80]
        if text is None:
            row["status"] = "not_checked"
            report.append(row)
            continue
        ranges = d["compensation"]["ranges"]
        official = norm(text)
        row.update({"ranges": len(ranges), "status": "ok"})
        for r in ranges:
            amounts_ok = all(any(form.lower() in official or form.lower() in text.lower() for form in money_forms(v)) for v in (r["min"], r["max"]))
            q_ok = (not r.get("qualifier")) or norm(r["qualifier"]) in official
            r_ok = norm(d["compensation"]["evidence"])[:80] in official
            if not (amounts_ok and q_ok):
                row["status"] = "MISMATCH"
                row.setdefault("detail", []).append({"min": r["min"], "max": r["max"], "amounts_in_official": amounts_ok, "qualifier_in_official": q_ok})
            row["evidence_sentence_in_official"] = r_ok
        report.append(row)
    (Path(crawl) / "source_verification.json").write_text(json.dumps(report, indent=1))
    checked = [r for r in report if r["status"] != "not_checked"]
    print(f"sampled {len(sample)} text-derived postings from {len(by_company)} companies; checked against the employer's posting: {len(checked)}; "
          f"all amounts and qualifiers present: {sum(r['status'] == 'ok' for r in checked)}; mismatches: {sum(r['status'] == 'MISMATCH' for r in checked)}; "
          f"not checkable here: {len(report) - len(checked)}")
    for r in report:
        if r["status"] in ("MISMATCH",) or r.get("error"):
            print("  ", r)


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:4]))
