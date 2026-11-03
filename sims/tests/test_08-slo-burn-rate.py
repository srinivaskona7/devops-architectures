import sys,os;sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _dop_common import *
from fractions import Fraction as F
SLUG='08-slo-burn-rate'
res=[]
def setv(pg,i,v):pg.evaluate('([a,b])=>{const e=document.getElementById(a);e.value=b;e.dispatchEvent(new Event("input"));e.dispatchEvent(new Event("change"))}',[i,str(v)])
RULES=[(14.4,12,1),(6,72,6),(3,288,24),(1,864,72)]
def py_fire(e,slo):
    frac=(100-F(slo))/100;frac=float(frac);out=[]
    for burn,lt,st in RULES:
        first=-1
        for t in range(lt-1,len(e)):
            bl=sum(e[t+1-lt:t+1])/lt/frac;bs=sum(e[t+1-st:t+1])/st/frac
            if bl>burn+1e-9 and bs>burn+1e-9:first=t;break
        out.append(first)
    return out
def py_series(base,spikes):
    e=[base/100]*1440
    for s_h,dur,rate in spikes:
        s=round(s_h*60/5)
        for i in range(s,min(1440,s+max(1,round(dur/5)))):e[i]=rate/100
    return e
def run_end(pg):
    pg.click('#btnReset');pg.uncheck('#predictToggle')
    for _ in range(30):pg.click('#btnStep')
    pg.check('#predictToggle')
def extra(c,res):
    pg=c.pg
    # downtime figures
    for s in ['99','99.5','99.9','99.95','99.99','99.999']:
        setv(pg,'slo',s);exp=F(43200)*(100-F(s))/100
        got=pg.evaluate('M.B.minutes');txt=pg.inner_text('#budgetMath')
        check('SLO %s downtime %s min (py %s)'%(s,got,float(exp)),abs(got-float(exp))<1e-9,res)
    setv(pg,'slo','99.9');check('99.9 shows 43.2 min text','43.2 min' in pg.inner_text('#budgetMath'),res)
    # rule budget % and thresholds
    pcts=pg.evaluate('RULES.map(r=>r.pct)');exp=[b*lh/720*100 for (b,lt,st),lh in zip(RULES,[1,6,24,72])]
    check('budget consumed 2/5/10/10 %% %s'%pcts,all(abs(a-b)<1e-9 for a,b in zip(pcts,exp)) and [round(x,6) for x in exp]==[2,5,10,10],res)
    check('burn thresholds 14.4/6/3/1',pg.evaluate('RULES.map(r=>r.burn)')==[14.4,6,3,1],res)
    for s in ['99','99.9','99.99']:
        setv(pg,'slo',s);thr=pg.evaluate('RULES.map(r=>r.burn*M.B.frac)');frac=float((100-F(s))/100)
        check('threshold error rate for %s'%s,all(abs(a-b*frac)<1e-12 for a,b in zip(thr,[14.4,6,3,1])),res)
    # composition
    setv(pg,'chain','99.95, 99.9, 99.99');setv(pg,'repA','99');setv(pg,'repN','2')
    ser=0.9995*0.999*0.9999;par=1-(1-0.99)**2
    got=pg.evaluate('[M.serialA,M.parA,M.combA]')
    check('serial %.8f parallel %.8f combined'%(ser,par),abs(got[0]-ser)<1e-12 and abs(got[1]-par)<1e-12 and abs(got[2]-ser*par)<1e-12,res)
    # presets vs python
    cases=[('fast',[(80,60,2)],'99.9'),('slow',[(80,1440,0.4)],'99.9'),('blip',[(80,5,5)],'99.9'),('mid',[(80,360,0.8)],'99.9'),('none',[],'99.9'),('fast',[(80,60,2)],'99'),('fast',[(80,60,2)],'99.99')]
    for p,sp,slo in cases:
        setv(pg,'slo',slo);pg.select_option('#preset',p);e=py_series(0.01,sp)
        exp=py_fire(e,slo);got=pg.evaluate('RULES.map(r=>M.first[r.id])')
        check('preset %s @%s fires %s'%(p,slo,got),got==exp,res)
    setv(pg,'slo','99.9');pg.select_option('#preset','blip');run_end(pg)
    check('blip: no alert fires, summary says none','none' in pg.inner_text('#summary'),res)
    pg.select_option('#preset','fast');run_end(pg)
    check('fast burn: 14.4x fires',pg.evaluate('M.first.r1')>=0 and 'FIRING' not in 'x',res)
    # consumed budget arithmetic: 2% for 60min at 99.9 => 12 ticks*0.02*5=1.2 + base
    e=py_series(0.01,[(80,60,2)]);cons=sum(e)*5/(43200*0.001)
    check('budget consumed %.4f%% matches'%(cons*100),abs(pg.evaluate('M.consumedAll')-cons)<1e-9,res)
    # painting with pointer
    pg.click('#spClear');box=pg.locator('#cv').bounding_box()
    pg.mouse.move(box['x']+300,box['y']+60);pg.mouse.down();pg.mouse.move(box['x']+340,box['y']+60,steps=5);pg.mouse.up()
    check('pointer paint changes series',pg.evaluate('paint.filter(v=>v!==null).length')>5,res)
    pg.select_option('#mode','erase');pg.mouse.move(box['x']+300,box['y']+60);pg.mouse.down();pg.mouse.move(box['x']+345,box['y']+60,steps=5);pg.mouse.up()
    check('erase clears painting',pg.evaluate('paint.filter(v=>v!==null).length')==0,res)
    # exhaust: 100% errors 1 day at 99.9 -> consumed >100%
    pg.select_option('#mode','paint');setv(pg,'spRate',100);setv(pg,'spDur',720);pg.click('#spApply')
    check('exhaustion flagged',pg.evaluate('M.consumedAll')>1 and 'exhausted' in pg.evaluate('SIM.steps[SIM.steps.length-1].say'),res)
    # mobile layout with chart
    pg.set_viewport_size({'width':390,'height':844});pg.wait_for_timeout(150)
    check('mobile no overflow after painting (%d)'%overflow(pg),overflow(pg)<=0,res)
    check('promql plain text present','sum(rate(' in pg.inner_text('#promql') and '14.4 * 0.001' in pg.inner_text('#promql'),res)
standard(SLUG,'07-monitoring-alerting',res,extra)
finish(res)
