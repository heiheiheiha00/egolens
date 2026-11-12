const root=document.querySelector('#experience');
let cases=[],active=0,step=0,mediaKey='',clipEnd=null;
const escapeText=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function current(){return cases[active]}
function renderCase(){
  const c=current();step=0;mediaKey='';
  document.querySelector('#experienceTabs').innerHTML=cases.map((c,i)=>`<button role="tab" aria-selected="${i===active}" id="case-tab-${i}" aria-controls="experiencePanel" data-case="${i}"><span>0${i+1}</span>${escapeText(c.label)}</button>`).join('');
  document.querySelectorAll('[data-case]').forEach(b=>{b.onclick=()=>{active=Number(b.dataset.case);renderCase()};b.onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();active=(active+(e.key==='ArrowRight'?1:-1)+cases.length)%cases.length;renderCase();document.querySelector('#case-tab-'+active).focus()}}});
  document.querySelector('#experiencePanel').setAttribute('aria-labelledby','case-tab-'+active);
  document.querySelector('#caseTitle').textContent=c.title;document.querySelector('#caseIntro').textContent=c.intro;
  renderStep();
}
function renderStep(){
  const c=current(),t=c.turns[step],clip=c.clips[t.clip],v=document.querySelector('#caseVideo');
  if(mediaKey!==t.clip){v.pause();v.src=clip.video;v.poster=clip.poster;v.muted=!clip.audio;v.load();mediaKey=t.clip}
  clipEnd=null;
  document.querySelector('#caseStage').textContent=t.stage;document.querySelector('#caseQuestion').textContent=t.question;document.querySelector('#caseAnswer').textContent=t.answer;
  document.querySelector('#caseQuestionLabel').textContent=t.question_label||'用户问题';
  document.querySelector('#answerLabel').textContent=t.answer_label||'历史回答';
  document.querySelector('#caseNote').textContent=t.note||'';
  document.querySelector('#caseSource').textContent=clip.source+' · 网页节选 '+clip.start.toFixed(2)+'–'+clip.end.toFixed(2)+'s';
  document.querySelector('#caseHistory').innerHTML=c.turns.slice(0,step).map((x,i)=>`<button data-past="${i}"><span>${i+1}</span>${escapeText(x.question)}</button>`).join('');
  document.querySelectorAll('[data-past]').forEach(b=>b.onclick=()=>{step=Number(b.dataset.past);renderStep()});
  document.querySelector('#caseEvidence').innerHTML=(t.evidence||[]).map((e,i)=>`<button class="case-evidence" data-evidence="${i}"><span>▶ ${escapeText(e.id)}</span><b>${escapeText(e.label)}</b><small>${escapeText(e.time_label)}</small></button>`).join('');
  document.querySelectorAll('[data-evidence]').forEach(b=>b.onclick=async()=>{const e=t.evidence[Number(b.dataset.evidence)];if(v.readyState<1)await new Promise(r=>v.addEventListener('loadedmetadata',r,{once:true}));v.currentTime=Math.max(0,Math.min(v.duration,e.start-clip.start));clipEnd=Math.max(0,Math.min(v.duration,e.end-clip.start));if(clip.audio)v.muted=false;await v.play();document.querySelector('#casePlayLabel').textContent='正在回放 '+e.label});
  document.querySelector('#caseSteps').innerHTML=c.turns.map((x,i)=>`<button data-step="${i}" aria-label="回看${escapeText(x.stage)}" aria-current="${i===step?'step':'false'}">${i+1}</button>`).join('');
  document.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>{step=Number(b.dataset.step);renderStep()});
  document.querySelector('#caseProgress').textContent=(step+1)+' / '+c.turns.length;
  document.querySelector('#casePrev').disabled=step===0;document.querySelector('#caseNext').disabled=step===c.turns.length-1;
  document.querySelector('#caseNext').textContent=step===c.turns.length-1?'已到最后一轮':'下一步 →';
  document.querySelector('#casePlayLabel').textContent='来源片段 · '+(clip.audio?'含原始语音':'静音预录');
}
document.querySelector('#casePrev').onclick=()=>{if(step>0){step--;renderStep()}};
document.querySelector('#caseNext').onclick=()=>{if(step<current().turns.length-1){step++;renderStep()}};
document.querySelector('#caseVideo').ontimeupdate=()=>{const v=document.querySelector('#caseVideo');if(clipEnd!==null&&v.currentTime>=clipEnd){v.pause();clipEnd=null}};
fetch('./assets/experience.json').then(r=>{if(!r.ok)throw Error('missing record');return r.json()}).then(data=>{cases=data.cases;renderCase();root.dataset.loaded='true'}).catch(()=>{document.querySelector('#caseTitle').textContent='记录暂时无法加载，请刷新重试';root.dataset.loaded='error'});
