(() => {
  const SYMBOL = 'XAUUSD';
  const MAGIC = 260903;
  const $ = id => document.getElementById(id);
  let activePage = 'dashboard';
  let regionHost = 'https://mt-client-api-v1.new-york.agiliumtrade.ai';
  let busy = false;

  const css = `
    .monitor-page{display:none}.monitor-page.active{display:block}.monitor-card{background:linear-gradient(145deg,#0b1821,#081118);border:1px solid #16313d;border-radius:17px;padding:15px;margin:11px 0;box-shadow:0 8px 24px #0005}.monitor-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.monitor-stat{background:#071018;border:1px solid #122b36;border-radius:12px;padding:11px}.monitor-stat small{display:block;color:#8299a3;font-size:9px;text-transform:uppercase}.monitor-stat strong{display:block;font-size:18px;margin-top:5px}.trade-row{border-top:1px solid #16313d;padding:12px 0}.trade-row:first-child{border-top:0}.trade-main{display:flex;justify-content:space-between;gap:8px}.trade-side{font-weight:800}.trade-meta{color:#80949e;font-size:10px;margin-top:4px}.trade-profit{font-weight:800}.monitor-empty{color:#8299a3;font-size:11px;padding:12px 0;text-align:center}.monitor-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:9px}.monitor-head b{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#b8c8cf}.refresh-note{font-size:9px;color:#68808b}.win{color:#23e58a}.loss{color:#ff4c4c}`;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  function token(){ return String(localStorage.getItem('metaapi.token') || '').trim(); }
  function accountId(){ return String(localStorage.getItem('metaapi.accountId') || '').trim(); }
  function ours(x){ return x && x.symbol === SYMBOL && (Number(x.magic) === MAGIC || String(x.clientId || '').startsWith('MB_')); }
  function side(x){ const t=String(x.type||'').toUpperCase(); return t.includes('BUY')?'BUY':t.includes('SELL')?'SELL':'—'; }
  function money(x){ const n=Number(x); return Number.isFinite(n)?n.toFixed(2):'0.00'; }
  function esc(s){ return String(s??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\\':'&#39;'}[c])); }
  async function apiGet(path){ const r=await fetch(regionHost+path,{headers:{'Accept':'application/json','auth-token':token()}}); if(!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.json(); }

  async function resolveRegion(){
    try{
      const r=await fetch('https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai/users/current/accounts/'+encodeURIComponent(accountId()),{headers:{'Accept':'application/json','auth-token':token()}});
      if(r.ok){ const a=await r.json(); const region=String(a.region||'new-york').toLowerCase(); if(region==='london') regionHost='https://mt-client-api-v1.london.agiliumtrade.ai'; }
    }catch(_){ }
  }

  function ensurePages(){
    if($('pipsMonitorStyle')) return;
    const nav=[...document.querySelectorAll('.nav div')];
    nav.forEach((n,i)=>{ n.style.cursor='pointer'; n.onclick=()=>showPage(i===1?'trades':i===2?'history':i===3?'logs':'dashboard'); });
    const main=document.querySelector('main');
    const marker=document.createElement('div'); marker.id='pipsMonitorPages';
    marker.innerHTML=`
      <section id="monitor-trades" class="monitor-page">
        <div class="monitor-card"><div class="monitor-head"><b>Live trades</b><span class="refresh-note" id="liveRefresh">LIVE</span></div><div id="liveTrades"></div></div>
      </section>
      <section id="monitor-history" class="monitor-page">
        <div class="monitor-card"><div class="monitor-head"><b>Closed trades</b><span class="refresh-note">MetaApi history</span></div><div class="monitor-stats"><div class="monitor-stat"><small>Win rate</small><strong class="cyan" id="winRate">—</strong></div><div class="monitor-stat"><small>Wins</small><strong class="win" id="wins">0</strong></div><div class="monitor-stat"><small>Losses</small><strong class="loss" id="losses">0</strong></div></div><div id="closedTrades" style="margin-top:10px"></div></div>
      </section>
      <section id="monitor-logs" class="monitor-page">
        <div class="monitor-card"><div class="monitor-head"><b>Trade logs</b><span class="refresh-note">Closed + result</span></div><div id="tradeLogs"></div></div>
      </section>`;
    const navEl=document.querySelector('.nav'); navEl.parentNode.insertBefore(marker,navEl.nextSibling);
  }

  function showPage(page){
    ensurePages(); activePage=page;
    document.querySelectorAll('.monitor-page').forEach(x=>x.classList.remove('active'));
    const target=page==='trades'?'monitor-trades':page==='history'?'monitor-history':page==='logs'?'monitor-logs':null;
    if(target) $(target).classList.add('active');
    document.querySelectorAll('.nav div').forEach((n,i)=>n.classList.toggle('active',i===(page==='trades'?1:page==='history'?2:page==='logs'?3:0)));
    if(page!=='dashboard') refresh();
  }

  function renderLive(positions){
    const el=$('liveTrades'); if(!el)return;
    const list=positions.filter(ours);
    el.innerHTML=list.length?list.map(p=>`<div class="trade-row"><div class="trade-main"><span class="trade-side ${side(p)==='BUY'?'win':'loss'}">${side(p)} ${esc(p.symbol)}</span><span class="trade-profit ${Number(p.profit)>=0?'win':'loss'}">${money(p.profit)}</span></div><div class="trade-meta">${money(p.volume)} lot • Entry ${money(p.openPrice)} • Current ${money(p.currentPrice)} • SL ${p.stopLoss?money(p.stopLoss):'—'}</div><div class="trade-meta">Ticket ${esc(p.id)}</div></div>`).join(''):'<div class="monitor-empty">No active Pips-life trades</div>';
    $('liveRefresh').textContent='UPDATED '+new Date().toLocaleTimeString();
  }

  function closedGroups(deals){
    const grouped=new Map();
    for(const d of deals.filter(ours)){ const id=String(d.positionId||d.orderId||d.id); if(!grouped.has(id))grouped.set(id,[]); grouped.get(id).push(d); }
    const out=[];
    for(const [id,ds] of grouped){ const exits=ds.filter(d=>String(d.entryType||'').toUpperCase().includes('OUT')); if(!exits.length)continue; const profit=exits.reduce((s,d)=>s+Number(d.profit||0)+Number(d.swap||0)+Number(d.commission||0),0); const first=ds[0]; const last=exits.sort((a,b)=>Date.parse(b.time)-Date.parse(a.time))[0]; out.push({id,profit,side:side(first),time:last.time,price:last.price,volume:exits.reduce((s,d)=>s+Number(d.volume||0),0)}); }
    return out.sort((a,b)=>Date.parse(b.time)-Date.parse(a.time));
  }

  function renderClosed(items){
    const wins=items.filter(x=>x.profit>0).length, losses=items.filter(x=>x.profit<0).length, total=wins+losses;
    $('wins').textContent=wins; $('losses').textContent=losses; $('winRate').textContent=total?((wins/total)*100).toFixed(1)+'%':'—';
    const html=items.slice(0,100).map(x=>`<div class="trade-row"><div class="trade-main"><span class="trade-side">${esc(x.side)} • ${esc(x.id)}</span><span class="trade-profit ${x.profit>=0?'win':'loss'}">${x.profit>=0?'+':''}${money(x.profit)}</span></div><div class="trade-meta">${new Date(x.time).toLocaleString()} • ${money(x.volume)} lot • Close ${money(x.price)}</div></div>`).join('');
    $('closedTrades').innerHTML=html||'<div class="monitor-empty">No closed Pips-life trades found</div>';
    $('tradeLogs').innerHTML=html||'<div class="monitor-empty">No trade logs yet</div>';
  }

  async function refresh(){
    if(busy || !token() || !accountId()) return; busy=true;
    try{
      await resolveRegion();
      const positions=await apiGet(`/users/current/accounts/${encodeURIComponent(accountId())}/positions`); renderLive(Array.isArray(positions)?positions:[]);
      const end=new Date(), start=new Date(end.getTime()-90*24*3600*1000);
      const deals=await apiGet(`/users/current/accounts/${encodeURIComponent(accountId())}/history-deals/time/${encodeURIComponent(start.toISOString())}/${encodeURIComponent(end.toISOString())}?limit=1000`);
      renderClosed(Array.isArray(deals)?deals:[]);
    }catch(e){
      if($('liveTrades')) $('liveTrades').innerHTML=`<div class="monitor-empty">Monitor unavailable: ${esc(e.message)}</div>`;
    }finally{busy=false;}
  }

  window.addEventListener('load',()=>{ ensurePages(); showPage('dashboard'); setInterval(()=>{ if(activePage!=='dashboard') refresh(); },5000); });
})();
