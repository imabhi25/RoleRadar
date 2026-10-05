"""Did the repair keep what the sources published?   python scripts/public_data_audit/preservation.py BEFORE_DIR AFTER_DIR

For every job in both crawls: untouched fields are identical; the compensation the source published can be recovered exactly from the
stored value (unwrap_source_compensation); every location label that was published is still there, as the label or as raw_location,
except entries that are not places (listed). Exit status 1 if anything else differs.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ingestion.compensation import unwrap_source_compensation  # noqa: E402

before, after = ({d["job_id"]: d for d in json.loads((Path(p) / "detail.json").read_text())} for p in sys.argv[1:3])
common = sorted(set(before) & set(after))
FIELDS = ["title", "company", "description", "source_name", "source_url", "company_apply_url", "role_type", "term_season", "term_year", "posted_at", "created_at", "skills", "experience_level"]
bad = {"fields": [], "compensation": [], "locations": []}
dropped = []
for j in common:
    b, a = before[j], after[j]
    for f in FIELDS:
        va, vb = a.get(f), b.get(f)
        if f == "skills":
            va, vb = sorted(va or []), sorted(vb or [])
        if f in ("posted_at", "created_at") and va and vb:
            from datetime import datetime
            va, vb = (datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (va, vb))
        if va != vb:
            bad["fields"].append((j, f))
    if unwrap_source_compensation(a.get("compensation")) != (b.get("compensation") or None):
        bad["compensation"].append(j)
    published = {str(e.get("raw_location") or e.get("source_location") or e["location"]) for e in b["locations"]}
    kept = {str(e["location"]) for e in a["locations"]} | {str(x) for e in a["locations"] for x in [e.get("raw_location"), e.get("source_location"), *(e.get("also_published") or [])] if x}
    for label in published - kept:
        if re.fullmatch(r"(?i)\(?\s*(?:offsite|home|remote\s*[-–]?\s*friendly.*|travel[- ]required\)?)\s*", label):
            dropped.append((j, label))
        else:
            # a published label of a repaired multi-part entry is kept as the label of one of its parts
            bad["locations"].append((j, label))
print(f"{len(common)} jobs in both crawls")
print(f"untouched fields identical: {len(common) * len(FIELDS) - len(bad['fields'])} of {len(common) * len(FIELDS)}  differences: {bad['fields'][:5]}")
print(f"source compensation recoverable exactly: {len(common) - len(bad['compensation'])} of {len(common)}  differences: {bad['compensation'][:5]}")
print(f"published location labels kept (label or raw_location): differences {len(bad['locations'])} {bad['locations'][:8]}")
print(f"entries dropped because they are not places: {len(dropped)}  {sorted({d[1] for d in dropped})}")
sys.exit(1 if any(bad.values()) else 0)
