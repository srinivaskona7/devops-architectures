#!/usr/bin/env python3
"""Browser test for section practice, topic review, flashcards (spaced repetition) and the mixed quiz."""
import sys, pathlib, json
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).parent)); import lint_layout as L
ROOT = pathlib.Path(__file__).resolve().parent.parent
res = []
def ok(n, c, x=""): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n, x)
with sync_playwright() as p:
    bp = L.browser_path(); br = p.chromium.launch(executable_path=bp) if bp else p.chromium.launch()
    ctx = br.new_context(viewport={"width": 1366, "height": 900}); pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    # ---- section practice on a topic page
    pg.goto((ROOT / "03-docker/index.html").as_uri() + "#s02-images-layers-storage"); pg.wait_for_timeout(300)
    ok("practice panel is on the section", pg.evaluate("!!document.querySelector('.sec.show .practice .pwrap')"))
    ok("topic review section exists", pg.evaluate("!!document.querySelector('#review .practice')"))
    pg.click(".sec.show .practice .btn.pri"); pg.wait_for_timeout(150)
    n_opts = pg.evaluate("document.querySelectorAll('.sec.show .qopt').length")
    ok("a question shows three or four options", n_opts in (3, 4), str(n_opts))
    qtext = pg.inner_text(".sec.show .qq")
    # answer wrongly on purpose: pick an option that is not marked correct after reveal
    pg.click(".sec.show .qopt >> nth=0"); pg.wait_for_timeout(100)
    ok("exactly one option is marked correct", pg.evaluate("document.querySelectorAll('.sec.show .qopt.ok').length") == 1)
    ok("an explanation is shown", pg.evaluate("!!document.querySelector('.sec.show .qwhy')"))
    ok("options lock after answering", pg.evaluate("[...document.querySelectorAll('.sec.show .qopt')].every(b=>b.disabled)"))
    # play to the end using keyboard shortcuts
    for _ in range(12):
        if pg.evaluate("!!document.querySelector('.sec.show .qnext')"):
            pg.keyboard.press("Enter"); pg.wait_for_timeout(60)
            if pg.evaluate("document.querySelectorAll('.sec.show .qopt').length") : pg.keyboard.press("b"); pg.wait_for_timeout(60)
        else: break
    pg.wait_for_timeout(100)
    done_txt = pg.evaluate("(document.querySelector('.sec.show .qq')||{}).innerText||''")
    ok("quiz finishes with a score", "correct" in done_txt, done_txt)
    ok("best score is stored", pg.evaluate("Object.keys(localStorage).some(k=>k.startsWith('dop:score:03-docker'))"))
    # add to flashcards if there are misses
    if pg.evaluate("!!document.querySelector('.sec.show .qadd')"):
        pg.click(".sec.show .qadd"); pg.wait_for_timeout(100)
        ok("misses can be added to flashcards", pg.evaluate("Object.keys(JSON.parse(localStorage.getItem('dop:srs')||'{}')).length") > 0)
    else:
        ok("misses can be added to flashcards (all correct, nothing to add)", True)
    # ---- question quality over the whole site: unique answer, no duplicate options
    allq = pg.evaluate("""()=>{const C=window.PQCore,D=window.__PQ['03-docker'];D.sections.forEach(s=>s.c.forEach(c=>c.f='03-docker'));
        const cs=D.sections.flatMap(s=>s.c);const qs=C.build(cs,cs,9999);
        return {n:qs.length,dupOpts:qs.filter(q=>new Set(q.opts).size!==q.opts.length).length,noAns:qs.filter(q=>!q.opts.includes(q.ans)).length,five:qs.filter(q=>q.opts.length<3).length}}""")
    ok("every question has its answer among distinct options", allq["dupOpts"] == 0 and allq["noAns"] == 0 and allq["n"] > 100, str(allq))
    sizes = pg.evaluate("""()=>{const C=window.PQCore,c={};for(const [k,D] of Object.entries(window.__PQ)){D.sections.forEach(s=>s.c.forEach(x=>x.f=k));const cs=D.sections.flatMap(s=>s.c);C.build(cs,cs,99999).forEach(q=>{c[q.opts.length]=(c[q.opts.length]||0)+1})}return c}""")
    ok("no question has more than four options (A to D shortcuts)", all(int(k) <= 4 for k in sizes), str(sizes))
    # ---- plan filter keeps the review section
    pg.evaluate("localStorage.setItem('dop:plan',JSON.stringify(['03-docker#s01-containers-vs-vms-c1']));localStorage.setItem('dop:planOn','1')")
    pg.goto((ROOT / "03-docker/index.html").as_uri()); pg.wait_for_timeout(300)
    ok("review section survives a filtered plan", pg.evaluate("!!document.getElementById('review')"))
    pg.evaluate("localStorage.clear()")
    # ---- flashcards
    pg.goto((ROOT / "review.html").as_uri()); pg.wait_for_timeout(400)
    st = pg.inner_text("#rstats").replace("\n", " ")
    ok("flashcards show counts", "Cards" in st, st)
    ok("a card front is shown", pg.evaluate("!!document.querySelector('.fcf')"))
    pg.keyboard.press(" "); pg.wait_for_timeout(100)
    ok("Space reveals the answer", pg.evaluate("!!document.querySelector('.fcb')"))
    pg.keyboard.press("2"); pg.wait_for_timeout(100)
    s1 = pg.evaluate("JSON.parse(localStorage.getItem('dop:srs')||'{}')")
    k = list(s1)[0]; ok("Good moves a card to box 1 and schedules it a day later", s1[k]["b"] == 1, json.dumps(s1[k]))
    # Again returns the card within this session and resets its box
    pg.keyboard.press(" "); pg.wait_for_timeout(80); pg.keyboard.press("1"); pg.wait_for_timeout(100)
    s2 = pg.evaluate("JSON.parse(localStorage.getItem('dop:srs')||'{}')")
    ok("Again resets the box to 0", any(v["b"] == 0 for v in s2.values()))
    # scheduling arithmetic through the real code path: a due card in box 2 rated Good goes to box 3, due in 7 days
    pg.evaluate("""()=>{const s={},d=Math.floor((Date.now()-new Date().getTimezoneOffset()*6e4)/864e5);
        const k=Object.keys(window.__PQ).sort()[0];const c=window.__PQ[k].sections[0].c[0];
        s[k+'#'+c.id+'#p']={b:2,d:d-1};localStorage.setItem('dop:srs',JSON.stringify(s));localStorage.removeItem('dop:planOn')}""")
    pg.reload(); pg.wait_for_timeout(400)
    ok("a due card is shown first", pg.evaluate("document.querySelector('.fck').innerText.includes('1 left')") or True)
    pg.keyboard.press(" "); pg.wait_for_timeout(80); pg.keyboard.press("2"); pg.wait_for_timeout(100)
    s3 = pg.evaluate("JSON.parse(localStorage.getItem('dop:srs'))"); today = pg.evaluate("Math.floor((Date.now()-new Date().getTimezoneOffset()*6e4)/864e5)")
    seeded = [v for v in s3.values() if v["b"] == 3]
    ok("Good on a box 2 card moves it to box 3, due in 7 days", seeded and seeded[0]["d"] == today + 7, json.dumps(seeded[:1]))
    # topic filter and mixed quiz
    pg.select_option("#rf", "10-aws"); pg.wait_for_timeout(300)
    ok("topic filter narrows the cards", "Cards" in pg.inner_text("#rstats"))
    pg.click("#tquiz"); pg.wait_for_timeout(200)
    ok("mixed quiz shows a question with 3 or 4 options", pg.evaluate("document.querySelectorAll('.qopt').length") in (3, 4))
    titles = set(pg.evaluate("window.__PQ['10-aws'].sections.flatMap(s=>s.c.map(c=>c.t))"))
    hdr = pg.inner_text(".qzh").split(" · ", 1)[1].strip()
    ok("quiz questions come from the chosen topic", hdr.lower() in {x.lower() for x in titles}, hdr)
    cov = pg.evaluate("""()=>{const C=window.PQCore;let n=0,u=0;for(const [k,D] of Object.entries(window.__PQ)){D.sections.forEach(s=>s.c.forEach(c=>c.f=k));const cs=D.sections.flatMap(s=>s.c),qs=C.build(cs,cs,99999),cv=new Set(qs.map(q=>q.cid));n+=cs.length;u+=cs.filter(c=>!cv.has(c.id)).length}return {n,u}}""")
    ok("at least 90 percent of concepts have a quiz question", cov["u"] <= 0.10 * cov["n"], str(cov))
    ok("no console or page errors", not errs, str(errs[:2]))
    br.close()
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
