import MetaApi, { SynchronizationListener } from 'metaapi.cloud-sdk';

const SYMBOL = 'XAUUSD';
const MAGIC = 260903;
const TRAIL_PIPS = 70;
const EXECUTION_VOLUME = 0.01;
const XAUUSD_PIP_SIZE_FALLBACK = 0.01;

const $ = id => document.getElementById(id);
const ui = {
  token: $('token'), account: $('account'), price: $('price'), balance: $('balance'),
  position: $('position'), stop: $('stop'), status: $('status'), save: $('save'),
  change: $('change'), start: $('start'), stopBot: $('stop')
};

let api = null, account = null, connection = null, listener = null;
let trading = false, connecting = false, synchronized = false;
let lastMid = NaN, lastBid = NaN, lastAsk = NaN, previousMid = NaN;
let currentPosition = null, currentStop = null;
let entryInFlight = false, stopActionInFlight = false, reentryScheduled = false, lastStatus = '';
const eventLog = [];
const sessionHistory = [];

function addLog(text) {
  const now = new Date();
  eventLog.unshift({ time: now, text: String(text) });
  if (eventLog.length > 40) eventLog.pop();
  renderLogs();
}

function setStatus(text) {
  const value = String(text);
  if (value !== lastStatus) {
    lastStatus = value;
    ui.status.textContent = value;
    addLog(value);
  }
  renderPageData();
}

function fmt(n) { return Number.isFinite(n) ? Number(n).toFixed(2) : '—'; }
function sideOf(x) { const t = String(x?.type ?? '').toUpperCase(); return t.includes('BUY') ? 'BUY' : t.includes('SELL') ? 'SELL' : ''; }
function isOurs(x) { if (!x || x.symbol !== SYMBOL) return false; return Number(x.magic) === MAGIC || String(x.clientId ?? '').startsWith('MB_'); }
function idOf(x) { return String(x?.id ?? x?.positionId ?? x?.orderId ?? ''); }
function volumeOf(x) { return Number(x?.volume ?? 0); }
function normalizeVolume(raw, spec) { const min=Number(spec?.minVolume??0.01), max=Number(spec?.maxVolume??100), step=Number(spec?.volumeStep??0.01); let v=Math.max(min,Math.min(max,raw)); if(step>0)v=Math.floor(v/step+1e-10)*step; return Number(Math.max(min,v).toFixed(6)); }
function brokerPipSize() { const spec=connection?.terminalState?.specification(SYMBOL); const p=Number(spec?.pipSize??spec?.point??0); return p>0?p:XAUUSD_PIP_SIZE_FALLBACK; }
function brokerDigits() { const spec=connection?.terminalState?.specification(SYMBOL); const d=Number(spec?.digits??2); return Number.isFinite(d)?d:2; }
function normalizePrice(price) { return Number(Number(price).toFixed(brokerDigits())); }
function currentVolume() { const spec=connection?.terminalState?.specification(SYMBOL); return normalizeVolume(EXECUTION_VOLUME,spec||{minVolume:.01,maxVolume:100,volumeStep:.01}); }
function stopCandidate(side,spot,pipSize) { return normalizePrice(side==='BUY' ? spot-TRAIL_PIPS*pipSize : spot+TRAIL_PIPS*pipSize); }
function cleanToken(value) { return String(value??'').trim().replace(/^Bearer\s+/i,''); }
function validAccountId(value) { return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value); }
function sdkConstructor() { const Ctor=MetaApi?.default??MetaApi; if(typeof Ctor!=='function')throw new Error('MetaApi browser SDK constructor is unavailable'); return Ctor; }

class BotListener extends SynchronizationListener {
  onConnected(){ setStatus('MetaApi connected — synchronizing…'); }
  onDisconnected(){ synchronized=false; setStatus('MetaApi disconnected — waiting to reconnect…'); }
  onSynchronizationStarted(){ synchronized=false; setStatus('Synchronizing MetaApi terminal…'); }
  onSynchronizationFinished(){ synchronized=true; setStatus('CONNECTED — XAUUSD live stream active'); reconcile(); }
  onSymbolPricesUpdated(instanceIndex,prices){
    const p=Array.isArray(prices)?prices.find(x=>x?.symbol===SYMBOL):(prices?.symbol===SYMBOL?prices:null); if(!p)return;
    const bid=Number(p.bid),ask=Number(p.ask); if(!Number.isFinite(bid)||!Number.isFinite(ask))return;
    const mid=(bid+ask)/2; previousMid=lastMid; lastMid=mid; lastBid=bid; lastAsk=ask; ui.price.textContent=fmt(mid);
    const info=connection?.terminalState?.accountInformation; if(info?.balance!=null)ui.balance.textContent=fmt(Number(info.balance));
    renderPageData(); if(!trading||!synchronized)return; void onTick(mid,bid,ask);
  }
  onPositionUpdated(instanceIndex,position){ if(position?.symbol===SYMBOL)reconcile(); }
  onPositionRemoved(){
    const hadPosition=!!currentPosition;
    currentPosition=null; currentStop=null; reconcile();
    if(hadPosition&&trading&&synchronized) scheduleReentry('STOP/position close detected');
  }
  onOrderUpdated(instanceIndex,order){ if(order?.symbol===SYMBOL)reconcile(); }
  onOrderCompleted(instanceIndex,order){ if(order?.symbol===SYMBOL)reconcile(); }
  onOrderFailed(instanceIndex,orderId,error){ setStatus(`Order failed: ${error?.message||error}`); reconcile(); }
}

