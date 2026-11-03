#!/usr/bin/env python3
"""Drive a topic page in a real browser: navigation, Start/Stop, subtitles, text mode, diagram replay, persistence."""
import os, sys, pathlib
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).parent)); import lint_layout as L
ROOT = pathlib.Path(__file__).resolve().parent.parent
folder = sys.argv[1] if len(sys.argv) > 1 else "00-roadmap-prerequisites"
res = []
def ok(n, c, x=""): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n, x)
with sync_playwright() as p:
    bp = L.browser_path(); br = p.chromium.launch(executable_path=bp) if bp else p.chromium.launch()
    ctx = br.new_context(viewport={"width": 1366, "height": 900}); pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto((ROOT / folder / "index.html").as_uri()); pg.wait_for_timeout(250)
    nsec = pg.evaluate("document.querySelectorAll('.sec').length")
    ok("overview is shown first", pg.evaluate("document.querySelector('.sec.show').id") == "overview")
    ok("toc lists every section", pg.evaluate("document.querySelectorAll('.toc>li').length") == nsec, f"{nsec} sections")
    pg.click("#next"); pg.wait_for_timeout(120); first = pg.evaluate("document.querySelector('.sec.show').id")
    ok("Next moves to section 1", first != "overview", first)
    pg.click("#next"); pg.wait_for_timeout(120); second = pg.evaluate("document.querySelector('.sec.show').id")
    pg.click("#prev"); pg.wait_for_timeout(120)
    ok("Prev returns", pg.evaluate("document.querySelector('.sec.show').id") == first)
    pg.click(".toc>li:nth-child(3)>a"); pg.wait_for_timeout(120)
    ok("TOC link opens that section", pg.evaluate("document.querySelector('.sec.show').id") != first)
    # diagram replay
    pg.evaluate("location.hash='#'+document.querySelectorAll('.sec')[1].id"); pg.wait_for_timeout(1800)
    ok("a diagram lights nodes on its own", pg.evaluate("document.querySelectorAll('.sec.show .dg .on').length") >= 1)
    # subtitles
    pg.keyboard.press("c"); pg.wait_for_timeout(150)
    ok("CC toggles on (key c)", pg.evaluate("document.documentElement.classList.contains('subs-on')"))
    pg.mouse.wheel(0, 700); pg.wait_for_timeout(400)
    sub = pg.evaluate("(()=>{const s=document.getElementById('subs');return {has:s.classList.contains('has'),vis:getComputedStyle(s).display,t:s.innerText.slice(0,70)}})()")
    ok("subtitle bar shows the concept in view", sub["has"] and sub["vis"] != "none" and len(sub["t"]) > 10, repr(sub["t"]))
    t1 = sub["t"]; t2 = t1
    for _ in range(12):  # concepts can be 1,000 to 1,600 px tall, so keep scrolling until the caption moves
        pg.mouse.wheel(0, 500); pg.wait_for_timeout(250)
        t2 = pg.evaluate("document.getElementById('subs').innerText.slice(0,70)")
        if t2 != t1: break
    ok("subtitle changes as you scroll", t1 != t2)
    # text mode
    pg.keyboard.press("r"); pg.wait_for_timeout(150)
    ok("text mode toggles on (key r)", pg.evaluate("document.documentElement.classList.contains('text-mode')"))
    lay = pg.evaluate("(()=>{const i=document.querySelector('.inner').getBoundingClientRect();return {w:Math.round(i.width),tiles:getComputedStyle(document.querySelector('.trio')).gridTemplateColumns.split(' ').length}})()")
    ok("text mode narrows the column and stacks the tiles", lay["w"] <= 780 and lay["tiles"] == 1, str(lay))
    pg.reload(); pg.wait_for_timeout(300)
    ok("both choices persist after reload", pg.evaluate("document.documentElement.classList.contains('subs-on') && document.documentElement.classList.contains('text-mode')"))
    pg.keyboard.press("r"); pg.keyboard.press("c")
    # tour
    pg.evaluate("location.hash='#'+document.querySelectorAll('.sec')[1].id"); pg.wait_for_timeout(200)
    pg.click("#start"); pg.wait_for_timeout(500)
    ok("Start focuses a concept", pg.evaluate("document.querySelectorAll('.concept.focus').length") == 1)
    ok("Start disables Start and enables Stop", pg.evaluate("document.getElementById('start').disabled && !document.getElementById('stop').disabled"))
    pg.click("#stop"); pg.wait_for_timeout(200)
    ok("Stop clears focus and re-enables Start", pg.evaluate("document.querySelectorAll('.concept.focus').length") == 0 and pg.evaluate("!document.getElementById('start').disabled"))
    # topics menu
    pg.click(".menu>button"); ok("Topics menu opens", pg.evaluate("document.querySelector('.menu').classList.contains('open')"))
    n_links = pg.evaluate("document.querySelectorAll('.menu a').length"); ok("menu links every topic", n_links == 15, str(n_links))
    ok("no console or page errors", not errs, str(errs[:2]))
    br.close()
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
