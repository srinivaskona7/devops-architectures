import sys,os,random,ipaddress;sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _common import *
SLUG='06-cidr-subnet-planner'
def fill(pg,sel,v):pg.evaluate('(a)=>{const e=document.querySelector(a[0]);e.value=a[1];e.dispatchEvent(new Event("input"))}',[sel,v])
def extra(c,res):
    pg=c.pg;random.seed(20261101)
    cases=['0.0.0.0/0','255.255.255.255/32','10.0.0.0/31','10.0.0.1/31','192.168.1.77/32','128.0.0.0/1','255.255.255.254/31','10.0.0.0/8','172.16.5.9/12']
    for _ in range(40):
        p=random.randint(0,32);ip=random.getrandbits(32);cases.append('%s/%d'%(ipaddress.IPv4Address(ip),p))
    bad=0
    for cs in cases:
        n=ipaddress.ip_network(cs,strict=False);p=n.prefixlen
        r=pg.evaluate('(s)=>{const q=SIM.parseCIDR(s);const c=SIM.calc(q.ip,q.p);return {net:SIM.ipStr(c.net),mask:SIM.ipStr(c.mask),bc:SIM.ipStr(c.bc),first:SIM.ipStr(c.first),last:SIM.ipStr(c.last),total:c.total,usable:c.usable}}',cs)
        if p==32:uf=ul=n.network_address;us=1
        elif p==31:uf,ul=n[0],n[-1];us=2
        else:uf,ul=n[1],n[-2];us=n.num_addresses-2
        exp=dict(net=str(n.network_address),mask=str(n.netmask),bc=str(n.broadcast_address),first=str(uf),last=str(ul),total=n.num_addresses,usable=us)
        if r!=exp:bad+=1;print('MISMATCH',cs,r,exp)
    check('%d CIDRs match ipaddress (incl /0 /31 /32)'%len(cases),bad==0,res)
    # UI shows calculation
    fill(pg,'#cidr','10.0.0.0/26');t=pg.inner_text('#calc')
    check('UI /26 shows 62 usable and 10.0.0.63','62' in t and '10.0.0.63' in t,res)
    fill(pg,'#cidr','999.1.1.1/8');check('invalid input shows error',pg.inner_text('#cerr')!='',res)
    fill(pg,'#cidr','10.0.0.0/33');check('/33 rejected',pg.inner_text('#cerr')!='',res)
    # split compare
    fill(pg,'#cidr','10.0.0.0/22');fill(pg,'#splitp','26')
    sp=pg.evaluate('SIM.split(SIM.calc(SIM.parseCIDR("10.0.0.0/22").ip,22),26).list.map(x=>SIM.ipStr(x.net)+"/"+x.p)')
    exp=[str(s) for s in ipaddress.ip_network('10.0.0.0/22').subnets(new_prefix=26)]
    check('split /22->/26 equals ipaddress (%d)'%len(exp),sp==exp,res)
    sp=pg.evaluate('SIM.split(SIM.calc(SIM.parseCIDR("0.0.0.0/0").ip,0),8).list.map(x=>SIM.ipStr(x.net)+"/"+x.p)')
    check('split /0->/8 equals ipaddress',sp==[str(s) for s in ipaddress.ip_network('0.0.0.0/0').subnets(new_prefix=8)],res)
    # overlap random compare
    bad=0
    for _ in range(60):
        a=ipaddress.ip_network('%s/%d'%(ipaddress.IPv4Address(random.getrandbits(32)),random.randint(0,32)),strict=False)
        b=ipaddress.ip_network('%s/%d'%(ipaddress.IPv4Address(random.getrandbits(32)),random.randint(0,32)),strict=False) if random.random()<.5 else random.choice(list(a.subnets(new_prefix=min(32,a.prefixlen+random.randint(0,3)))))
        r=pg.evaluate('(a)=>{const x=SIM.parseCIDR(a[0]),y=SIM.parseCIDR(a[1]);return SIM.overlap(SIM.calc(x.ip,x.p),SIM.calc(y.ip,y.p))}',[str(a),str(b)])
        if r!=a.overlaps(b):bad+=1;print('OV MISMATCH',a,b,r)
    check('60 overlap checks match ipaddress',bad==0,res)
    for i,v in enumerate(['10.0.0.0/16','10.0.128.0/17','172.16.0.0/16','','','']):fill(pg,'#ovin label:nth-child(%d) input'%(i+1),v)
    check('overlap UI flags 10.0.0.0/16 vs /17',pg.evaluate('SIM.overlapPairs')==1 and 'inside' in pg.inner_text('#ovres'),res)
    for i,v in enumerate(['10.0.0.0/16','10.1.0.0/16','172.16.0.0/16','192.168.0.0/24','10.2.0.0/16','10.3.0.0/16']):fill(pg,'#ovin label:nth-child(%d) input'%(i+1),v)
    check('overlap UI: 6 CIDRs, none overlap',pg.evaluate('SIM.overlapPairs')==0 and 'No overlaps' in pg.inner_text('#ovres'),res)
    # AWS
    pg.check('#aws');fill(pg,'#cidr','10.0.0.0/24');t=pg.inner_text('#awsout')
    check('AWS /24: 251 usable, reserved .0 .1 .2 .3 .255','251' in t and all(x in t for x in ['10.0.0.0','10.0.0.1','10.0.0.2','10.0.0.3','10.0.0.255']),res)
    check('AWS /24 within range','within the documented' in t and 'check the current AWS docs' in t,res)
    fill(pg,'#cidr','10.0.0.0/29');check('AWS /29 flagged outside range','outside the documented' in pg.inner_text('#awsout'),res)
    fill(pg,'#cidr','10.0.0.0/15');check('AWS /15 flagged outside range','outside the documented' in pg.inner_text('#awsout'),res)
    fill(pg,'#cidr','10.0.0.0/28');t=pg.inner_text('#awsout');check('AWS /28 in range, 11 usable','within the documented' in t and '11' in t,res)
    pg.uncheck('#aws')
res=[]
standard(SLUG,res,extra)
# worked example hits /26 question text
c=Ctx(SLUG);pg=c.pg
qs=pg.evaluate('SIM.steps.filter(s=>s.predict).map(s=>s.predict.q)')
check('worked example has /26 usable-hosts question and 3+ predictions',any('/26' in q for q in qs) and len(qs)>=3,res)
pg.uncheck('#predictToggle')
for _ in range(7):pg.click('#btnStep')
check('example final step enables AWS mode',pg.is_checked('#aws'),res)
check('cidr: no errors',not c.errs,res);c.close()
p=sum(1 for _,o in res if o);print('RESULT %d/%d passed'%(p,len(res)));sys.exit(0 if p==len(res) else 1)
