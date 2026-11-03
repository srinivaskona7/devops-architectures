import sys,os;sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _common import *
SLUG='04-tcp-tls-handshake'
def extra(c,res):
    pg=c.pg
    # TTFB arithmetic computed in code
    for mode,rtts in [('tls13',3),('tls12',4),('resume',3),('zero',2),('h3',2),('h3zero',1)]:
        for rtt,think in [(10,0),(80,20),(300,200)]:
            pg.select_option('#mode',mode);pg.fill('#rtt',str(rtt)) if False else pg.evaluate('(v)=>{const e=document.getElementById("rtt");e.value=v[0];e.dispatchEvent(new Event("input"));const t=document.getElementById("think");t.value=v[1];t.dispatchEvent(new Event("input"))}',[rtt,think])
            exp=rtts*rtt+think
            check('ttfb %s rtt=%d think=%d -> %d ms'%(mode,rtt,think,exp),('= %d ms'%exp) in pg.inner_text('#ttfb'),res)
    pg.select_option('#mode','tls13')
    check('TLS1.3 includes all named messages',all(k in ''.join(s['lab'] for s in pg.evaluate('SIM.build("tls13")')) for k in ['key_share','ServerHello','EncryptedExtensions','Certificate','CertificateVerify','Finished']),res)
    check('0-RTT replay note on page','replayed' in pg.inner_text('body') or 'replay' in pg.inner_text('body'),res)
res=[]
standard(SLUG,res,extra)
# every scenario walks to end w/o error
c=Ctx(SLUG);pg=c.pg;pg.uncheck('#predictToggle')
for m in ['tls13','tls12','resume','zero','h3','h3zero']:
    pg.select_option('#mode',m);n=pg.evaluate('SIM.steps.length')
    for _ in range(n):pg.click('#btnStep')
    check('scenario %s walks to end (%d steps)'%(m,n),pg.evaluate('SIM.idx')==n-1,res)
check('scenarios: no errors',not c.errs,res);c.close()
p=sum(1 for _,o in res if o);print('RESULT %d/%d passed'%(p,len(res)));sys.exit(0 if p==len(res) else 1)
