/* Picker: choose whole topics, sections or single concepts. Saved in localStorage; topic pages filter themselves from it. */
(()=>{
const $=(s,r=document)=>r.querySelector(s),LS=window.localStorage,D=window.__PLAN;
document.documentElement.dataset.theme=LS.getItem('dop:theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
const tb=$('#theme');if(tb)tb.onclick=()=>{const t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;LS.setItem('dop:theme',t)};
const menu=$('.menu'),mb=$('.menu>button');if(mb)mb.onclick=e=>{e.stopPropagation();menu.classList.toggle('open')};
document.addEventListener('click',e=>{if(menu&&!menu.contains(e.target))menu.classList.remove('open')});
let sel=new Set();try{sel=new Set(JSON.parse(LS.getItem('dop:plan')||'[]'))}catch(e){}
const key=(f,c)=>f.slug+'#'+c;
const save=()=>{LS.setItem('dop:plan',JSON.stringify([...sel]));LS.setItem('dop:planOn',sel.size?'1':'0')};
const esc=t=>t.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const tree=$('#tree'),q=$('#q');if(!tree)return;
const total=D.reduce((n,f)=>n+f.secs.reduce((m,s)=>m+s.c.length,0),0);
/* build the tree once; checkboxes carry data keys */
tree.innerHTML=D.map((f,fi)=>`<details class="pf" data-f="${f.slug}" style="border-left:5px solid ${f.accent}"><summary><label><input type="checkbox" data-kind="f" data-f="${f.slug}"> <b>${String(fi).padStart(2,'0')} ${esc(f.title)}</b></label> <span class="cnt" data-cnt="${f.slug}"></span></summary>`+
 f.secs.map(s=>`<details class="ps" data-s="${s.id}"><summary><label><input type="checkbox" data-kind="s" data-f="${f.slug}" data-s="${s.id}"> ${esc(s.title)}</label> <span class="cnt">${s.c.length} concepts</span></summary><ul>`+
  s.c.map(c=>`<li data-t="${esc((f.title+' '+s.title+' '+c[1]).toLowerCase())}"><label><input type="checkbox" data-kind="c" data-f="${f.slug}" data-s="${s.id}" data-c="${c[0]}"> ${esc(c[1])}</label> <a href="${f.slug}/index.html#${c[0]}" title="Open this concept">↗</a></li>`).join('')+`</ul></details>`).join('')+`</details>`).join('');
const boxes=[...tree.querySelectorAll('input')];
const fd=slug=>D.find(f=>f.slug===slug);
function paint(){
  let n=0,pages=0;
  D.forEach(f=>{
    let fc=0,ft=0;
    f.secs.forEach(s=>{let sc=0;s.c.forEach(c=>{ft++;if(sel.has(key(f,c[0]))){sc++;fc++}});
      const b=tree.querySelector(`input[data-kind=s][data-s="${s.id}"]`);b.checked=sc===s.c.length&&sc>0;b.indeterminate=sc>0&&sc<s.c.length});
    const b=tree.querySelector(`input[data-kind=f][data-f="${f.slug}"]`);b.checked=fc===ft&&fc>0;b.indeterminate=fc>0&&fc<ft;
    tree.querySelector(`[data-cnt="${f.slug}"]`).textContent=fc?`${fc} of ${ft} selected`:`${ft} concepts`;
    n+=fc;pages+=fc*f.ppc;
  });
  boxes.filter(b=>b.dataset.kind==='c').forEach(b=>b.checked=sel.has(b.dataset.f+'#'+b.dataset.c));
  $('#stats').innerHTML=`<span class="chip"><b>${n}</b> of ${total} concepts</span><span class="chip"><b>~${Math.round(pages)}</b> A4 pages</span><span class="chip"><b>~${Math.round(n*5/60*10)/10}</b> hours (about 5 min a concept)</span>`;
  save();
}
tree.addEventListener('change',e=>{
  const b=e.target;if(b.tagName!=='INPUT')return;
  const f=fd(b.dataset.f),on=b.checked,k=b.dataset.kind;
  const set=(sid,cid)=>on?sel.add(key(f,cid)):sel.delete(key(f,cid));
  if(k==='c')set(b.dataset.s,b.dataset.c);
  else f.secs.forEach(s=>{if(k==='f'||s.id===b.dataset.s)s.c.forEach(c=>{const li=tree.querySelector(`input[data-c="${c[0]}"][data-f="${f.slug}"]`).closest('li');if(!li.hidden)set(s.id,c[0])})});
  paint();
});
/* search: hide non-matching concepts, open the folders that have matches */
q.oninput=()=>{
  const t=q.value.trim().toLowerCase(),words=t.split(/\s+/).filter(Boolean);
  tree.querySelectorAll('li').forEach(li=>li.hidden=words.length>0&&!words.every(w=>li.dataset.t.includes(w)));
  tree.querySelectorAll('details.ps').forEach(d=>{const any=[...d.querySelectorAll('li')].some(li=>!li.hidden);d.hidden=!any;if(words.length)d.open=any});
  tree.querySelectorAll('details.pf').forEach(d=>{const any=[...d.querySelectorAll('details.ps')].some(x=>!x.hidden);d.hidden=!any;if(words.length)d.open=any});
};
const presets=[['Core DevOps path',['00','01','02','03','04','05','06']],['Cloud: AWS, Azure, GCP',['10','11','12','13']],['Observability and Python',['07','08','09']],['Everything',D.map((_,i)=>String(i).padStart(2,'0'))]];
$('#presets').innerHTML=presets.map((p,i)=>`<button class="btn" data-p="${i}" type="button">${p[0]}</button>`).join('');
$('#presets').onclick=e=>{const b=e.target.closest('[data-p]');if(!b)return;const pre=presets[b.dataset.p][1];
  sel=new Set();D.forEach((f,i)=>{if(pre.includes(String(i).padStart(2,'0')))f.secs.forEach(s=>s.c.forEach(c=>sel.add(key(f,c[0]))))});paint()};
$('#selvis').onclick=()=>{tree.querySelectorAll('li:not([hidden]) input[data-kind=c]').forEach(b=>sel.add(b.dataset.f+'#'+b.dataset.c));paint()};
$('#clr').onclick=()=>{sel=new Set();paint()};
function list(){
  const out=[];D.forEach(f=>{const rows=[];f.secs.forEach(s=>{const cs=s.c.filter(c=>sel.has(key(f,c[0])));if(cs.length)rows.push(`  - ${s.title}: ${cs.map(c=>c[1]).join('; ')}`)});if(rows.length)out.push(`${f.title}\n${rows.join('\n')}`)});
  return out.join('\n');
}
$('#copy').onclick=async()=>{const t=list()||'(nothing selected)';try{await navigator.clipboard.writeText(t);$('#copy').textContent='Copied ✓'}catch(e){window.prompt('Copy your list',t)}setTimeout(()=>$('#copy').textContent='Copy list',1800)};
$('#go').onclick=()=>{const f=D.find(f=>f.secs.some(s=>s.c.some(c=>sel.has(key(f,c[0])))));if(!f){alert('Select at least one concept first.');return}LS.setItem('dop:planOn','1');location.href=f.slug+'/index.html?plan=1'};
paint();
})();
