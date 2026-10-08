"""Read-only crawl of a RoleRadar API (production or a local replica) into JSON files for analyze.py.

    python scripts/public_data_audit/crawl.py https://jobber-mauve.vercel.app OUT_DIR

Only GET requests to the public job endpoints are made. Nothing is written except OUT_DIR.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def get(base, path, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(base.rstrip("/") + path, headers={"User-Agent": "roleradar-data-audit/1"})
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def main(base, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    listing, offset = [], 0
    while True:
        page = get(base, f"/api/jobs?limit=100&offset={offset}&sort=newest")
        listing.extend(page["jobs"])
        offset += 100
        if offset >= page["total"] or not page["jobs"]:
            break
    ids = [job["job_id"] for job in listing]
    with ThreadPoolExecutor(8) as pool:
        details = list(pool.map(lambda j: get(base, "/api/jobs/" + urllib.parse.quote(j, safe="")), ids))
    (out / "list.json").write_text(json.dumps(listing))
    (out / "detail.json").write_text(json.dumps(details))
    (out / "companies.json").write_text(json.dumps(get(base, "/api/companies")))
    (out / "filters.json").write_text(json.dumps(get(base, "/api/jobs/filters")))
    health = {}
    try:
        health = get(base, "/api/health")
    except Exception:
        pass
    (out / "meta.json").write_text(json.dumps({"base": base, "crawled_at": started, "jobs": len(ids), "health": health}))
    print(f"{len(ids)} jobs, {len(details)} details from {base} at {started}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
