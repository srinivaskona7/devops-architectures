import sys,os
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..', 'tools'))
from lint_layout import browser_path
from playwright.sync_api import sync_playwright
SLUG='09-raft-etcd'
FILE=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),SLUG+'.html')
res=[]
def check(n,c):
    res.append(bool(c));print(('PASS ' if c else 'FAIL ')+n)
def overflow(pg):return pg.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
def until(pg,expr,n=8):
    for _ in range(n):
        if pg.evaluate(expr):return True
        pg.click('#bAdv')
    return pg.evaluate(expr)
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
    check('buttons >=36px',pg.evaluate('[...document.querySelectorAll("button")].every(b=>{const r=b.getBoundingClientRect();return r.height>=36&&r.width>=36})'))
    check('simplifications note names compaction, membership, pre-vote',all(w in pg.inner_text('.simp') for w in ['log compaction','membership change','pre-vote']))
    check('quorum arithmetic: 3->2/1, 4->3/1, 5->3/2',pg.evaluate('[3,4,5].map(n=>quorum(n)+"/"+(n-quorum(n))).join()')=='2/1,3/1,3/2')
    init_state=pg.inner_html('#state');init_say=pg.inner_text('#say')
    for n in (3,5):
        pg.select_option('#ncount',str(n));pg.wait_for_timeout(50)
        check('N=%d initial idx -1'%n,pg.evaluate('SIM.idx')==-1)
        a,r=answer_all(pg);L=pg.evaluate('SIM.steps.length')
        check('N=%d reached end (%d steps)'%(n,L),pg.evaluate('SIM.idx')==L-1)
        check('N=%d 3-5 predictions (%d)'%(n,a),3<=a<=5)
        check('N=%d score chip %d/%d'%(n,r,a),pg.inner_text('#score')=='Score %d/%d'%(r,a) and 0<r<a)
        check('N=%d summary has score'%n,('Prediction score: %d / %d'%(r,a)) in pg.inner_text('#summary'))
        check('N=%d every step has explanation'%n,pg.evaluate('SIM.steps.every(s=>s.say&&s.say.length>10)'))
        check('N=%d scripted story: partition minority cannot commit, vote denied, stale leader steps down, overwrite'%n,pg.evaluate('(()=>{const t=SIM.steps.map(s=>s.say+" "+s.view.ev.map(e=>e.msg).join(" ")).join(" ");return /less up to date/.test(t)&&/steps down/.test(t)&&/deletes them/.test(t)&&/stays uncommitted/.test(t)})()'))
        check('N=%d no safety violations in any step'%n,pg.evaluate('SIM.steps.every(s=>check(s.view.C).length===0)'))
        for w,h in [(390,844),(1366,900)]:
            pg.set_viewport_size({'width':w,'height':h});pg.wait_for_timeout(100)
            check('N=%d no h-overflow at %d (%d)'%(n,w,overflow(pg)),overflow(pg)<=0)
        pg.keyboard.press('ArrowLeft');check('N=%d Left = back'%n,pg.evaluate('SIM.idx')==L-2)
        pg.keyboard.press('ArrowRight');check('N=%d Right = step'%n,pg.evaluate('SIM.idx')==L-1)
        pg.keyboard.press('r')
        check('N=%d Reset idx/score/say'%n,pg.evaluate('SIM.idx')==-1 and pg.inner_text('#score')=='Score 0/0' and pg.locator('#summary:not([hidden])').count()==0)
    pg.select_option('#ncount','3');pg.keyboard.press('r')
    check('Reset state restored (N=3)',pg.inner_html('#state')==init_state and pg.inner_text('#say')==init_say)
    # reproducibility
    s1=pg.evaluate('SIM.steps.map(s=>s.say).join("|")');pg.keyboard.press('r');s2=pg.evaluate('SIM.steps.map(s=>s.say).join("|")')
    check('seeded run reproducible',s1==s2)
    pg.fill('#seed','11');pg.dispatch_event('#seed','change')
    check('different seed gives a different run',pg.evaluate('SIM.steps.map(s=>s.say).join("|")')!=s1)
    pg.fill('#seed','7');pg.dispatch_event('#seed','change')
    # keyboard play
    pg.uncheck('#predict');pg.select_option('#speed','2');pg.keyboard.press(' ');pg.wait_for_timeout(1800)
    played=pg.evaluate('SIM.idx');pg.keyboard.press(' ');pg.wait_for_timeout(800)
    check('Space plays then pauses (idx %d)'%played,played>=1 and pg.evaluate('SIM.idx')<=played+1)
    pg.keyboard.press('r');pg.check('#predict')
    # Try it
    pg.select_option('#ncount','3')
    until(pg,'leaderOf(cur())>=0')
    check('Try it: run to next event elects a leader',pg.evaluate('leaderOf(cur())')>=0)
    ld=pg.evaluate('leaderOf(cur())')
    pg.fill('#wcmd','z=9');pg.click('#bWrite');until(pg,'Object.values(cur().ledger).some(e=>e.cmd==="z=9")')
    check('Try it: write replicated and committed',pg.evaluate('(()=>{const c=cur();return Object.values(c.ledger).some(e=>e.cmd==="z=9")})()'))
    pg.select_option('#tnode',str(ld));pg.click('#bKill')
    check('Try it: kill leader marks node down',pg.evaluate('!cur().nodes[%d].alive'%ld) and 'DOWN' in pg.inner_text('#state'))
    until(pg,'leaderOf(cur())>=0&&leaderOf(cur())!=%d'%ld)
    nl=pg.evaluate('leaderOf(cur())')
    check('Try it: new leader elected among survivors',nl>=0 and nl!=ld)
    pg.select_option('#lA','0');pg.select_option('#lB','1');pg.click('#bCut')
    check('Try it: cut link shown',pg.evaluate('cur().cut.includes("0-1")') and 'Cut links' in pg.inner_text('#state'))
    pg.click('#bHealAll');check('Try it: heal all',pg.evaluate('cur().cut.length')==0)
    check('Safety line shows 0 violations',('0 violations' in pg.inner_text('#inv')))
    pg.keyboard.press('r')
    check('Reset after Try it restores initial',pg.inner_html('#state')==init_state and pg.evaluate('SIM.idx')==-1)
    # headless fuzz
    out=pg.evaluate('(()=>{const o=[];for(let s=1;s<=250;s++)o.push(fuzz(s));return o})()')
    bad=[x for x in out if x['viol']]
    check('fuzz: 250 randomized runs (3 and 5 nodes), 0 safety violations %s'%bad[:1],len(out)==250 and not bad)
    check('fuzz: at most one leader per term (tracked in every run)',all(not any('two leaders' in v for v in x['viol']) for x in out))
    check('fuzz: committed entries never lost (>=1000 commits seen, got %d)'%sum(x['committed'] for x in out),sum(x['committed'] for x in out)>=1000 and not bad)
    check('fuzz: after healing every run converges to one leader and identical logs',all(x['converged'] and x['leaders']==1 for x in out))
    check('fuzz: multiple terms exercised',sum(x['terms'] for x in out)>=500)
    check('fuzz deterministic',pg.evaluate('JSON.stringify(fuzz(5))===JSON.stringify(fuzz(5))'))
    check('no console/page errors %s'%errs[:2],not errs)
    check('no network requests',not reqs)
    b.close()
print('%d/%d passed'%(sum(res),len(res)))
sys.exit(0 if all(res) else 1)
