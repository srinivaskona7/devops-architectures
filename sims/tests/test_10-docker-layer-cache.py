import sys,os
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..', 'tools'))
from lint_layout import browser_path
from playwright.sync_api import sync_playwright
SLUG='10-docker-layer-cache'
FILE=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),SLUG+'.html')
res=[]
def check(n,c):
    res.append(bool(c));print(('PASS ' if c else 'FAIL ')+n)
def overflow(pg):return pg.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
def answer_all(pg):
    asked=right=guard=0;n=pg.evaluate('SIM.steps.length')
    while pg.evaluate('SIM.idx')<n-1 and guard<3000:
        guard+=1
        if pg.locator('#quiz:not([hidden]) .opts button:not([disabled])').count():
            ci=pg.evaluate('SIM.steps[SIM.pending].predict.correct');no=pg.evaluate('SIM.steps[SIM.pending].predict.opts.length')
            pick=ci if asked%2==0 else (ci+1)%no
            pg.locator('#quiz .opts button').nth(pick).click();asked+=1;right+=(pick==ci)
        else: pg.click('#btnStep')
    return asked,right
def ev(pg,ch,order='dep',line='deps'):
    return pg.evaluate('([c,o,l])=>{cfg.change=c;cfg.line=l;return evaluate(o)}',[ch,order,line])
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=browser_path())
    pg=b.new_page(viewport={'width':1366,'height':900});errs=[];reqs=[]
    pg.on('console',lambda m:errs.append(m.text) if m.type=='error' else None)
    pg.on('pageerror',lambda e:errs.append(str(e)))
    pg.on('request',lambda r:reqs.append(r.url) if not r.url.startswith(('file:','data:')) else None)
    pg.goto('file://'+FILE)
    check('meta tags',all(pg.locator('meta[name="%s"]'%m).count()==1 for m in ['sim:title','sim:topic','sim:summary','sim:concepts']) and pg.get_attribute('meta[name="sim:topic"]','content')=='03-docker')
    check('back link ../index.html',pg.get_attribute('a.back','href')=='../index.html')
    check('theme set',pg.evaluate('document.documentElement.getAttribute("data-theme")') in ('dark','light'))
    check('buttons >=36px',pg.evaluate('[...document.querySelectorAll("button")].every(b=>{const r=b.getBoundingClientRect();return r.height>=36&&r.width>=36})'))
    check('simplifications note + examples labelled','Simplifications' in pg.inner_text('.simp') and 'example' in pg.inner_text('.simp'))
    # cache rule correctness (pure function)
    r=ev(pg,'src');st=[x['st'] for x in r['rows']]
    check('rule: source change (dep-first) -> hit,hit,hit,miss,miss,miss',st==['hit','hit','hit','miss','miss','miss'])
    r=ev(pg,'dep');check('rule: manifest change -> first miss at COPY manifest, all after miss',[x['st'] for x in r['rows']]==['hit']+['miss']*5)
    r=ev(pg,'none');check('rule: no change -> all hits, total 0',all(x['st']=='hit' for x in r['rows']) and r['total']==0)
    r=ev(pg,'line','dep','build');check('rule: edit RUN build -> hits above, miss build and CMD',[x['st'] for x in r['rows']]==['hit']*4+['miss']*2)
    r=ev(pg,'line','dep','from');check('rule: edit FROM -> everything rebuilds',all(x['st']=='miss' for x in r['rows']))
    r=ev(pg,'src','naive');check('naive: source change rebuilds from COPY . . (install included)',[x['st'] for x in r['rows']]==['hit']+['miss']*4)
    n=ev(pg,'src','naive');d=ev(pg,'src','dep')
    check('totals: naive 75.5 vs dep-first 30.5 for source change (defaults)',abs(n['total']-75.5)<1e-9 and abs(d['total']-30.5)<1e-9)
    check('dep change: both orders equal-ish (dep-first 75.7, naive 75.5)',abs(ev(pg,'dep','dep')['total']-75.7)<1e-9 and abs(ev(pg,'dep','naive')['total']-75.5)<1e-9)
    check('multi-stage sizes computed (1370 vs 315)',pg.evaluate('(()=>{const m=msz();return m.single===1370&&m.multi===315})()'))
    pg.evaluate('cfg.change="src";cfg.line="deps"');pg.select_option('#chg','src')
    init_state=pg.inner_html('#state');init_say=pg.inner_text('#say')
    for ch,order in [('src','dep'),('dep','dep'),('src','naive')]:
        pg.select_option('#chg',ch);pg.select_option('#ord',order)
        a,rr=answer_all(pg);L=pg.evaluate('SIM.steps.length')
        check('[%s/%s] reached end (%d steps)'%(ch,order,L),pg.evaluate('SIM.idx')==L-1)
        check('[%s/%s] 3-5 predictions (%d)'%(ch,order,a),3<=a<=5)
        check('[%s/%s] score chip %d/%d'%(ch,order,rr,a),pg.inner_text('#score')=='Score %d/%d'%(rr,a) and 0<rr<a)
        check('[%s/%s] summary has score'%(ch,order),('Prediction score: %d / %d'%(rr,a)) in pg.inner_text('#summary'))
        check('[%s/%s] every step has explanation'%(ch,order),pg.evaluate('SIM.steps.every(s=>s.say&&s.say.length>10)'))
        check('[%s/%s] final view shows comparison, multi-stage and cache mounts'%(ch,order),all(w in pg.inner_text('#state') for w in ['Reorder for better caching','Multi-stage final image size','cache mounts','registry cache']))
        for w,h in [(390,844),(1366,900)]:
            pg.set_viewport_size({'width':w,'height':h});pg.wait_for_timeout(100)
            check('[%s/%s] no h-overflow at %d (%d)'%(ch,order,w,overflow(pg)),overflow(pg)<=0)
        pg.keyboard.press('ArrowLeft');check('Left = back',pg.evaluate('SIM.idx')==L-2)
        pg.keyboard.press('ArrowRight');check('Right = step',pg.evaluate('SIM.idx')==L-1)
        pg.keyboard.press('r')
        check('Reset idx/score/summary',pg.evaluate('SIM.idx')==-1 and pg.inner_text('#score')=='Score 0/0' and pg.locator('#summary:not([hidden])').count()==0)
    pg.select_option('#chg','src');pg.select_option('#ord','dep');pg.keyboard.press('r')
    check('Reset state/say restored',pg.inner_html('#state')==init_state and pg.inner_text('#say')==init_say)
    # Try it: durations
    pg.fill('[data-d="deps"]','100')
    check('Try it: editing npm ci duration changes naive total (130.5)',abs(pg.evaluate('evaluate("naive").total')-130.5)<1e-9)
    pg.click('#durReset');check('Restore defaults',pg.evaluate('cfg.dur.deps')==45)
    pg.select_option('#chg','line');check('line select enabled only for Dockerfile line',not pg.is_disabled('#linesel'))
    pg.select_option('#linesel','build')
    pg.uncheck('#predict')
    for _ in range(14):pg.keyboard.press('ArrowRight')
    check('Dockerfile-line change shows hit/miss badges',pg.locator('.badge.hit').count()>=1 and pg.locator('.badge.miss').count()>=1)
    pg.select_option('#chg','none');pg.check('#predict')
    # play/pause
    pg.uncheck('#predict');pg.select_option('#speed','2');pg.keyboard.press(' ');pg.wait_for_timeout(1800)
    played=pg.evaluate('SIM.idx');pg.keyboard.press(' ');pg.wait_for_timeout(800)
    check('Space plays then pauses (idx %d)'%played,played>=1 and pg.evaluate('SIM.idx')<=played+1)
    check('no console/page errors %s'%errs[:2],not errs)
    check('no network requests',not reqs)
    b.close()
print('%d/%d passed'%(sum(res),len(res)))
sys.exit(0 if all(res) else 1)
