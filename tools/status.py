#!/usr/bin/env python3
"""Planned versus actual pages per topic. Run after build.py and lint_layout.py."""
import json, pathlib, yaml

R = pathlib.Path(__file__).resolve().parent.parent
cur = yaml.safe_load((R / "tools/curriculum.yaml").read_text())["folders"]
rep = json.loads((R / "tools/report.json").read_text()) if (R / "tools/report.json").exists() else {}
pg = json.loads((R / "tools/pages.json").read_text()) if (R / "tools/pages.json").exists() else {}
tp = ta = 0
print(f"{'folder':30s} {'plan':>5} {'A4 now':>7} {'sections':>9} {'concepts':>9} {'diagrams':>9} {'code':>5}  progress")
for f in cur:
    s = f["slug"]; r = rep.get(s, {}); a = pg.get(s, 0) if r.get("sections") else 0; tp += f["pages"]; ta += a
    bar = "#" * min(20, round(20 * a / f["pages"])) if f["pages"] else ""
    print(f"{s:30s} {f['pages']:>5} {a:>7} {r.get('sections',0):>9} {r.get('concepts',0):>9} {r.get('diagrams',0):>9} {r.get('code',0):>5}  {bar}")
print(f"{'TOTAL':30s} {tp:>5} {ta:>7}   ({100*ta/tp:.0f}% of the planned A4 pages)")
