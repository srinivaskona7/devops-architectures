/* Shared practice engine. Builds questions from concept data and runs a quiz inside a container.
   Offline, no dependencies. Used by topic pages (practice.js) and review.html (review.js). */
(()=>{
const LS=window.localStorage;
const shuffle=a=>{a=a.slice();for(let i=a.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]]}return a};
const clip=(t,n)=>{t=(t||'').replace(/\s+/g,' ').trim();if(t.length<=n)return t;const cut=t.slice(0,n),i=Math.max(cut.lastIndexOf('. '),cut.lastIndexOf('; '));return i>60?cut.slice(0,i+1):cut.replace(/\s+\S*$/,'')+'…'};
const STOP=new Set(['and','with','from','their','about','using','into','your','that','this','what','when']);
/* a plain-words description "leaks" if it repeats a distinctive word of the concept title, which would give the answer away */
const mask=(title,plain)=>{let t=plain;title.split(/[^A-Za-z0-9]+/).filter(w=>w.length>=4&&!STOP.has(w.toLowerCase())).forEach(w=>{const stem=w.replace(/(ing|ed|es|s)$/i,'');if(stem.length>=3)t=t.replace(new RegExp('\\b'+stem.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'\\w*','gi'),'_____')});return t};
const maskedEnough=t=>(t.match(/_____/g)||[]).length<=3;
const today=()=>Math.floor((Date.now()-new Date().getTimezoneOffset()*6e4)/864e5);
function srs(){try{return JSON.parse(LS.getItem('dop:srs')||'{}')}catch(e){return{}}}
function srsSave(s){LS.setItem('dop:srs',JSON.stringify(s))}
function srsAdd(keys){const s=srs(),t=today();let n=0;keys.forEach(k=>{if(!s[k]){s[k]={b:0,d:t};n++}else if(s[k].d>t){s[k]={b:0,d:t};n++}});srsSave(s);return n}

/* cs = concepts to ask about, all = wider pool used when cs has too few distractors, max = number of questions */
function build(cs,all,max){
  const qs=[],ownA=[],allA=[];
  cs.forEach(c=>(c.k||[]).forEach(x=>ownA.push({a:x[1],c:c.id})));
  all.forEach(c=>(c.k||[]).forEach(x=>allA.push({a:x[1],c:c.id})));
  const pickA=(c,a)=>{const seen=new Set([a]),out=[];for(const src of [shuffle(ownA),shuffle(allA)]){for(const x of src){if(x.c===c.id||seen.has(x.a))continue;seen.add(x.a);out.push(x.a);if(out.length===3)return out}}return out};
  cs.forEach(c=>{
    const f=c.f||'';
    (c.k||[]).forEach(([q,a],i)=>{const d=pickA(c,a);if(d.length<3)return;qs.push({q,opts:shuffle([a,...d]),ans:a,why:a,cid:c.id,ct:c.t,sk:f+'#'+c.id+'#k'+i})});
    const o=c.o||[];
    if(o.length>=3){const names=o.map(x=>x[0]);o.forEach(([opt,when,avoid])=>{const w=when.replace(/[.\s]+$/,''),v=avoid.replace(/[.\s]+$/,'');qs.push({q:'Which option fits this situation: '+w+'?',opts:shuffle([opt,...shuffle(names.filter(n=>n!==opt)).slice(0,3)]),ans:opt,why:opt+' fits because '+w+'. Avoid it when '+v+'.',cid:c.id,ct:c.t,sk:f+'#'+c.id+'#p'})})}
    const mp=c.p?mask(c.t,c.p):'';
    if(c.p&&c.p.length>40&&maskedEnough(mp)&&mp.replace(/_____/g,'').trim().length>30){
      const titles=[...new Set(shuffle(cs.filter(x=>x.id!==c.id).map(x=>x.t)).concat(shuffle(all.filter(x=>x.id!==c.id).map(x=>x.t))))].filter(t=>t!==c.t).slice(0,3);
      if(titles.length===3)qs.push({q:'Which concept is this? '+clip(mp,230),opts:shuffle([c.t,...titles]),ans:c.t,why:c.t+': '+clip(c.p,300),cid:c.id,ct:c.t,sk:f+'#'+c.id+'#p'});
    }
  });
  return shuffle(qs).slice(0,max);
}

