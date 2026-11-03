import sys,os;sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _dop_common import *
SLUG='07-aws-iam-evaluation'
res=[]
EXP={'scp':('DENY (implicit)','Service control policy (SCP)'),'boundary':('DENY (implicit)','Permissions boundary'),'cross':('DENY (implicit)','Resource-based policy'),
 'deny':('DENY (explicit)','Explicit Deny policy'),'direct':('ALLOW','Resource-based policy'),'cond':('DENY (implicit)','Identity-based policy')}
def setv(pg,i,v):pg.evaluate('([a,b])=>{const e=document.getElementById(a);e.value=b;e.dispatchEvent(new Event("input"))}',[i,v])
def outcome(pg):
    pg.click('#btnReset');pg.uncheck('#predictToggle')
    for _ in range(20):pg.click('#btnStep')
    pg.check('#predictToggle');return pg.evaluate('[SIM.result.decision,SIM.result.layer,SIM.idx==SIM.steps.length-1]')
def extra(c,res):
    pg=c.pg
    for sid,(dec,layer) in EXP.items():
        pg.select_option('#scn',sid);d,l,fin=outcome(pg)
        lname=pg.evaluate('LN["%s"]'%l)
        check('scenario %s -> %s at %s'%(sid,dec,layer),d==dec and lname==layer and fin,res)
    # fixes: cross with resource policy -> allow
    pg.select_option('#scn','cross');pg.check('#en-resource');d,l,_=outcome(pg);check('cross + resource allow => ALLOW',d=='ALLOW',res)
    pg.select_option('#scn','cond');setv(pg,'ip','10.1.1.1');d,l,_=outcome(pg);check('condition IP fixed => ALLOW',d=='ALLOW',res)
    setv(pg,'tags','Team=other');d,l,_=outcome(pg);check('tag mismatch => implicit deny at identity',d=='DENY (implicit)' and l=='identity',res)
    pg.select_option('#scn','scp');pg.uncheck('#en-scp');d,l,_=outcome(pg);check('SCP removed => ALLOW',d=='ALLOW',res)
    pg.check('#en-boundary');setv(pg,'action','iam:CreateUser');d,l,_=outcome(pg);check('boundary then blocks other action',d=='DENY (implicit)' and l=='identity',res)
    # session policy limits role
    pg.select_option('#scn','scp');pg.uncheck('#en-scp');setv(pg,'ptype','role');pg.check('#en-session');d,l,_=outcome(pg)
    check('session policy blocks role (implicit at session)',d=='DENY (implicit)' and l=='session',res)
    pg.uncheck('#en-session');d,l,_=outcome(pg);check('role without session policy => ALLOW',d=='ALLOW',res)
    # resource policy naming role ARN is limited by boundary (documented); naming session ARN is direct
    pg.select_option('#scn','direct');setv(pg,'ptype','role');
    pg.fill('#tx-resource','{"Statement":[{"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::111111111111:role/Deployer"},"Action":"s3:GetObject","Resource":"*"}]}');pg.dispatch_event('#tx-resource','input')
    d,l,_=outcome(pg);check('role-ARN resource grant limited by boundary => DENY at identity/boundary',d=='DENY (implicit)',res)
    pg.fill('#tx-resource','{"Statement":[{"Effect":"Allow","Principal":{"AWS":"arn:aws:sts::111111111111:assumed-role/Deployer/ci-session"},"Action":"s3:GetObject","Resource":"*"}]}');pg.dispatch_event('#tx-resource','input')
    d,l,_=outcome(pg);check('session-ARN resource grant not limited => ALLOW',d=='ALLOW',res)
    # invalid JSON handled
    pg.fill('#tx-identity','{bad');pg.dispatch_event('#tx-identity','input');check('invalid JSON warns, no crash',pg.inner_text('#wn-identity').startswith('Invalid JSON'),res)
standard(SLUG,'10-aws',res,extra)
finish(res)
