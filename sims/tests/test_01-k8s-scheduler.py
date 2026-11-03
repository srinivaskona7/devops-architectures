import sys,os
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..', 'tools'))
from lint_layout import browser_path
from playwright.sync_api import sync_playwright
SLUG='01-k8s-scheduler'
FILE=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),SLUG+'.html')
res=[]
def check(n,c):
    res.append(bool(c));print(('PASS ' if c else 'FAIL ')+n)
def setv(pg,i,v):pg.evaluate('([i,v])=>{const e=document.getElementById(i);e.value=v;e.dispatchEvent(new Event("input",{bubbles:true}))}',[i,v])
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
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=browser_path())
    pg=b.new_page(viewport={'width':1366,'height':900});errs=[];reqs=[]
    pg.on('console',lambda m:errs.append(m.text) if m.type=='error' else None)
    pg.on('pageerror',lambda e:errs.append(str(e)))
    pg.on('request',lambda r:reqs.append(r.url) if not r.url.startswith(('file:','data:')) else None)
    pg.goto('file://'+FILE)
    check('meta tags',all(pg.locator('meta[name="%s"]'%m).count()==1 for m in ['sim:title','sim:topic','sim:summary','sim:concepts']) and pg.get_attribute('meta[name="sim:topic"]','content')=='04-kubernetes')
    check('back link ../index.html',pg.get_attribute('a.back','href')=='../index.html')
    check('theme set',pg.evaluate('document.documentElement.getAttribute("data-theme")') in ('dark','light'))
    check('buttons >=36px',all(pg.evaluate('(s)=>{const r=document.querySelector(s).getBoundingClientRect();return r.height>=36&&r.width>=36}',s) for s in ['#btnBack','#btnPlay','#btnStep','#btnReset']))
    check('simplifications note',pg.locator('text=Simplifications').count()>=1)
    init_state=pg.inner_html('#state');init_say=pg.inner_text('#say')
    check('initial idx -1',pg.evaluate('SIM.idx')==-1)
    asked,right=answer_all(pg);n=pg.evaluate('SIM.steps.length')
    check('reached end (%d steps)'%n,pg.evaluate('SIM.idx')==n-1)
    check('3-5 predictions (%d)'%asked,3<=asked<=5)
    check('score chip %d/%d'%(right,asked),pg.inner_text('#score')=='Score %d/%d'%(right,asked) and 0<right<asked)
    check('summary has score',('Prediction score: %d / %d'%(right,asked)) in pg.inner_text('#summary'))
    check('every step has say',all(pg.evaluate('SIM.steps.every(s=>s.say&&s.say.length>10)') for _ in [0]))
    for w,h in [(390,844),(1366,900)]:
        pg.set_viewport_size({'width':w,'height':h});pg.wait_for_timeout(100)
        check('no h-overflow at %d (%d)'%(w,overflow(pg)),overflow(pg)<=0)
    pg.keyboard.press('ArrowLeft');check('Left = back',pg.evaluate('SIM.idx')==n-2)
    pg.keyboard.press('ArrowRight');check('Right = step',pg.evaluate('SIM.idx')==n-1)
    pg.keyboard.press('r')
    check('Reset idx',pg.evaluate('SIM.idx')==-1);check('Reset state restored',pg.inner_html('#state')==init_state);check('Reset say restored',pg.inner_text('#say')==init_say);check('Reset score',pg.inner_text('#score')=='Score 0/0')
    pg.uncheck('#predict');pg.keyboard.press('ArrowRight');check('predict off: no quiz',pg.locator('#quiz:not([hidden])').count()==0 and pg.evaluate('SIM.idx')==0)
    pg.keyboard.press('r');pg.check('#predict')
    for _ in range(6):
        if pg.locator('#quiz:not([hidden])').count():break
        pg.keyboard.press('ArrowRight')
    check('predict on: quiz pauses before the step',pg.locator('#quiz:not([hidden])').count()==1 and not pg.evaluate('SIM.steps[SIM.idx+1].predict')==None)
    pg.keyboard.press('r')
    pg.uncheck('#predict');pg.select_option('#speed','2');pg.keyboard.press(' ');pg.wait_for_timeout(1500)
    played=pg.evaluate('SIM.idx');pg.keyboard.press(' ');pg.wait_for_timeout(1000)
    check('Space plays then pauses (idx %d)'%played,played>=1 and pg.evaluate('SIM.idx')<=played+1)
    pg.keyboard.press('r');pg.check('#predict')
    sig0=pg.evaluate('SIM.steps.map(s=>s.say).join("|")')
    pg.select_option('select[data-n="0"][data-k="cpu"]','1');pg.select_option('#ncount','3')
    check('Try it changes outcome (scheduler)',pg.evaluate('SIM.steps.map(s=>s.say).join("|")')!=sig0 and pg.evaluate('SIM.idx')==-1)
    pg.uncheck('#predict')
    n=pg.evaluate('SIM.steps.length')
    for _ in range(n):pg.keyboard.press('ArrowRight')
    check('Pending pod shows real event format',pg.evaluate('SIM.steps.some(s=>s.view.event&&/0\\/\\d nodes are available: .*(Insufficient|untolerated|didn)/.test(s.view.event))'))
    pg.keyboard.press('r');pg.check('#predict')
    check('no console/page errors %s'%errs[:2],not errs)
    check('no network requests',not reqs)
    b.close()
print('%d/%d passed'%(sum(res),len(res)))
sys.exit(0 if all(res) else 1)