async function connectSdk(){
  if(connecting||connection)return;
  const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();
  if(!token||token==='SAVED TOKEN'){setStatus('MetaAPI token is missing');return;}
  if(!accountId){setStatus('MetaAPI account ID is missing');return;}
  if(!validAccountId(accountId)){setStatus('MetaAPI account ID format is invalid');return;}
  connecting=true; setStatus('Connecting directly to MetaApi…');
  try{
    const MetaApiClass=sdkConstructor(); api=new MetaApiClass(token); account=await api.metatraderAccountApi.getAccount(accountId);
    if(!account?.id)throw new Error('MetaApi account not found'); setStatus('MetaApi account found — checking deployment…');
    if(typeof account.waitConnected==='function')await account.waitConnected();
    connection=account.getStreamingConnection(); listener=new BotListener(); connection.addSynchronizationListener(listener);
    await connection.connect(); await connection.waitSynchronized(); synchronized=true; await connection.subscribeToMarketData(SYMBOL); reconcile();
    setStatus('CONNECTED — XAUUSD live stream active');
  }catch(e){
    const msg=e?.message||String(e); try{if(connection)await connection.close();}catch(_){} try{if(api)await api.close();}catch(_){}
    connection=null;account=null;api=null;synchronized=false;setStatus(`MetaApi connection failed: ${msg}`);
  }finally{connecting=false;renderPageData();}
}

function reconcile(){
  if(!connection?.terminalState)return;
  const state=connection.terminalState;
  const positions=(state.positions||[]).filter(isOurs);
  const legacyStops=(state.orders||[]).filter(isOurs).filter(o=>String(o.type??'').toUpperCase().includes('STOP'));
  // This version uses a broker-side position SL, not an opposite pending stop.
  // Cancel any old Pips-life pending stops left by a previous app version.
  for(const o of legacyStops)void cancelOrder(idOf(o));

  const next=positions[0]||null;
  currentPosition=next;
  const stopPrice=Number(next?.stopLoss??0);
  currentStop=next?{id:idOf(next),openPrice:stopPrice}:null;
  ui.position.textContent=next?sideOf(next):'—';
  ui.stop.textContent=stopPrice>0?fmt(stopPrice):'—';
  renderPageData();

  if(next && (!Number.isFinite(stopPrice)||stopPrice<=0) && !stopActionInFlight) void setInitialStop(next);
  if(!next && trading && synchronized) scheduleReentry('No active position');
}

function tradeOptions(comment){return{comment,magic:MAGIC};}

async function enter(side,spot){
  if(entryInFlight||currentPosition||!connection)return;
  const volume=currentVolume();
  if(volume<=0){setStatus('Cannot size trade: invalid XAUUSD execution volume');return;}
  const pipSize=brokerPipSize();
  const initialStop=stopCandidate(side,Number(spot),pipSize);
  if(!Number.isFinite(initialStop)||initialStop<=0){setStatus('Cannot calculate 70-pip stop');return;}
  entryInFlight=true;
  try{
    const options=tradeOptions('MB Velocity 70pip Trail');
    if(side==='BUY') await connection.createMarketBuyOrder(SYMBOL,volume,initialStop,undefined,options);
    else await connection.createMarketSellOrder(SYMBOL,volume,initialStop,undefined,options);
    setStatus(`OPEN ${side} ${volume} — SL ${fmt(initialStop)} (70 pips)`);
    await waitForPosition(side,3000);
    reconcile();
    if(currentPosition) await setInitialStop(currentPosition);
  }catch(e){setStatus(`Entry failed: ${e?.message||e}`);}finally{entryInFlight=false;}
}

