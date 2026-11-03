#!/usr/bin/env python3
"""Assemble the GitHub Pages artifact in _site/ and fail if any relative link inside it does not resolve.
Only built pages, assets and simulators are published; sources, tests and tooling are not."""
import pathlib, re, shutil, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir()

def put(src):
    dst = OUT / src.relative_to(ROOT); dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)

for f in ROOT.glob("*.html"): put(f)
for d in sorted(ROOT.glob("[0-9][0-9]-*")):
    if (d / "index.html").exists(): put(d / "index.html")
for top in ("assets", "sims"):
    for f in (ROOT / top).rglob("*"):
        if f.is_file() and not {"__pycache__", "tests"} & set(f.parts): put(f)
(OUT / ".nojekyll").write_text("")          # serve files as they are, no Jekyll processing

SKIP = re.compile(r"^(https?:|mailto:|data:|javascript:|#|$)")
bad, pages, links = [], 0, 0
for page in OUT.rglob("*.html"):
    pages += 1
    for m in re.finditer(r'(?:href|src)="([^"]*)"', page.read_text(errors="ignore")):
        ref = m.group(1)
        if SKIP.match(ref): continue
        links += 1
        target = (page.parent / ref.split("#")[0].split("?")[0]).resolve()
        if target.is_dir(): target = target / "index.html"
        if not target.exists() or OUT not in target.parents and target != OUT:
            bad.append(f"{page.relative_to(OUT)} -> {ref}")
size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
print(f"packaged {pages} pages, checked {links} relative links, {size:.1f} MB")
if bad:
    print("BROKEN LINKS:"); [print("  ", b) for b in bad[:40]]; sys.exit(1)
