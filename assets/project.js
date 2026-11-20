const cases = {
  memory: ['换了话题，还记得床品的颜色吗？','先询问床品，再切换到手机。第三轮回到床品时，回答引用了第一轮的原始片段。'],
  recall: ['手接触键盘之前，屏幕亮着吗？','第一轮缺少屏幕状态。补看请求将观察范围收窄到接触前的八秒，回答引用新增证据 E2。'],
  speech: ['电脑装回去了没有？','打开声音，听原始对话，再看系统如何依据带时间戳的语音回答追问。'],
  tracking: ['视角变化时，工具移动到了哪里？','先看原始片段，再看同一工具的区域传播。侧栏记录操作与追踪结果。']
};
const video = document.querySelector('#film');
const tabs = [...document.querySelectorAll('[role=tab]')];
const panel = document.querySelector('#panel');
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
function select(tab, play) {
  const name = tab.dataset.case;
  tabs.forEach(t => { t.tabIndex = t === tab ? 0 : -1; t.setAttribute('aria-selected', String(t === tab)); });
  panel.setAttribute('aria-labelledby',tab.id);
  video.pause();
  video.poster = './assets/films/' + name + '.jpg';
  video.src = './assets/films/' + name + '.mp4';
  video.muted = name !== 'speech';
  document.querySelector('#filmTitle').textContent = cases[name][0];
  document.querySelector('#filmText').textContent = cases[name][1];
  if (play) video.play().catch(()=>{});
}
tabs.forEach((tab,i) => {
  tab.id = 'tab-' + tab.dataset.case; tab.setAttribute('aria-controls','panel');
  tab.onclick = () => select(tab,true);
  tab.onkeydown = e => {
    const index = {ArrowRight:(i+1)%tabs.length,ArrowLeft:(i+tabs.length-1)%tabs.length,Home:0,End:tabs.length-1}[e.key];
    if(index === undefined) return;
    e.preventDefault(); tabs[index].focus(); select(tabs[index],true);
  };
});
select(tabs[0],false);
if (reduced) document.querySelector('.herofig video').pause();
else new IntersectionObserver((entries,observer)=>{if(entries[0].isIntersecting){if(video.paused && video.currentTime===0) video.play().catch(()=>{});observer.disconnect();}},{threshold:.25}).observe(video);
