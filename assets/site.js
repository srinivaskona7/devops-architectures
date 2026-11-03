/* DevOps & Cloud Architecture Path - interactive behaviour. No dependencies; works from file://. */
(()=>{
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const root=document.documentElement;root.classList.add('js');
const FOLDER=document.body.dataset.folder||'',LS=window.localStorage;
const reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
const params=new URLSearchParams(location.search);
if(params.has('all')||params.has('print'))root.classList.add('all');
/* theme */
const saved=LS.getItem('dop:theme');
root.dataset.theme=saved||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
const tb=$('#theme');if(tb)tb.onclick=()=>{root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';LS.setItem('dop:theme',root.dataset.theme)};
/* topics menu + mobile drawer */
const menu=$('.menu'),mb=$('.menu>button');
if(mb)mb.onclick=e=>{e.stopPropagation();menu.classList.toggle('open')};
document.addEventListener('click',e=>{if(menu&&!menu.contains(e.target))menu.classList.remove('open')});
const side=$('.side'),sb=$('#sidebtn');if(sb)sb.onclick=()=>side.classList.toggle('open');
/* my selection: when a plan is saved, drop unselected sections and concepts before anything is indexed */
(()=>{
  if(params.get('plan')==='1')LS.setItem('dop:planOn','1');
  if(params.get('plan')==='0')LS.setItem('dop:planOn','0');
  let plan=[];try{plan=JSON.parse(LS.getItem('dop:plan')||'[]')}catch(e){}
  const mine=new Set(plan.filter(k=>k.startsWith(FOLDER+'#')).map(k=>k.slice(FOLDER.length+1)));
  if(!FOLDER||LS.getItem('dop:planOn')!=='1'||!mine.size)return;
  let kept=0,all=0;
  $$('.sec').forEach(s=>{
    if(s.id==='overview'||s.id==='review')return;
    const cs=$$('.concept',s);all+=cs.length;
    if(!cs.some(c=>mine.has(c.id))){s.remove();const li=$$('.toc>li').find(l=>l.dataset.sec===s.id);if(li)li.remove();$$('a.sc').filter(a=>a.getAttribute('href')==='#'+s.id).forEach(a=>a.remove());return}
    cs.forEach(c=>{
      if(mine.has(c.id)){kept++;return}
      c.remove();
      $$('.toc a').filter(a=>{const h=a.getAttribute('href');return h==='#'+c.id||h.startsWith('#'+c.id+'-h')}).forEach(a=>{const li=a.closest('li');if(li)li.remove()});
    });
  });
  /* repair previous/next buttons for the sections that remain */
  const ids=$$('.sec').map(s=>s.id),nf=$('#nextfolder');
  ids.forEach((id,i)=>{const p=$('.pager',document.getElementById(id));if(!p)return;
    const pv=$('a:not(.pri)',p),nx=$('a.pri',p);
    if(pv&&i>0)pv.setAttribute('href','#'+ids[i-1]);
    if(nx){if(i+1<ids.length)nx.setAttribute('href','#'+ids[i+1]);else if(nf)nx.setAttribute('href',nf.getAttribute('href'))}});
  const b=document.createElement('div');b.className='callout tip planbanner';
  b.innerHTML='<b class="t">Your selection</b><span></span><a class="btn" href="../plan.html">Edit selection</a><a class="btn" id="planoff" href="#">Show everything</a>';
  b.querySelector('span').textContent='Showing '+kept+' of '+all+' concepts in this topic. Topics where you picked nothing are shown in full.';
  const inner=$('.inner');if(inner)inner.insertBefore(b,inner.firstChild);
  b.querySelector('#planoff').onclick=e=>{e.preventDefault();LS.setItem('dop:planOn','0');location.hash='';location.reload()};
})();
/* sections */
const secs=$$('.sec'),order=secs.map(s=>s.id);
const toc=$$('.toc>li');
const done=new Set(JSON.parse(LS.getItem('dop:done:'+FOLDER)||'[]'));
function paintDone(){toc.forEach(li=>li.classList.toggle('done',done.has(li.dataset.sec)))}
function show(id,anchor){
  if(!order.includes(id))id=order[0];
  secs.forEach(s=>s.classList.toggle('show',s.id===id));
  toc.forEach(li=>li.classList.toggle('active',li.dataset.sec===id));
  const i=order.indexOf(id);cur=i;
  const p=$('#prev'),n=$('#next');
  if(p){p.disabled=false;p.onclick=()=>go(i>0?order[i-1]:null,-1)}
  if(n){n.disabled=false;n.onclick=()=>go(i<order.length-1?order[i+1]:null,1)}
  const c=$('.crumb');if(c){const t=$('.sec.show h2,.sec.show h1');c.textContent=(c.dataset.base||'')+(t?' / '+t.textContent:'')}
  if(side)side.classList.remove('open');
  if(anchor){const el=document.getElementById(anchor);if(el)el.scrollIntoView();}else window.scrollTo(0,0);
  replayAll($('.sec.show'));
}
function go(id,dir){
  if(id){location.hash='#'+id;return}
  const a=$(dir<0?'#prevfolder':'#nextfolder');if(a)location.href=a.href;
}
let cur=0;
function route(){
  let h=decodeURIComponent(location.hash.slice(1));
  if(!h){show(order[0]);return}
  if(order.includes(h)){show(h);return}
  const el=document.getElementById(h);
  if(el){const s=el.closest('.sec');if(s){show(s.id,h);return}}
  show(order[0]);
}
addEventListener('hashchange',()=>{stopTour();route()});
$$('.markdone').forEach(b=>b.onclick=()=>{const id=b.dataset.sec;done.add(id);LS.setItem('dop:done:'+FOLDER,JSON.stringify([...done]));paintDone();const i=order.indexOf(id);go(i<order.length-1?order[i+1]:null,1)});
const filt=$('#filter');
if(filt)filt.oninput=()=>{const q=filt.value.trim().toLowerCase();toc.forEach(li=>{const t=li.textContent.toLowerCase();li.style.display=!q||t.includes(q)?'':'none'})};
/* diagrams: sweep (one lit at a time) or reveal (accumulate) */
const players=new Map();
function play(dg){
  stop(dg);
  const items=$$('[data-s]',dg).sort((a,b)=>(+a.dataset.s)-(+b.dataset.s));
  if(!items.length)return;
  const reveal=dg.classList.contains('reveal');
  if(reduce){dg.classList.add('still');return}
  let k=-1;
  const tick=()=>{k++;
    if(k>items.length){k=-1;items.forEach(e=>e.classList.remove('on'));return}
    if(k===items.length)return;
    if(!reveal)items.forEach(e=>e.classList.remove('on'));
    items[k].classList.add('on');
  };
  tick();players.set(dg,setInterval(tick,reveal?950:1100));
  const b=$('button',dg);if(b)b.textContent='⏸ Pause';
}
function stop(dg){const t=players.get(dg);if(t){clearInterval(t);players.delete(dg)}const b=$('button',dg);if(b)b.textContent='▶ Replay'}
function replayAll(scope){(scope?$$('.dg[data-anim]',scope):[]).forEach(d=>{d.querySelectorAll('[data-s]').forEach(e=>e.classList.remove('on'));play(d)})}
$$('.dg[data-anim] button').forEach(b=>b.onclick=()=>{const d=b.closest('.dg');if(players.has(d)){stop(d)}else{d.querySelectorAll('[data-s]').forEach(e=>e.classList.remove('on'));play(d)}});
const io='IntersectionObserver' in window?new IntersectionObserver(es=>es.forEach(e=>{const d=e.target;if(!e.isIntersecting&&players.has(d))stop(d)}),{threshold:0}):null;
$$('.dg[data-anim]').forEach(d=>io&&io.observe(d));
/* code copy */
$$('.code button').forEach(b=>b.onclick=()=>{const t=b.closest('.code').querySelector('pre').innerText;(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(()=>{b.textContent='Copied'},()=>{b.textContent='Select + copy'});setTimeout(()=>b.textContent='Copy',1400)});
/* guided tour: Start walks through every concept of the section, then the next section; Stop ends it */
let tour=null;
const bs=$('#start'),bx=$('#stop');
function stopTour(){if(tour){clearTimeout(tour.t);$$('.concept.focus').forEach(c=>c.classList.remove('focus'));tour=null}
  if(bs){bs.disabled=false;bs.classList.remove('on')}if(bx)bx.disabled=true}
function startTour(){
  stopTour();if(bs){bs.disabled=true;bs.classList.add('on')}if(bx)bx.disabled=false;
  tour={t:0};
  const run=(si,ci)=>{
    if(!tour)return;
    const sec=document.getElementById(order[si]);
    const cs=$$('.concept',sec);
    if(si!==cur)show(order[si]);
    if(ci>=cs.length){ if(si+1<order.length){location.hash='#'+order[si+1];tour={t:setTimeout(()=>run(si+1,0),700)};return} stopTour();return}
    $$('.concept.focus').forEach(c=>c.classList.remove('focus'));
    const c=cs[ci];c.classList.add('focus');c.scrollIntoView({behavior:'smooth',block:'start'});if(subsOn)conceptSubtitle(c);
    const d=$('.dg[data-anim]',c);if(d)play(d);
    const words=(c.innerText||'').split(/\s+/).length;
    tour.t=setTimeout(()=>run(si,ci+1),Math.max(7000,Math.min(26000,words*190)));
  };
  run(Math.max(cur,0),0);
}
if(bs)bs.onclick=startTour;if(bx){bx.onclick=stopTour;bx.disabled=true}
addEventListener('wheel',()=>{},{passive:true});
addEventListener('keydown',e=>{if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;
  if(e.key==='ArrowRight'){e.preventDefault();$('#next')&&$('#next').click()}
  else if(e.key==='ArrowLeft'){e.preventDefault();$('#prev')&&$('#prev').click()}
  else if(e.key==='Escape'){stopTour()}
  else if(e.key==='t'||e.key==='T'){tour?stopTour():startTour()}});

/* subtitles: plain-words summary of the concept in view (or the one the tour is on) */
const subs=$('#subs'),sbtn=$('#subsbtn'),tbtn=$('#textbtn');
function setFlag(cls,on,key,btn){root.classList.toggle(cls,on);if(btn)btn.classList.toggle('on',on);LS.setItem(key,on?'1':'0')}
let subsOn=LS.getItem('dop:subs')==='1',textOn=LS.getItem('dop:text')==='1';
function conceptSubtitle(c){
  if(!c||!subs)return;
  const t=$('.tile.plain',c),h=c.querySelector('h3');
  const body=t?t.innerText.replace(/^In plain words\s*/i,'').trim():'';
  subs.innerHTML='<small></small><span></span>';
  subs.firstChild.textContent=h?h.textContent:'';subs.lastChild.textContent=body;
  subs.classList.toggle('has',!!body);
}
let lastC=null;
function pickInView(){
  if(!subsOn||tour)return;
  const sec=$('.sec.show');if(!sec)return;
  const mid=innerHeight*0.38;let best=null,bd=1e9;
  $$('.concept',sec).forEach(c=>{const r=c.getBoundingClientRect();if(r.bottom<80||r.top>innerHeight)return;
    const d=r.top<=mid&&r.bottom>=mid?0:Math.min(Math.abs(r.top-mid),Math.abs(r.bottom-mid));if(d<bd){bd=d;best=c}});
  if(best!==lastC){lastC=best;conceptSubtitle(best)}
  if(!best&&subs)subs.classList.remove('has');
}
addEventListener('scroll',()=>{if(subsOn&&!tour)requestAnimationFrame(pickInView)},{passive:true});
if(sbtn)sbtn.onclick=()=>{subsOn=!subsOn;setFlag('subs-on',subsOn,'dop:subs',sbtn);lastC=null;if(subsOn)pickInView();else if(subs)subs.classList.remove('has')};
if(tbtn)tbtn.onclick=()=>{textOn=!textOn;setFlag('text-mode',textOn,'dop:text',tbtn)};
setFlag('subs-on',subsOn,'dop:subs',sbtn);setFlag('text-mode',textOn,'dop:text',tbtn);
addEventListener('keydown',e=>{if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;if(e.key==='c'||e.key==='C')sbtn&&sbtn.click();if(e.key==='r'||e.key==='R')tbtn&&tbtn.click()});
paintDone();route();
if(subsOn)setTimeout(pickInView,200);
})();
