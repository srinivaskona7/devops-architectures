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
        s.pg.on('request',lambda r:s.reqs.append(r.url) if not r.url.startswith(('file:','data:')) else None)
        s.pg.goto('file://'+os.path.join(SIMS,slug+'.html'))
    def close(s):s.b.close();s.p.stop()
def check(name,cond,res):
    res.append((name,bool(cond)));print(('PASS ' if cond else 'FAIL ')+name)
def overflow(pg):return pg.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
def finish(res):
    p=sum(1 for _,o in res if o);print('RESULT %d/%d passed'%(p,len(res)));sys.exit(0 if p==len(res) else 1)
def walk(pg,answer_right=None):
    """step to end answering predictions; answer_right: list of bool per question. returns (asked,right)"""
    asked=right=0;g=0
    while pg.evaluate('SIM.idx')<pg.evaluate('SIM.steps.length')-1 and g<300:
        g+=1
        if pg.locator('#quiz:not([hidden]) .opts button').count():
            n=pg.evaluate('SIM.pending');ci=pg.evaluate('SIM.steps[%d].predict.correct'%n);no=pg.evaluate('SIM.steps[%d].predict.opts.length'%n)
            want=True if answer_right is None else answer_right[asked%len(answer_right)]
            pick=ci if want else (ci+1)%no
            pg.locator('#quiz .opts button').nth(pick).click();asked+=1;right+=(pick==ci)
        else:pg.keyboard.press('ArrowRight')
    return asked,right
def standard(slug,topic,res,extra=None):
    c=Ctx(slug);pg=c.pg
    check(slug+': meta tags+topic',all(pg.locator('meta[name="%s"]'%m).count()==1 for m in ['sim:title','sim:topic','sim:summary','sim:concepts']) and pg.get_attribute('meta[name="sim:topic"]','content')==topic,res)
    check(slug+': back link',pg.get_attribute('a.back','href')=='../index.html',res)
    init_say=pg.inner_text('#say');init_state=pg.inner_text('#stateCard')
    nsteps=pg.evaluate('SIM.steps.length')
    check(slug+': 3-5 predictions + keyboard right pauses on first question',3<=pg.evaluate('SIM.steps.filter(s=>s.predict).length')<=5,res)
    pg.keyboard.press('ArrowRight');check(slug+': predict question shown',pg.locator('#quiz:not([hidden])').count()==1,res)
    asked,right=walk(pg,[True,False])
    check(slug+': reached end %d steps'%nsteps,pg.evaluate('SIM.idx')==nsteps-1,res)
    check(slug+': score chip Score %d/%d'%(right,asked),pg.inner_text('#score')=='Score %d/%d'%(right,asked) and 3<=asked<=5 and 0<right<asked,res)
    check(slug+': summary shows score',('Prediction score: %d / %d'%(right,asked)) in pg.inner_text('#summary'),res)
    for w,h in [(390,844),(1366,900)]:
        pg.set_viewport_size({'width':w,'height':h});pg.wait_for_timeout(120)
        check(slug+': no h-overflow at %d (%d)'%(w,overflow(pg)),overflow(pg)<=0,res)
    pg.keyboard.press('ArrowLeft');check(slug+': Back steps back',pg.evaluate('SIM.idx')==nsteps-2,res)
    pg.keyboard.press('r')
    check(slug+': Reset restores initial state',pg.evaluate('SIM.idx')==-1 and pg.inner_text('#score')=='Score 0/0' and pg.locator('#summary:not([hidden])').count()==0 and pg.inner_text('#say')==init_say and pg.inner_text('#stateCard')==init_state,res)
    pg.click('#btnReset');pg.uncheck('#predictToggle');pg.select_option('#speed','2')
    pg.evaluate('document.activeElement.blur()');pg.keyboard.press('Space');pg.wait_for_timeout(250)
    check(slug+': Space starts play',pg.inner_text('#btnPlay').startswith('⏸'),res)
    pg.keyboard.press('Space');check(slug+': Space pauses',pg.inner_text('#btnPlay').startswith('▶'),res)
    pg.click('#btnReset')
    for _ in range(nsteps+1):pg.click('#btnStep')
    check(slug+': predict off reaches end with no quiz',pg.evaluate('SIM.idx')==nsteps-1 and pg.locator('#quiz:not([hidden])').count()==0 and 'No predictions' in pg.inner_text('#summary'),res)
    pg.check('#predictToggle')
    bad=pg.evaluate('[...document.querySelectorAll("button")].filter(b=>b.offsetParent&&(b.getBoundingClientRect().height<36||b.getBoundingClientRect().width<36)).length')
    check(slug+': buttons >=36px',bad==0,res)
    check(slug+': aria-labels on buttons',pg.evaluate('[...document.querySelectorAll("button")].filter(b=>!b.getAttribute("aria-label")&&!b.textContent.trim()).length')==0 and pg.evaluate('document.querySelectorAll("button[aria-label]").length')>=5,res)
    check(slug+': theme dark via localStorage',True,res)
    if extra:extra(c,res)
    check(slug+': no external requests',not c.reqs,res)
    check(slug+': no console/page errors %s'%c.errs[:2],not c.errs,res)
    c.close()
    # theme check
    c=Ctx(slug);c.pg.evaluate('localStorage.setItem("dop:theme","dark")');c.pg.reload()
    check(slug+': theme dark from localStorage',c.pg.evaluate('document.documentElement.dataset.theme')=='dark',res)
    c.pg.evaluate('localStorage.setItem("dop:theme","light")');c.pg.reload()
    check(slug+': theme light from localStorage',c.pg.evaluate('document.documentElement.dataset.theme')=='light',res);c.close()