async function waitForPosition(side,timeoutMs){
  const end=Date.now()+timeoutMs;
  while(Date.now()<end){
    reconcile();
    if(currentPosition&&sideOf(currentPosition)===side)return currentPosition;
    await new Promise(r=>setTimeout(r,50));
  }
  return currentPosition;
}

async function setInitialStop(position){
  if(!position||stopActionInFlight||!connection)return;
  const side=sideOf(position),spot=side==='BUY'?Number(lastBid):Number(lastAsk);
  if(!Number.isFinite(spot))return;
  const candidate=stopCandidate(side,spot,brokerPipSize());
  if(!Number.isFinite(candidate)||candidate<=0)return;
  stopActionInFlight=true;
  try{
    await connection.modifyPosition(idOf(position),candidate,undefined);
    currentStop={id:idOf(position),openPrice:candidate};
    ui.stop.textContent=fmt(candidate);
  }catch(e){setStatus(`Initial SL failed: ${e?.message||e}`);}finally{stopActionInFlight=false;}
}

async function trail(bid,ask){
  if(!currentPosition||stopActionInFlight)return;
  const side=sideOf(currentPosition),spot=side==='BUY'?bid:ask;
  const candidate=stopCandidate(side,spot,brokerPipSize());
  const existing=Number(currentPosition.stopLoss??currentStop?.openPrice??0);
  const improve=side==='BUY'?candidate>existing:candidate<existing;
  if(existing>0&&!improve)return;
  if(!Number.isFinite(candidate)||candidate<=0)return;
  stopActionInFlight=true;
  try{
    await connection.modifyPosition(idOf(currentPosition),candidate,undefined);
    currentPosition.stopLoss=candidate;
    currentStop={id:idOf(currentPosition),openPrice:candidate};
    ui.stop.textContent=fmt(candidate);
  }catch(e){setStatus(`SL trail failed: ${e?.message||e}`);}finally{stopActionInFlight=false;}
}

function scheduleReentry(reason){
  if(reentryScheduled||!trading||!synchronized||entryInFlight||currentPosition)return;
  reentryScheduled=true;
  queueMicrotask(()=>{
    reentryScheduled=false;
    if(!trading||!synchronized||entryInFlight||currentPosition)return;
    const prev=previousMid,mid=lastMid;
    if(!Number.isFinite(prev)||!Number.isFinite(mid)||prev===mid){
      setStatus(`${reason} — waiting for next price tick`);
      return;
    }
    const side=prev<mid?'BUY':prev>mid?'SELL':'';
    if(side){
      addLog(`${reason} — immediate ${side} re-entry`);
      void enter(side,side==='BUY'?lastAsk:lastBid);
    }
  });
}

async function onTick(mid,bid,ask){
  if(!trading||!synchronized)return;
  if(!currentPosition){
    if(entryInFlight||!Number.isFinite(previousMid)||previousMid===mid){if(!Number.isFinite(previousMid))setStatus('Streaming XAUUSD — waiting for first movement');return;}
    const side=previousMid<mid?'BUY':previousMid>mid?'SELL':'';
    if(side)await enter(side,side==='BUY'?ask:bid);
    return;
  }
  await trail(bid,ask);
  const sl=Number(currentPosition.stopLoss??currentStop?.openPrice??0);
  setStatus(`Running ${sideOf(currentPosition)} | TRAILING SL ${fmt(sl)} | 70 PIPS`);
}

async function cancelOrder(id){if(id&&connection){try{await connection.cancelOrder(id);}catch(_){}}}

function startForegroundService(){try{if(window.AndroidBot?.startForegroundBot)window.AndroidBot.startForegroundBot();}catch(_) {}}
function stopForegroundService(){try{if(window.AndroidBot?.stopForegroundBot)window.AndroidBot.stopForegroundBot();}catch(_) {}}

