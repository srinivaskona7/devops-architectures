#!/usr/bin/env python3
"""Layout and page-count lint, run in a real browser against the built HTML.

Checks, per section (shown one at a time), at desktop and mobile widths:
  * no horizontal page overflow
  * no text clipped inside diagram nodes, cards, callouts, table cells
  * no two diagram nodes overlap; no sequence message wider than its lanes
  * no code block wider than the viewport without its own scrollbar
  * a concept's three tiles are all present
Then prints the real A4 page count from a print layout.

Usage: python3 tools/lint_layout.py [--folder 01-linux] [--pdf]
"""
import sys, os, glob, json, pathlib, argparse
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = r"""
() => {
  const out = [];
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 };
  const hit = (a, b, m = 2) => a.left < b.right - m && a.right > b.left + m && a.top < b.bottom - m && a.bottom > b.top + m;
  const vw = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > vw + 1) out.push('page scrolls horizontally: ' + document.documentElement.scrollWidth + ' > ' + vw);
  const sec = document.querySelector('.sec.show'); if (!sec) return ['no visible section'];
  sec.querySelectorAll('.nd,.tile,.callout,.opt>div,th,td,.msg,.nt,.sc,.cmp>div,.ll').forEach(e => {
    if (!vis(e)) return;
    if (e.scrollWidth > e.clientWidth + 2 && getComputedStyle(e).overflowX !== 'auto') out.push('text overflow-x in <' + e.className + '> "' + (e.textContent || '').trim().slice(0, 36) + '"');
    if (e.scrollHeight > e.clientHeight + 2 && getComputedStyle(e).overflowY === 'hidden') out.push('text clipped in <' + e.className + '> "' + (e.textContent || '').trim().slice(0, 36) + '"');
  });
  sec.querySelectorAll('.dg').forEach(dg => {
    const ns = [...dg.querySelectorAll('.nd,.msg,.nt,.cmp>div')].filter(vis);
    for (let i = 0; i < ns.length; i++) {
      const a = ns[i].getBoundingClientRect();
      const inScroll = ns[i].closest('.seqwrap');
      if (!inScroll && (a.right > vw + 1 || a.left < -1)) out.push('diagram node off-screen: "' + ns[i].textContent.trim().slice(0, 30) + '"');
      const box = dg.getBoundingClientRect();
      if (!inScroll && (a.right > box.right + 1 || a.left < box.left - 1)) out.push('diagram node outside its frame: "' + ns[i].textContent.trim().slice(0, 30) + '"');
      for (let j = i + 1; j < ns.length; j++) {
        if (ns[i].contains(ns[j]) || ns[j].contains(ns[i])) continue;
        if (ns[i].classList.contains('msg') && ns[j].classList.contains('msg') && ns[i].parentElement === ns[j].parentElement) { if (hit(a, ns[j].getBoundingClientRect(), 3)) out.push('two sequence messages overlap: "' + ns[i].textContent.trim().slice(0, 20) + '" / "' + ns[j].textContent.trim().slice(0, 20) + '"'); continue }
        if (hit(a, ns[j].getBoundingClientRect(), 3)) out.push('diagram nodes overlap: "' + ns[i].textContent.trim().slice(0, 24) + '" x "' + ns[j].textContent.trim().slice(0, 24) + '"');
      }
    }
    dg.querySelectorAll('.msg').forEach(m => {
      const t = m.getBoundingClientRect(), row = m.parentElement.getBoundingClientRect();
      if (t.height > 64) out.push('sequence label wraps over 3 lines: "' + m.textContent.trim().slice(0, 40) + '"');
    });
  });
  sec.querySelectorAll('.code pre').forEach(p => { if (!vis(p)) return; if (p.scrollWidth > p.clientWidth + 2 && getComputedStyle(p).overflowX !== 'auto') out.push('code block overflows without scrollbar') });
  sec.querySelectorAll('.concept').forEach(c => { if (c.classList.contains('lab')) return; const t = c.querySelectorAll('.tile').length; if (t !== 3) out.push('concept has ' + t + ' tiles: ' + c.querySelector('h3').textContent.slice(0, 40)); if (!c.querySelector('.dg')) out.push('concept has no diagram: ' + c.querySelector('h3').textContent.slice(0, 40)) });
  sec.querySelectorAll('img').forEach(i => { if (!i.complete || i.naturalWidth === 0) out.push('broken image ' + i.src) });
  return out;
}
"""


def browser_path():
    """Use $CHROMIUM if set; else Playwright's own; else the newest cached headless shell (local convenience)."""
    if os.environ.get("CHROMIUM"): return os.environ["CHROMIUM"]
    c = sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell")))
    return c[-1] if c else None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--folder"); ap.add_argument("--pdf", action="store_true"); ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    folders = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and p.name[:2].isdigit() and (p / "index.html").exists())
    if a.folder: folders = [f for f in folders if f == a.folder]
    problems = 0; total_sections = 0; pages = {}
    with sync_playwright() as p:
        try: br = p.chromium.launch()
        except Exception:
            bp = browser_path()
            if not bp: raise
            br = p.chromium.launch(executable_path=bp)
        for f in folders:
            url = (ROOT / f / "index.html").as_uri()
            for label, vp in (("desktop", {"width": 1366, "height": 900}), ("mobile", {"width": 390, "height": 844})):
                if a.quick and label == "mobile": continue
                pg = br.new_page(viewport=vp); errs = []
                pg.on("pageerror", lambda e: errs.append("js: " + str(e)))
                pg.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None)
                pg.goto(url); pg.wait_for_timeout(120)
                ids = pg.evaluate("[...document.querySelectorAll('.sec')].map(s=>s.id)")
                for sid in ids:
                    pg.evaluate(f"location.hash='#{sid}'"); pg.wait_for_timeout(40)
                    r = pg.evaluate(JS)
                    pg.evaluate("document.querySelectorAll('.dg[data-anim]').forEach(d=>d.querySelectorAll('[data-s]').forEach(e=>e.classList.add('on')))")
                    r += [x for x in pg.evaluate(JS) if x not in r]
                    total_sections += (label == "desktop")
                    if r:
                        problems += len(set(r)); print(f"[{f} {label} #{sid}]"); [print("   -", x) for x in sorted(set(r))[:8]]
                for e in errs: problems += 1; print(f"[{f} {label}] {e}")
                pg.close()
            if a.pdf or True:
                pg = br.new_page(viewport={"width": 1100, "height": 900})
                pg.goto(url + "?print=1"); pg.wait_for_timeout(200); pg.emulate_media(media="print")
                out = ROOT / "tools" / f"_{f}.pdf"
                pg.pdf(path=str(out), format="A4", margin={"top": "14mm", "bottom": "14mm", "left": "14mm", "right": "14mm"}, print_background=True)
                import re
                n = len(re.findall(rb"/Type\s*/Page[^s]", out.read_bytes())); pages[f] = n; out.unlink(); pg.close()
        br.close()
    print(f"\nsections checked (desktop): {total_sections} | layout problems: {problems}")
    print("A4 pages per folder (this run):", json.dumps(pages)); print("A4 pages in this run:", sum(pages.values()))
    pj = ROOT / "tools/pages.json"
    merged = json.loads(pj.read_text()) if pj.exists() else {}
    merged.update(pages); pj.write_text(json.dumps(merged, indent=1))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
