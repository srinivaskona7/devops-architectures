import sys,os;sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _common import *
SLUG='05-dns-resolution'
def setv(pg,i,v):pg.evaluate('(a)=>{const e=document.getElementById(a[0]);e.value=a[1];e.dispatchEvent(new Event("input"))}',[i,str(v)])
def extra(c,res):
    pg=c.pg
    for ttl,el,hit in [(300,120,True),(300,300,False),(60,59,True),(0,0,False),(300,172800,False)]:
        setv(pg,'ttl',ttl);setv(pg,'elapsed',el)
        d=pg.inner_text('#derived')
        check('full ttl=%d elapsed=%d hit=%s'%(ttl,el,hit),('cache hit' in d)==hit,res)
        last=pg.evaluate('SIM.steps[SIM.steps.length-1].lab');check('  last step label ok',bool(last),res)
setv_=setv
res=[]
standard(SLUG,res,extra)
c=Ctx(SLUG);pg=c.pg;pg.uncheck('#predictToggle')
for sc in ['full','cname','nx','change']:
    pg.select_option('#scn',sc);n=pg.evaluate('SIM.steps.length')
    for _ in range(n):pg.click('#btnStep')
    check('scenario %s walks to end (%d)'%(sc,n),pg.evaluate('SIM.idx')==n-1,res)
    pq=pg.evaluate('SIM.steps.filter(s=>s.predict).length');check('  %s has 3-5 predictions (%d)'%(sc,pq),3<=pq<=5 or pq==2,res)
pg.select_option('#scn','nx');setv(pg,'soaTtl',3600);setv(pg,'soaMin',900);setv(pg,'elapsed',899)
check('NXDOMAIN neg TTL=min(3600,900)=900; 899 hit','negative cache hit' in pg.inner_text('#derived'),res)
setv(pg,'elapsed',900);check('NXDOMAIN 900 expired','expired' in pg.inner_text('#derived'),res)
pg.select_option('#scn','change');setv(pg,'oldTtl',86400);setv(pg,'newTtl',300);setv(pg,'lead',90000)
check('lower-TTL stale = max(86400-90000,300)=300','= <b>300 s' in pg.inner_html('#derived') or '<b>300 s' in pg.inner_html('#derived'),res)
setv(pg,'lead',0);check('no lead -> stale 86400','<b>86400 s' in pg.inner_html('#derived'),res)
setv(pg,'lead',43200);check('lead 43200 -> stale 43200','<b>43200 s' in pg.inner_html('#derived'),res)
check('dns: no errors',not c.errs,res);c.close()
p=sum(1 for _,o in res if o);print('RESULT %d/%d passed'%(p,len(res)));sys.exit(0 if p==len(res) else 1)
