/* Flashcards with spaced repetition (Leitner boxes) and a mixed quiz, across every topic. Progress is stored in localStorage. */
(()=>{
const C=window.PQCore,D=window.__PQ||{},LS=window.localStorage;
const $=(s,r=document)=>r.querySelector(s),h=C.h;
document.documentElement.dataset.theme=LS.getItem('dop:theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
const tb=$('#theme');if(tb)tb.onclick=()=>{const t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;LS.setItem('dop:theme',t)};
const menu=$('.menu'),mb=$('.menu>button');if(mb)mb.onclick=e=>{e.stopPropagation();menu.classList.toggle('open')};
document.addEventListener('click',e=>{if(menu&&!menu.contains(e.target))menu.classList.remove('open')});
const INT=[0,1,3,7,16,35];               /* days until a card returns, by box */
const folders=Object.keys(D).sort();
folders.forEach(k=>D[k].sections.forEach(s=>s.c.forEach(c=>c.f=k)));
let plan=new Set();try{plan=new Set(JSON.parse(LS.getItem('dop:plan')||'[]'))}catch(e){}
const rf=$('#rf'),rp=$('#rp'),rn=$('#rn'),body=$('#rbody'),stats=$('#rstats');
rf.append(new Option('All topics','*'));folders.forEach(k=>rf.append(new Option(D[k].title,k)));
rp.disabled=!plan.size;
const concepts=()=>folders.filter(k=>rf.value==='*'||rf.value===k).flatMap(k=>D[k].sections.flatMap(s=>s.c)).filter(c=>!rp.checked||plan.has(c.f+'#'+c.id));
function cardsOf(cs){
  const out=[];
  cs.forEach(c=>{
    if(c.p&&c.p.length>=20)out.push({key:c.f+'#'+c.id+'#p',f:c.f,cid:c.id,ct:c.t,front:c.t,back:c.p,kind:'Explain in plain words'});
    (c.k||[]).forEach(([q,a],i)=>out.push({key:c.f+'#'+c.id+'#k'+i,f:c.f,cid:c.id,ct:c.t,front:q,back:a,kind:'Check yourself'}));
  });
  return out;
}
function paintStats(){
  const t=C.today(),s=C.srs(),L=cardsOf(concepts());let due=0,fresh=0,learned=0;
  L.forEach(c=>{const x=s[c.key];if(!x)fresh++;else{if(x.d<=t)due++;if(x.b>=3)learned++}});
  stats.replaceChildren(...[['Due today',due],['New',fresh],['Learned',learned],['Cards',L.length]].map(([a,b])=>{const e=h('span','chip');e.append(h('b',null,String(b)),document.createTextNode(' '+a));return e}));
}
let active=null;
document.addEventListener('keydown',e=>{
  if(!active||/INPUT|TEXTAREA|SELECT/.test((e.target||{}).tagName))return;
  if(e.key===' '||e.key==='Enter'){active.flip();e.preventDefault()}
  else if(active.flipped()&&'123'.includes(e.key)){active.grade(['again','good','easy']['123'.indexOf(e.key)])}
});
function startCards(){
  const t=C.today(),s=C.srs(),L=cardsOf(concepts()),N=+rn.value;
  const due=L.filter(c=>s[c.key]&&s[c.key].d<=t).sort((a,b)=>s[a.key].d-s[b.key].d);
  const fresh=C.shuffle(L.filter(c=>!s[c.key])).slice(0,N);
  const queue=due.concat(fresh);let reviewed=0;
  if(!queue.length){body.replaceChildren(h('p','muted','Nothing is due and there are no new cards for this selection. Come back tomorrow, or choose another topic.'));active=null;return}
  let cur=null,flipped=false;
  function next(){cur=queue.shift()||null;flipped=false;draw()}
  function grade(g){
    const st=C.srs(),old=st[cur.key]||{b:0},day=C.today();
    const b=g==='again'?0:Math.min(5,old.b+(g==='easy'?2:1));
    st[cur.key]={b,d:day+INT[b]};C.srsSave(st);reviewed++;
    if(g==='again')queue.splice(Math.min(3,queue.length),0,cur);
    paintStats();next();
  }
  function draw(){
    body.replaceChildren();
    if(!cur){
      const d=h('div','fc');d.append(h('h3',null,'Session complete'),h('p',null,reviewed+' reviews done. Cards you rated Good return tomorrow, then after 3, 7, 16 and 35 days.'));
      body.append(d);active=null;paintStats();return;
    }
    const c=h('div','fc');
    c.append(h('div','fck',cur.kind+' · '+cur.ct+' · '+(queue.length+1)+' left'));
    c.append(h('div','fcf',cur.front));
    if(flipped){
      c.append(h('div','fcb',cur.back));
      const a=h('a','fcl','Open this concept ↗');a.href=cur.f+'/index.html#'+cur.cid;c.append(a);
      const row=h('div','qrow');
      [['again','Again (1)'],['good','Good (2)'],['easy','Easy (3)']].forEach(([g,l])=>{const b=h('button','btn'+(g==='good'?' pri':''),l);b.type='button';b.dataset.g=g;b.onclick=()=>grade(g);row.append(b)});
      c.append(row);
    }else{
      const b=h('button','btn pri','Show answer (Space)');b.type='button';b.id='flip';b.onclick=()=>{flipped=true;draw()};c.append(b);
    }
    body.append(c);
  }
  active={flip:()=>{if(!flipped){flipped=true;draw()}},flipped:()=>flipped,grade};
  next();
}
function startQuiz(){
  active=null;
  const cs=concepts(),qs=C.build(cs,cs,10);
  if(qs.length<4){body.replaceChildren(h('p','muted','Not enough material in this selection for a quiz. Choose more topics.'));return}
  C.runQuiz(body,qs,{retry:startQuiz});
}
const tc=$('#tcards'),tq=$('#tquiz');
const tab=m=>{tc.classList.toggle('pri',m==='c');tq.classList.toggle('pri',m==='q');m==='c'?startCards():startQuiz()};
tc.onclick=()=>tab('c');tq.onclick=()=>tab('q');
[rf,rp,rn].forEach(e=>e.onchange=()=>{paintStats();tab(tq.classList.contains('pri')?'q':'c')});
paintStats();tab('c');
})();
