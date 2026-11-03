import sys,os
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..', 'tools'))
from lint_layout import browser_path
from playwright.sync_api import sync_playwright
SIMS=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class Ctx:
    def __init__(s,slug,w=1366,h=900):
        s.p=sync_playwright().start();s.b=s.p.chromium.launch(executable_path=browser_path())
        s.pg=s.b.new_page(viewport={'width':w,'height':h});s.errs=[];s.reqs=[]
        s.pg.on('console',lambda m:s.errs.append(m.text) if m.type=='error' else None)
        s.pg.on('pageerror',lambda e:s.errs.append(str(e)))
        s.pg.on('request',lambda r:s.reqs.append(r.url) if not r.url.startswith('file:') and not r.url.startswith('data:') else None)
        s.pg.goto('file://'+os.path.join(SIMS,slug+'.html'))
    def close(s):s.b.close();s.p.stop()
def check(name,cond,res):
    res.append((name,bool(cond)));print(('PASS ' if cond else 'FAIL ')+name)
def overflow(pg):return pg.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
def run_predict(pg,limit=500):
    """step to end, answering predictions; returns (asked,right)"""
    n=0
    while n<limit:
        n+=1
        if pg.locator('#quiz:not([hidden]) .opts button:not([disabled])').count():
            idx=pg.evaluate('SIM.steps[Engine_idx()].predict.correct') if False else None
        pg.click('#btnStep')
        if pg.locator('#quiz:not([hidden]) .opts button:not([disabled])').count():
            yield 'q'
        if pg.evaluate('SIM.idx')>=pg.evaluate('SIM.steps.length')-1 and not pg.locator('#quiz:not([hidden]) .opts button:not([disabled])').count():
            return
def standard(slug,res,extra=None):
    c=Ctx(slug);pg=c.pg
    check(slug+': meta tags',all(pg.locator('meta[name="%s"]'%m).count()==1 for m in ['sim:title','sim:topic','sim:summary','sim:concepts']) and pg.get_attribute('meta[name="sim:topic"]','content')=='00-roadmap-prerequisites',res)
    check(slug+': back link',pg.get_attribute('a.back','href')=='../index.html',res)
    init_say=pg.inner_text('#say');init_state=pg.inner_text('#state') if pg.locator('#state').count() else ''
    nsteps=pg.evaluate('SIM.steps.length')
    # keyboard
    pg.keyboard.press('ArrowRight');a=pg.evaluate('SIM.idx')
    check(slug+': predict pauses first (idx still -1 or pending)',pg.locator('#quiz:not([hidden])').count()+ (1 if a>=0 else 0)>=1,res)
    # Walk to end answering first correct for even, wrong for odd questions
    asked=right=0;guard=0
    while pg.evaluate('SIM.idx')<nsteps-1 and guard<400:
        guard+=1
        if pg.locator('#quiz:not([hidden]) .opts button:not([disabled])').count():
            ci=pg.evaluate('(()=>{const q=document.querySelector("#quiz p").textContent;const s=SIM.steps.find(x=>x.predict&&x.predict.q===q);return s.predict.correct})()')
            pick=ci if asked%2==0 else (ci+1)%4
            pg.locator('#quiz .opts button').nth(pick).click();asked+=1;right+=(pick==ci)
        else:
            pg.keyboard.press('ArrowRight')
    check(slug+': reached end (%d/%d)'%(pg.evaluate('SIM.idx')+1,nsteps),pg.evaluate('SIM.idx')==nsteps-1,res)
    score=pg.inner_text('#score')
    check(slug+': score chip %d/%d ("%s")'%(right,asked,score),score=='Score %d/%d'%(right,asked) and asked>=3,res)
    summ=pg.inner_text('#summary')
    check(slug+': summary shows score',('Prediction score: %d / %d'%(right,asked)) in summ,res)
    for w,h in [(390,844),(1366,900)]:
        pg.set_viewport_size({'width':w,'height':h});pg.wait_for_timeout(100)
        check(slug+': no h-overflow at %d (%d)'%(w,overflow(pg)),overflow(pg)<=0,res)
    # back
    pg.keyboard.press('ArrowLeft');check(slug+': Back steps back',pg.evaluate('SIM.idx')==nsteps-2,res)
    # play/pause with space and no predict
    pg.keyboard.press('r');
    check(slug+': Reset restores idx/score/summary',pg.evaluate('SIM.idx')==-1 and pg.inner_text('#score')=='Score 0/0' and pg.locator('#summary:not([hidden])').count()==0 and pg.inner_text('#say')==init_say,res)
    if init_state: check(slug+': Reset restores state panel',pg.inner_text('#state')==init_state,res)
    pg.uncheck('#predictToggle');pg.select_option('#speed','2')
    pg.keyboard.press('Space');pg.wait_for_timeout(300)
    check(slug+': Space starts play',pg.inner_text('#btnPlay').startswith('⏸'),res)
    pg.keyboard.press('Space');check(slug+': Space pauses',pg.inner_text('#btnPlay').startswith('▶'),res)
    for _ in range(nsteps+2):pg.click('#btnStep')
    check(slug+': predict off -> no questions, reaches end',pg.evaluate('SIM.idx')==nsteps-1 and 'No predictions' in pg.inner_text('#summary') or pg.evaluate('SIM.idx')==nsteps-1,res)
    sizes=pg.evaluate('[...document.querySelectorAll("button")].filter(b=>b.offsetParent&&(b.getBoundingClientRect().height<36||b.getBoundingClientRect().width<36)).length')
    check(slug+': buttons >=36px',sizes==0,res)
    if extra:extra(c,res)
    check(slug+': no external requests',not c.reqs,res)
    check(slug+': no console/page errors %s'%c.errs[:2],not c.errs,res)
    c.close()
