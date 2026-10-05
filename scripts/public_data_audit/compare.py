"""Before/after table from two analyze.py runs:  python scripts/public_data_audit/compare.py BEFORE_DIR AFTER_DIR"""
import json
import sys
from pathlib import Path

before, after = (json.loads((Path(d) / "metrics.json").read_text()) for d in sys.argv[1:3])
rows = [(k, v["count"], after[k]["count"], v.get("note", "")) for k, v in before.items() if isinstance(v, dict) and "count" in v and k in after]
width = max(len(r[0]) for r in rows)
print(f"{'check':{width}s} {'before':>7s} {'after':>6s}")
for key, b, a, _ in rows:
    print(f"{key:{width}s} {b:7d} {a:6d}{'' if a == b else '  *'}")
print("\nplace labels a reader sees (distinct spellings):")
for place, v in before["place_label_variants_displayed"].items():
    print(f"  {place:14s} {v['distinct']} -> {after['place_label_variants_displayed'][place]['distinct']}")
print("distinct displayed primary locations:", before["profile"]["distinct_displayed_primary_locations"], "->", after["profile"]["distinct_displayed_primary_locations"])
