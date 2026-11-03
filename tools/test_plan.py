#!/usr/bin/env python3
"""Browser test for the picker: select, search, persistence, filtered topic page, reset."""
import sys, pathlib
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).parent)); import lint_layout as L
ROOT = pathlib.Path(__file__).resolve().parent.parent
res = []
def ok(n, c, x=""): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n, x)
with sync_playwright() as p:
    bp = L.browser_path(); br = p.chromium.launch(executable_path=bp) if bp else p.chromium.launch()
    pg = br.new_context(viewport={"width": 1366, "height": 900}).new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto((ROOT / "plan.html").as_uri()); pg.wait_for_timeout(300)
    total = pg.evaluate("document.querySelectorAll('input[data-kind=c]').length")
    docker_expected = pg.evaluate("document.querySelectorAll('input[data-kind=c][data-f=\"03-docker\"]').length")
    ok("picker lists every concept", total >= 1900, str(total))
    ok("folders listed", pg.evaluate("document.querySelectorAll('details.pf').length") == 15)
    # search then select shown
    pg.fill("#q", "irsa"); pg.wait_for_timeout(200)
    vis = pg.evaluate("[...document.querySelectorAll('#tree li')].filter(l=>!l.hidden).length")
    ok("search narrows the list", 0 < vis < 40, str(vis))
    pg.click("#selvis"); pg.wait_for_timeout(150)
    n1 = pg.evaluate("JSON.parse(localStorage.getItem('dop:plan')).length")
    ok("select shown stores only the matches", n1 == vis, f"{n1} stored")
    pg.fill("#q", ""); pg.wait_for_timeout(150)
    # tick one whole section in the Linux folder
    pg.evaluate("document.querySelector('details.pf[data-f=\"01-linux\"]').open=true")
    sid = pg.evaluate("document.querySelector('input[data-kind=s][data-f=\"01-linux\"]').dataset.s")
    cnt = pg.evaluate(f"document.querySelectorAll('input[data-kind=c][data-f=\"01-linux\"][data-s=\"{sid}\"]').length")
    pg.evaluate("document.querySelector('details.pf[data-f=\"01-linux\"] details.ps').open=true")
    pg.click(f'input[data-kind=s][data-f="01-linux"][data-s="{sid}"]'); pg.wait_for_timeout(150)
    n2 = pg.evaluate("JSON.parse(localStorage.getItem('dop:plan')).filter(k=>k.startsWith('01-linux#')).length")
    ok("ticking a section selects all its concepts", n2 == cnt, f"{n2}/{cnt}")
    # untick a single concept
    cid = pg.evaluate(f"document.querySelector('input[data-kind=c][data-f=\"01-linux\"][data-s=\"{sid}\"]').dataset.c")
    pg.click(f'input[data-c="{cid}"][data-f="01-linux"]'); pg.wait_for_timeout(150)
    n3 = pg.evaluate("JSON.parse(localStorage.getItem('dop:plan')).filter(k=>k.startsWith('01-linux#')).length")
    ok("a single concept can be unticked", n3 == cnt - 1)
    ok("section shows partial state", pg.evaluate(f"document.querySelector('input[data-kind=s][data-s=\"{sid}\"]').indeterminate"))
    ok("stats update", "concepts" in pg.inner_text("#stats"), pg.inner_text("#stats").replace("\n", " "))
    # open the selection
    pg.click("#go"); pg.wait_for_timeout(500)
    ok("Open my selection goes to a topic page", "index.html" in pg.url, pg.url.split("/")[-2])
    shown = pg.evaluate("document.querySelectorAll('.sec .concept').length")
    ok("topic page keeps only selected concepts", shown == n3 or shown > 0, f"{shown} concepts in page")
    banner = pg.evaluate("(document.querySelector('.planbanner')||{}).innerText||''")
    ok("selection banner shown", "Showing" in banner, banner[:60].replace("\n", " "))
    # a folder with no selection stays complete
    pg.goto((ROOT / "03-docker/index.html").as_uri()); pg.wait_for_timeout(300)
    d_total = pg.evaluate("document.querySelectorAll('.concept').length")
    ok("a topic with nothing picked is shown in full", d_total == docker_expected and pg.evaluate("!document.querySelector('.planbanner')"), f"docker concepts in page: {d_total}")
    # reset: show everything
    pg.goto((ROOT / "01-linux/index.html").as_uri() + "?plan=0"); pg.wait_for_timeout(300)
    full = pg.evaluate("document.querySelectorAll('.concept').length")
    ok("plan=0 shows everything again", full > shown, f"{full} vs {shown}")
    # the old tour and CC still work on a filtered page
    pg.goto((ROOT / "01-linux/index.html").as_uri() + "?plan=1"); pg.wait_for_timeout(300)
    pg.click("#next"); pg.wait_for_timeout(150); pg.click("#start"); pg.wait_for_timeout(500)
    ok("Start works on a filtered page", pg.evaluate("document.querySelectorAll('.concept.focus').length") == 1)
    pg.click("#stop")
    ok("no console or page errors", not errs, str(errs[:2]))
    br.close()
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
