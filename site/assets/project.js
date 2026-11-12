const notice=document.querySelector('#notice');
function show(title,text){document.querySelector('#noticeTitle').textContent=title;document.querySelector('#noticeText').textContent=text;notice.showModal()}
for(const id of ['paperLink','paperResource'])document.querySelector('#'+id).onclick=()=>show('论文筹备中','EgoLens 的论文尚未完成。正式论文链接会更新到这里；页面底部列出的 EgoLife、SAM2 与 Qwen2.5-VL 是基础工作。');
document.querySelector('.dialog-close').onclick=()=>notice.close();document.querySelector('#noticeOkay').onclick=()=>notice.close();notice.onclick=e=>{if(e.target===notice){const r=notice.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)notice.close()}};
fetch('./site.json').then(r=>r.json()).then(c=>{if(c.paper_url){const b=document.querySelector('#paperLink');b.innerHTML='Paper <span>↗</span>';b.onclick=()=>window.open(c.paper_url,'_blank','noopener');document.querySelector('#paperNote').textContent='论文与代码一起，完整呈现方法';document.querySelector('#paperResource').onclick=()=>window.open(c.paper_url,'_blank','noopener')}}).catch(()=>{});
if(matchMedia('(prefers-reduced-motion: reduce)').matches)document.querySelector('.hero-video video').pause();
