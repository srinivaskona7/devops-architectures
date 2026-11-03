/* Practice panels on topic pages: a short quiz at the end of every section and a mixed review at the end of the topic. */
(()=>{
const F=document.body.dataset.folder,C=window.PQCore,LS=window.localStorage;
const D=(window.__PQ||{})[F];
if(!F||!D||!C)return;
D.sections.forEach(s=>s.c.forEach(c=>c.f=F));
const $$=(s,r=document)=>[...r.querySelectorAll(s)];
const present=id=>!!document.getElementById(id);
const all=()=>D.sections.flatMap(s=>s.c).filter(c=>present(c.id));
const h=C.h;
$$('.practice').forEach(el=>{
  const sec=el.dataset.sec,star=sec==='*';
  const cs=star?all():((D.sections.find(s=>s.id===sec)||{c:[]}).c.filter(c=>present(c.id)));
  const max=star?15:6,key='dop:score:'+F+':'+sec;
  const n=C.build(cs,all(),999).length;
  if(n<1){el.remove();return}
  const wrap=h('div','pwrap');el.append(wrap);
  const getBest=()=>{try{return JSON.parse(LS.getItem(key)||'null')}catch(e){return null}};
  function intro(){
    wrap.replaceChildren();
    const t=h('div','pt');
    t.append(h('b',null,star?'Review this topic':'Practice this section'),document.createTextNode(' · '+Math.min(max,n)+' questions from what you just read'));
    wrap.append(t);
    const best=getBest();
    if(best)wrap.append(h('div','pbest','Best score: '+best.s+' of '+best.t));
    const b=h('button','btn pri','Start questions');b.type='button';b.onclick=run;wrap.append(b);
  }
  function run(){
    const qs=C.build(cs,all(),max);
    C.runQuiz(wrap,qs,{retry:run,after:intro,onDone:(s,t)=>{const b=getBest();if(!b||s/t>b.s/b.t)LS.setItem(key,JSON.stringify({s,t,d:Date.now()}))}});
  }
  intro();
});
})();