function saveCredentials(){
  const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();if(!token||token==='SAVED TOKEN'){setStatus('Enter a valid MetaAPI token');return;}if(!validAccountId(accountId)){setStatus('Enter a valid MetaAPI account ID');return;}
  localStorage.setItem('metaapi.token',token);localStorage.setItem('metaapi.accountId',accountId);ui.token.value='SAVED TOKEN';ui.token.disabled=true;ui.account.value=accountId;const original=token;ui.token.value=original;addLog('Credentials saved locally');connectSdk().finally(()=>{ui.token.value='SAVED TOKEN';ui.token.disabled=true;});
}
function changeCredentials(){trading=false;stopForegroundService();localStorage.removeItem('metaapi.token');localStorage.removeItem('metaapi.accountId');if(connection)connection.close().catch(()=>{});if(api)api.close().catch(()=>{});connection=null;account=null;api=null;synchronized=false;currentPosition=null;currentStop=null;ui.token.disabled=false;ui.token.value='';ui.account.value='';setStatus('Enter new MetaAPI credentials');}
function startBot(){
  if(!connection||!synchronized){setStatus('START BLOCKED — Connect MetaApi first');return;}
  trading=true;startForegroundService();ui.start.classList.add('active');ui.stopBot.classList.remove('active');setStatus('BOT RUNNING — waiting for tick movement');addLog('BOT STARTED — foreground engine requested');renderPageData();
}
function stopBot(){trading=false;stopForegroundService();ui.stopBot.classList.add('active');ui.start.classList.remove('active');setStatus('BOT STOPPED — trading disabled');addLog('BOT STOPPED by user');renderPageData();}

function showPage(name){
  ['dashboard','trades','history','logs'].forEach(p=>{const el=$(`page-${p}`);if(el)el.classList.toggle('active',p===name);const nav=$(`nav-${p}`);if(nav)nav.classList.toggle('active',p===name);});
  renderPageData();window.scrollTo({top:0,behavior:'smooth'});
}
function renderTrades(){
  const el=$('tradesInfo');if(!el)return;
  if(!connection){el.innerHTML='<div class="empty">MetaApi is not connected.<br>Connect from Dashboard to view live trades.</div>';return;}
  const pos=currentPosition, stop=currentStop;
  el.innerHTML=`<div class="info-row"><span>Engine</span><b class="${trading?'green':''}">${trading?'RUNNING':'STOPPED'}</b></div><div class="info-row"><span>Connection</span><b>${synchronized?'CONNECTED':'SYNCING'}</b></div><div class="info-row"><span>Symbol</span><b>${SYMBOL}</b></div><div class="info-row"><span>Position</span><b>${pos?sideOf(pos):'NONE'}</b></div><div class="info-row"><span>Volume</span><b>${pos?fmt(volumeOf(pos))+' LOT':'—'}</b></div><div class="info-row"><span>Entry</span><b>${pos?fmt(Number(pos.openPrice)):'—'}</b></div><div class="info-row"><span>Trailing SL</span><b class="red">${stop&&Number(stop.openPrice)>0?fmt(Number(stop.openPrice)):'—'}</b></div>`;
}
function renderHistory(){
  const el=$('historyInfo');if(!el)return;
  if(!sessionHistory.length){el.innerHTML='<div class="empty">No completed bot events in this app session yet.<br>Closed positions will appear here after the engine records them.</div>';return;}
  el.innerHTML=sessionHistory.slice(0,30).map(x=>`<div class="info-row"><span>${new Date(x.time).toLocaleTimeString()}</span><b>${x.text}</b></div>`).join('');
}
function renderLogs(){
  const el=$('logsInfo');if(!el)return;
  el.innerHTML=eventLog.length?eventLog.map(x=>`<div class="log-row"><span class="log-time">${x.time.toLocaleTimeString()}</span>${String(x.text).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</div>`).join(''):'<div class="empty">No events yet.</div>';
}
function renderPageData(){
  const p=currentPosition,s=currentStop;
  if($('sideBadge')){const side=sideOf(p);$('sideBadge').textContent=side||'WAITING';$('sideBadge').classList.toggle('sell',side==='SELL');}
  if($('positionPrice'))$('positionPrice').textContent=p?fmt(Number(p.openPrice)):'—';
  if($('stopDetail'))$('stopDetail').textContent=s&&Number(s.openPrice)>0?fmt(Number(s.openPrice)):'—';
  renderTrades();renderHistory();renderLogs();
}

ui.save.onclick=saveCredentials;ui.change.onclick=changeCredentials;ui.start.onclick=startBot;ui.stopBot.onclick=stopBot;
$('nav-dashboard').onclick=()=>showPage('dashboard');$('nav-trades').onclick=()=>showPage('trades');$('nav-history').onclick=()=>showPage('history');$('nav-logs').onclick=()=>showPage('logs');

const savedToken=cleanToken(localStorage.getItem('metaapi.token')),savedAccount=String(localStorage.getItem('metaapi.accountId')||'').trim();
if(savedToken&&savedAccount){ui.token.value=savedToken;ui.account.value=savedAccount;addLog('Saved credentials found — reconnecting');connectSdk().finally(()=>{ui.token.value='SAVED TOKEN';ui.token.disabled=true;});}
addLog('Pips-life engine loaded — 70-pip trailing SL');renderPageData();