const h=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e};
function runQuiz(el,qs,o){
  o=o||{};let i=0,score=0;const missed=[];
  const onKey=e=>{
    if(/INPUT|TEXTAREA|SELECT/.test((e.target||{}).tagName))return;
    const k=e.key.toLowerCase(),idx='abcd'.indexOf(k)>=0?'abcd'.indexOf(k):('1234'.indexOf(k)>=0?'1234'.indexOf(k):-1);
    const btns=el.querySelectorAll('.qopt');
    if(idx>=0&&btns[idx]&&!btns[idx].disabled){btns[idx].click();e.preventDefault()}
    else if((e.key==='Enter'||e.key==='ArrowRight')&&el.querySelector('.qnext')){el.querySelector('.qnext').click();e.preventDefault()}
  };
  document.addEventListener('keydown',onKey);
  function show(){
    el.replaceChildren();
    if(i>=qs.length)return done();
    const q=qs[i],card=h('div','qz');
    card.append(h('div','qzh','Question '+(i+1)+' of '+qs.length+' · '+q.ct));
    card.append(h('div','qq',q.q));
    const box=h('div','qopts');
    q.opts.forEach((t,k)=>{const b=h('button','qopt');b.type='button';b.append(h('b',null,String.fromCharCode(65+k)+'  '),document.createTextNode(t));b.onclick=()=>answer(b,t);box.append(b)});
    card.append(box);el.append(card);
    function answer(b,t){
      const ok=t===q.ans;if(ok)score++;else missed.push(q);
      const ci=q.opts.indexOf(q.ans);
      [...box.children].forEach((x,k)=>{x.disabled=true;if(k===ci)x.classList.add('ok')});
      if(!ok)b.classList.add('no');
      const fb=h('div','qwhy '+(ok?'good':'bad'));fb.append(h('b',null,ok?'Correct. ':'Not quite. '),document.createTextNode(q.why));
      const nx=h('button','btn pri qnext',i+1<qs.length?'Next →':'See result');nx.type='button';nx.onclick=()=>{i++;show()};
      card.append(fb,nx);
    }
  }
  function done(){
    document.removeEventListener('keydown',onKey);
    el.replaceChildren();
    const pct=Math.round(100*score/qs.length),c=h('div','qz');
    c.append(h('div','qzh','Result'),h('div','qq',score+' of '+qs.length+' correct ('+pct+'%)'));
    c.append(h('p','muted',pct>=80?'Strong. The flashcards will keep it fresh.':pct>=50?'Partly there. Re-read what you missed, then try again.':'Re-read this part first, then try again.'));
    if(missed.length){const u=h('ul','qmiss');missed.forEach(m=>{const li=h('li');li.append(h('b',null,m.ct+': '),document.createTextNode(clip(m.q,140)+' → '+clip(m.ans,200)));u.append(li)});c.append(h('div','qzh','Review these'),u)}
    const row=h('div','qrow');
    const again=h('button','btn pri','Try different questions');again.type='button';again.onclick=()=>o.retry&&o.retry();row.append(again);
    if(missed.length){const add=h('button','btn qadd','Add '+missed.length+' to flashcards');add.type='button';add.onclick=()=>{const n=srsAdd(missed.map(m=>m.sk));add.textContent=n?'Added '+n+' ✓':'Already in your flashcards ✓';add.disabled=true};row.append(add)}
    if(o.after){const back=h('button','btn','Close');back.type='button';back.onclick=o.after;row.append(back)}
    c.append(row);el.append(c);
    if(o.onDone)o.onDone(score,qs.length,missed);
  }
  show();
}
window.PQCore={build,runQuiz,srs,srsSave,srsAdd,today,shuffle,clip,h};
})();
