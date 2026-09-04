import MetaApi, { SynchronizationListener } from 'metaapi.cloud-sdk';

const SYMBOL='XAUUSD';
const MAGIC=260903;
const TRAIL_PIPS=70;
const EXECUTION_VOLUME=0.01;
const XAUUSD_PIP_SIZE_FALLBACK=0.01;
const CANDLE_TIMEFRAME='1m';
const CANDLE_BUFFER=36;
const MIN_VELOCITY_PIPS=0.20;
const ENTRY_COOLDOWN_MS=750;
const REVERSAL_CONFIRM=2;

const $=id=>document.getElementById(id);
const ui={token:$('token'),account:$('account'),price:$('price'),balance:$('balance'),position:$('position'),stop:$('stop'),status:$('status'),save:$('save'),change:$('change'),start:$('start'),stopBot:$('stop')};
let api=null,account=null,connection=null,listener=null;
let trading=false,stopRequested=false,connecting=false,synchronized=false;
let reconnectTimer=null,reconnectAttempt=0;
let lastMid=NaN,lastBid=NaN,lastAsk=NaN,lastEntryAt=0;
let currentPosition=null,currentStop=null;
let entryInFlight=false,stopActionInFlight=false,reconcileInFlight=false;
let lastDirection='',marketBias='',pullbackActive=false;
let candles=[];
const eventLog=[],sessionHistory=[];
let lastStatus='';

function addLog(text){const now=new Date();eventLog.unshift({time:now,text:String(text)});if(eventLog.length>60)eventLog.pop();renderLogs();}
function setStatus(text){const value=String(text);if(value!==lastStatus){lastStatus=value;ui.status.textContent=value;addLog(value);}else ui.status.textContent=value;renderPageData();}
function fmt(n){return Number.isFinite(n)?Number(n).toFixed(2):'—';}
function sideOf(x){const t=String(x?.type??'').toUpperCase();return t.includes('BUY')?'BUY':t.includes('SELL')?'SELL':'';}
function isOurs(x){return !!x&&x.symbol===SYMBOL&&(Number(x.magic)===MAGIC||String(x.clientId??'').startsWith('MB_'));}
function idOf(x){return String(x?.id??x?.positionId??x?.orderId??'');}
function volumeOf(x){return Number(x?.volume??0);}
function normalizeVolume(raw,spec){const min=Number(spec?.minVolume??0.01),max=Number(spec?.maxVolume??100),step=Number(spec?.volumeStep??0.01);let v=Math.max(min,Math.min(max,raw));if(step>0)v=Math.floor(v/step+1e-10)*step;return Number(Math.max(min,v).toFixed(6));}
function brokerPipSize(){const spec=connection?.terminalState?.specification(SYMBOL);const p=Number(spec?.pipSize??spec?.point??0);return p>0?p:XAUUSD_PIP_SIZE_FALLBACK;}
function brokerDigits(){const spec=connection?.terminalState?.specification(SYMBOL);const d=Number(spec?.digits??2);return Number.isFinite(d)?d:2;}
function normalizePrice(price){return Number(Number(price).toFixed(brokerDigits()));}
function currentVolume(){return normalizeVolume(EXECUTION_VOLUME,connection?.terminalState?.specification(SYMBOL)||{minVolume:.01,maxVolume:100,volumeStep:.01});}
function stopCandidate(side,spot,pipSize){return normalizePrice(side==='BUY'?spot-TRAIL_PIPS*pipSize:spot+TRAIL_PIPS*pipSize);}
function cleanToken(value){return String(value??'').trim().replace(/^Bearer\s+/i,'');}
function validAccountId(value){return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);}
function sdkConstructor(){const Ctor=MetaApi?.default??MetaApi;if(typeof Ctor!=='function')throw new Error('MetaApi browser SDK constructor is unavailable');return Ctor;}
function credentialToken(){return cleanToken(ui.token.value)==='SAVED TOKEN'?cleanToken(localStorage.getItem('metaapi.token')):cleanToken(ui.token.value);}
function credentialAccount(){return String(ui.account.value||localStorage.getItem('metaapi.accountId')||'').trim();}
function persistCredentials(token,accountId){localStorage.setItem('metaapi.token',token);localStorage.setItem('metaapi.accountId',accountId);try{window.AndroidBot?.saveCredentials?.(accountId,token);}catch(e){addLog(`Secure credential store unavailable: ${e?.message||e}`);}}
function clearPersistedCredentials(){localStorage.removeItem('metaapi.token');localStorage.removeItem('metaapi.accountId');try{window.AndroidBot?.clearCredentials?.();}catch(_) {}}

function candleTime(c){const t=c?.time instanceof Date?c.time:new Date(c?.time);return t.getTime();}
function normalizeCandles(list){return (Array.isArray(list)?list:[]).filter(c=>Number.isFinite(Number(c?.open))&&Number.isFinite(Number(c?.high))&&Number.isFinite(Number(c?.low))&&Number.isFinite(Number(c?.close))&&Number.isFinite(candleTime(c))).sort((a,b)=>candleTime(a)-candleTime(b)).slice(-CANDLE_BUFFER);}
function closedCandles(){if(candles.length<3)return candles.slice();return candles.slice(0,-1);}
function updateBias(){
  const cs=closedCandles();if(cs.length<6)return marketBias;
  const recent=cs.slice(-12),closes=recent.map(c=>Number(c.close));
  const fast=closes.slice(-5).reduce((a,b)=>a+b,0)/Math.min(5,closes.length),slow=closes.reduce((a,b)=>a+b,0)/closes.length;
  const last=recent[recent.length-1],prev=recent[recent.length-2];
  const bullishStructure=last.close>prev.close&&last.high>=prev.high&&last.low>=prev.low;
  const bearishStructure=last.close<prev.close&&last.low<=prev.low&&last.high<=prev.high;
  const bullScore=(fast>slow?1:0)+(last.close>recent[0].close?1:0)+(bullishStructure?1:0);
  const bearScore=(fast<slow?1:0)+(last.close<recent[0].close?1:0)+(bearishStructure?1:0);
  const old=marketBias;
  if(bullScore>=2&&bullScore>bearScore)marketBias='BUY';
  else if(bearScore>=2&&bearScore>bullScore)marketBias='SELL';
  if(old&&marketBias!==old)addLog(`BIAS CHANGED ${old} → ${marketBias}`);
  return marketBias;
}
function structureLevels(){const cs=closedCandles().slice(-8);if(!cs.length)return {low:NaN,high:NaN};return {low:Math.min(...cs.map(c=>Number(c.low))),high:Math.max(...cs.map(c=>Number(c.high)))};}
function reversalConfirmed(side,price){
  const cs=closedCandles();if(cs.length<REVERSAL_CONFIRM)return false;
  const last=cs[cs.length-1],prev=cs[cs.length-2],levels=structureLevels();
  if(side==='BUY'){const bearishCandles=Number(last.close)<Number(last.open)&&Number(prev.close)<Number(prev.open);return price<levels.low||(bearishCandles&&Number(last.close)<Number(prev.low));}
  const bullishCandles=Number(last.close)>Number(last.open)&&Number(prev.close)>Number(prev.open);return price>levels.high||(bullishCandles&&Number(last.close)>Number(prev.high));
}
function directionalVelocity(side,mid){if(!Number.isFinite(lastMid)||!Number.isFinite(mid))return false;const delta=(mid-lastMid)/brokerPipSize();return side==='BUY'?delta>=MIN_VELOCITY_PIPS:delta<=-MIN_VELOCITY_PIPS;}
function evaluateMarket(mid){
  updateBias();
  if(!marketBias)return {action:'WAIT',reason:'building candle bias'};
  if(reversalConfirmed(marketBias,mid)){const old=marketBias;marketBias=old==='BUY'?'SELL':'BUY';pullbackActive=false;addLog(`DIRECTION CHANGE CONFIRMED — ${old} → ${marketBias}`);return {action:'BIAS_CHANGED',reason:'market structure broken'};}
  const against=marketBias==='BUY'?mid<lastMid:mid>lastMid;
  if(against){pullbackActive=true;return {action:'PULLBACK',reason:`${marketBias} bias retained`};}
  if(pullbackActive&&directionalVelocity(marketBias,mid)){pullbackActive=false;return {action:'ENTRY',side:marketBias,reason:'pullback resumed with velocity'};}
  if(!pullbackActive&&directionalVelocity(marketBias,mid))return {action:'ENTRY',side:marketBias,reason:'bias-aligned velocity'};
  return {action:'WAIT',reason:`${marketBias} bias`};
}

class BotListener extends SynchronizationListener{
  async onConnected(){reconnectAttempt=0;setStatus('MetaApi connected — synchronizing…');}
  async onDisconnected(){synchronized=false;setStatus('MetaApi disconnected — reconnecting automatically…');scheduleReconnect();}
  async onSynchronizationStarted(){synchronized=false;setStatus('Synchronizing MetaApi terminal…');}
  async onSynchronizationFinished(){synchronized=true;reconnectAttempt=0;clearTimeout(reconnectTimer);reconnectTimer=null;setStatus(`CONNECTED — ${SYMBOL} live stream active — bias ${marketBias||'CALCULATING'}`);void reconcile();}
  async onSymbolPricesUpdated(instanceIndex,prices){
    const p=Array.isArray(prices)?prices.find(x=>x?.symbol===SYMBOL):(prices?.symbol===SYMBOL?prices:null);if(!p)return;
    const bid=Number(p.bid),ask=Number(p.ask);if(!Number.isFinite(bid)||!Number.isFinite(ask))return;
    const mid=(bid+ask)/2;lastBid=bid;lastAsk=ask;ui.price.textContent=fmt(mid);
    const info=connection?.terminalState?.accountInformation;if(info?.balance!=null)ui.balance.textContent=fmt(Number(info.balance));
    if(!trading||stopRequested||!synchronized){lastMid=mid;renderPageData();return;}
    await onTick(mid,bid,ask);
  }
  async onCandlesUpdated(instanceIndex,updates){const incoming=Array.isArray(updates)?updates.filter(x=>x?.symbol===SYMBOL):[];if(incoming.length){candles=normalizeCandles([...candles,...incoming]);const old=marketBias;updateBias();if(old!==marketBias&&old)addLog(`CANDLE BIAS ${old} → ${marketBias}`);renderPageData();}}
  async onPositionUpdated(instanceIndex,position){if(position?.symbol===SYMBOL)void reconcile();}
  async onPositionRemoved(instanceIndex,positionId){void reconcile();}
  async onOrderUpdated(instanceIndex,order){if(order?.symbol===SYMBOL)void reconcile();}
  async onOrderCompleted(instanceIndex,order){if(order?.symbol===SYMBOL)void reconcile();}
  async onOrderFailed(instanceIndex,orderId,error){setStatus(`Order failed: ${error?.message||error}`);void reconcile();}
}

async function loadCandleContext(){try{if(typeof account?.getHistoricalCandles==='function'){const hist=await account.getHistoricalCandles(SYMBOL,CANDLE_TIMEFRAME);if(Array.isArray(hist)&&hist.length)candles=normalizeCandles(hist);}}catch(e){addLog(`Historical candle context unavailable — live candle stream will build bias: ${e?.message||e}`);}updateBias();}

async function connectSdk(force=false){
  if(connecting)return;
  const token=credentialToken(),accountId=credentialAccount();
  if(!token||token==='SAVED TOKEN'){setStatus('MetaAPI token is missing');return;}
  if(!accountId){setStatus('MetaAPI account ID is missing');return;}
  if(!validAccountId(accountId)){setStatus('MetaAPI account ID format is invalid');return;}
  if(connection&&!force)return;
  connecting=true;setStatus(force?'Reconnecting MetaApi…':'Connecting directly to MetaApi…');
  try{
    if(force&&connection){try{connection.removeSynchronizationListener?.(listener);}catch(_){}try{await connection.close();}catch(_){}connection=null;}
    const MetaApiClass=sdkConstructor();api=new MetaApiClass(token);
    account=await api.metatraderAccountApi.getAccount(accountId);if(!account?.id)throw new Error('MetaApi account not found');
    if(account.state!=='DEPLOYED'){setStatus('Deploying MetaApi account…');await account.deploy();}
    if(typeof account.waitConnected==='function')await account.waitConnected();
    await loadCandleContext();
    connection=account.getStreamingConnection();listener=new BotListener();connection.addSynchronizationListener(listener);
    await connection.connect();await connection.waitSynchronized();synchronized=true;
    await connection.subscribeToMarketData(SYMBOL,[{type:'quotes',intervalInMilliseconds:1000},{type:'candles',timeframe:CANDLE_TIMEFRAME,intervalInMilliseconds:1000},{type:'ticks'}]);
    void reconcile();setStatus(`CONNECTED — ${SYMBOL} live tick/candle stream active — bias ${marketBias||'CALCULATING'}`);
  }catch(e){const msg=e?.message||String(e);try{await connection?.close();}catch(_){}try{await api?.close();}catch(_){}connection=null;account=null;api=null;synchronized=false;setStatus(`MetaApi connection failed: ${msg}`);scheduleReconnect();}
  finally{connecting=false;renderPageData();}
}
function scheduleReconnect(){
  if(stopRequested)return;
  const token=credentialToken(),accountId=credentialAccount();if(!token||!accountId)return;
  clearTimeout(reconnectTimer);const delay=Math.min(30000,1000*Math.pow(2,reconnectAttempt++));reconnectTimer=setTimeout(()=>void connectSdk(true),delay);addLog(`Reconnect scheduled in ${Math.round(delay/1000)}s`);
}

async function reconcile(){
  if(reconcileInFlight||!connection?.terminalState)return;
  reconcileInFlight=true;
  try{
    const state=connection.terminalState,positions=(state.positions||[]).filter(isOurs),staleStops=(state.orders||[]).filter(isOurs).filter(o=>String(o.type??'').toUpperCase().includes('STOP'));
    for(const o of staleStops)void cancelOrder(idOf(o));
    currentPosition=positions[0]||null;const stopPrice=Number(currentPosition?.stopLoss??0);currentStop=currentPosition?{id:idOf(currentPosition),openPrice:stopPrice}:null;
    ui.position.textContent=currentPosition?sideOf(currentPosition):'—';ui.stop.textContent=stopPrice>0?fmt(stopPrice):'—';
    if(currentPosition&&sideOf(currentPosition)&&!stopPrice&&!stopActionInFlight)void setInitialStop(currentPosition);renderPageData();
  }finally{reconcileInFlight=false;}
}
function tradeOptions(side){return{comment:side==='BUY'?'MB_BUY':'MB_SELL',clientId:`MB_${side[0]}_${Date.now().toString(36)}`,magic:MAGIC};}

async function enter(side,spot){
  if(entryInFlight||currentPosition||!connection||!trading||stopRequested||!synchronized)return;
  if(Date.now()-lastEntryAt<ENTRY_COOLDOWN_MS)return;
  const volume=currentVolume();if(volume<=0){setStatus('ENTRY BLOCKED — invalid XAUUSD execution volume');return;}
  if(!Number.isFinite(Number(spot))||Number(spot)<=0){setStatus('ENTRY BLOCKED — invalid live XAUUSD price');return;}
  entryInFlight=true;
  try{
    const options=tradeOptions(side);if(stopRequested||!trading)return;
    if(side==='BUY')await connection.createMarketBuyOrder(SYMBOL,volume,undefined,undefined,options);else await connection.createMarketSellOrder(SYMBOL,volume,undefined,undefined,options);
    lastEntryAt=Date.now();if(stopRequested||!trading){await reconcile();if(currentPosition)await closePositionSafe(currentPosition);return;}
    lastDirection=side;setStatus(`OPEN ${side} ${volume} — PULLBACK/BIAS EXECUTION — applying 70-pip SL`);
    const position=await waitForPosition(side,3000);await reconcile();if(position&&trading&&!stopRequested)await setInitialStop(position);
  }catch(e){if(!stopRequested)setStatus(`Entry failed: ${e?.message||e}`);}finally{entryInFlight=false;}
}
async function waitForPosition(side,timeoutMs){const end=Date.now()+timeoutMs;while(Date.now()<end){await reconcile();if(currentPosition&&sideOf(currentPosition)===side)return currentPosition;await new Promise(r=>setTimeout(r,50));}return currentPosition;}
async function setInitialStop(position){
  if(!position||stopActionInFlight||!connection)return;
  const side=sideOf(position),spot=side==='BUY'?Number(lastBid):Number(lastAsk);if(!Number.isFinite(spot))return;
  const candidate=stopCandidate(side,spot,brokerPipSize());if(!Number.isFinite(candidate)||candidate<=0)return;
  stopActionInFlight=true;
  try{await connection.modifyPosition(idOf(position),candidate,undefined);currentStop={id:idOf(position),openPrice:candidate};ui.stop.textContent=fmt(candidate);}catch(e){if(!stopRequested)setStatus(`Initial SL failed: ${e?.message||e}`);}finally{stopActionInFlight=false;}
}
async function trail(bid,ask){
  if(!currentPosition||stopActionInFlight||stopRequested||!connection)return;
  const side=sideOf(currentPosition),spot=side==='BUY'?bid:ask,candidate=stopCandidate(side,spot,brokerPipSize()),existing=Number(currentPosition.stopLoss??currentStop?.openPrice??0),improve=side==='BUY'?candidate>existing:candidate<existing;
  if(!Number.isFinite(candidate)||candidate<=0||(existing>0&&!improve))return;
  stopActionInFlight=true;try{await connection.modifyPosition(idOf(currentPosition),candidate,undefined);currentPosition.stopLoss=candidate;currentStop={id:idOf(currentPosition),openPrice:candidate};ui.stop.textContent=fmt(candidate);}catch(e){if(!stopRequested)setStatus(`SL trail failed: ${e?.message||e}`);}finally{stopActionInFlight=false;}
}
async function onTick(mid,bid,ask){
  if(!trading||stopRequested||!synchronized)return;
  const previous=lastMid;lastMid=mid;if(currentPosition){await trail(bid,ask);return;}
  if(!Number.isFinite(previous)||mid===previous)return;
  const decision=evaluateMarket(mid);
  if(decision.action==='PULLBACK'){lastDirection=marketBias;setStatus(`PULLBACK — ${marketBias} bias retained — waiting for resumption`);return;}
  if(decision.action==='BIAS_CHANGED'){lastDirection=marketBias;setStatus(`BIAS CHANGED — now ${marketBias} — watching for aligned velocity`);return;}
  if(decision.action==='ENTRY'){lastDirection=decision.side;setStatus(`VELOCITY ${decision.side} — ${decision.reason} — executing immediately`);await enter(decision.side,decision.side==='BUY'?ask:bid);}
}
async function cancelOrder(id){if(id&&connection){try{await connection.cancelOrder(id);}catch(_) {}}}
async function closePositionSafe(position){if(!position||!connection)return false;try{await connection.closePosition(idOf(position));return true;}catch(e){addLog(`Close position failed: ${e?.message||e}`);return false;}}
async function stopAllTrading(){
  stopRequested=true;trading=false;clearTimeout(reconnectTimer);reconnectTimer=null;ui.stopBot.classList.add('active');ui.start.classList.remove('active');stopForegroundService();setStatus('STOPPING — closing all Pips-life positions and cancelling orders…');
  try{const positions=(connection?.terminalState?.positions||[]).filter(isOurs),orders=(connection?.terminalState?.orders||[]).filter(isOurs);await Promise.all(orders.map(o=>cancelOrder(idOf(o))));await Promise.all(positions.map(p=>closePositionSafe(p)));await new Promise(r=>setTimeout(r,300));await reconcile();currentPosition=null;currentStop=null;ui.position.textContent='—';ui.stop.textContent='—';setStatus('BOT STOPPED — all Pips-life positions closed; new orders disabled');sessionHistory.unshift({time:Date.now(),text:'Bot stopped — positions closed and orders disabled'});}catch(e){setStatus(`BOT STOP ERROR — ${e?.message||e}`);}
}
function startForegroundService(){try{if(window.AndroidBot?.startForegroundBot)window.AndroidBot.startForegroundBot();}catch(_) {}}
function stopForegroundService(){try{if(window.AndroidBot?.stopForegroundBot)window.AndroidBot.stopForegroundBot();}catch(_) {}}
function saveCredentials(){const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();if(!token||token==='SAVED TOKEN'){setStatus('Enter a valid MetaAPI token');return;}if(!validAccountId(accountId)){setStatus('Enter a valid MetaAPI account ID');return;}persistCredentials(token,accountId);ui.token.value='SAVED TOKEN';ui.token.disabled=true;addLog('Credentials saved locally — encrypted Android store + WebView fallback');void connectSdk();}
function changeCredentials(){void stopAllTrading();clearPersistedCredentials();try{connection?.close();api?.close();}catch(_){}connection=null;account=null;api=null;synchronized=false;ui.token.disabled=false;ui.token.value='';ui.account.value='';setStatus('Enter new MetaAPI credentials');}
function startBot(){stopRequested=false;if(!connection||!synchronized){setStatus('START BLOCKED — Connect MetaApi first');return;}trading=true;startForegroundService();ui.start.classList.add('active');ui.stopBot.classList.remove('active');setStatus(`BOT RUNNING — CANDLE BIAS + PULLBACK DETECTION — 70 PIP TRAIL`);addLog(`BOT STARTED — current bias ${marketBias||'CALCULATING'}; pullbacks are traded in bias direction; structure breaks reverse bias`);}
function showPage(name){['dashboard','trades','history','logs'].forEach(p=>{const el=$(`page-${p}`);if(el)el.classList.toggle('active',p===name);const nav=$(`nav-${p}`);if(nav)nav.classList.toggle('active',p===name);});renderPageData();window.scrollTo({top:0,behavior:'smooth'});}
function renderTrades(){const el=$('tradesInfo');if(!el)return;if(!connection){el.innerHTML='<div class="empty">MetaApi is not connected.<br>Connect from Dashboard to view live trades.</div>';return;}const pos=currentPosition,stop=currentStop;el.innerHTML=`<div class="info-row"><span>Engine</span><b class="${trading?'green':''}">${trading?'RUNNING':'STOPPED'}</b></div><div class="info-row"><span>Connection</span><b>${synchronized?'CONNECTED':'RECONNECTING'}</b></div><div class="info-row"><span>Bias</span><b>${marketBias||'CALCULATING'}</b></div><div class="info-row"><span>State</span><b>${pullbackActive?'PULLBACK — WAITING RESUMPTION':'DIRECTIONAL'}</b></div><div class="info-row"><span>Entry mode</span><b>BIAS + PULLBACK VELOCITY</b></div><div class="info-row"><span>Last direction</span><b>${lastDirection||'WAITING'}</b></div><div class="info-row"><span>Symbol</span><b>${SYMBOL}</b></div><div class="info-row"><span>Position</span><b>${pos?sideOf(pos):'NONE'}</b></div><div class="info-row"><span>Volume</span><b>${pos?fmt(volumeOf(pos))+' LOT':'—'}</b></div><div class="info-row"><span>Entry</span><b>${pos?fmt(Number(pos.openPrice)):'—'}</b></div><div class="info-row"><span>Trailing SL</span><b class="red">${stop&&Number(stop.openPrice)>0?fmt(Number(stop.openPrice)):'—'}</b></div><div class="info-row"><span>Trail distance</span><b>70 PIPS</b></div>`;}
function renderHistory(){const el=$('historyInfo');if(!el)return;if(!sessionHistory.length){el.innerHTML='<div class="empty">No completed bot events in this app session yet.</div>';return;}el.innerHTML=sessionHistory.slice(0,30).map(x=>`<div class="info-row"><span>${new Date(x.time).toLocaleTimeString()}</span><b>${x.text}</b></div>`).join('');}
function renderLogs(){const el=$('logsInfo');if(!el)return;el.innerHTML=eventLog.length?eventLog.map(x=>`<div class="log-row"><span class="log-time">${x.time.toLocaleTimeString()}</span>${String(x.text).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</div>`).join(''):'<div class="empty">No events yet.</div>';}
function renderPageData(){const p=currentPosition,s=currentStop;if($('sideBadge')){const side=sideOf(p);$('sideBadge').textContent=side||lastDirection||'WAITING';$('sideBadge').classList.toggle('sell',side==='SELL');}if($('positionPrice'))$('positionPrice').textContent=p?fmt(Number(p.openPrice)):'—';if($('stopDetail'))$('stopDetail').textContent=s&&Number(s.openPrice)>0?fmt(Number(s.openPrice)):'—';renderTrades();renderHistory();renderLogs();}

ui.save.onclick=saveCredentials;ui.change.onclick=changeCredentials;ui.start.onclick=startBot;ui.stopBot.onclick=stopAllTrading;
$('nav-dashboard').onclick=()=>showPage('dashboard');$('nav-trades').onclick=()=>showPage('trades');$('nav-history').onclick=()=>showPage('history');$('nav-logs').onclick=()=>showPage('logs');
const androidToken=(()=>{try{return cleanToken(window.AndroidBot?.getSavedToken?.()||'');}catch(_){return '';}})();
const androidAccount=(()=>{try{return String(window.AndroidBot?.getSavedAccountId?.()||'').trim();}catch(_){return '';}})();
const savedToken=androidToken||cleanToken(localStorage.getItem('metaapi.token'));const savedAccount=androidAccount||String(localStorage.getItem('metaapi.accountId')||'').trim();
if(savedToken&&savedAccount){localStorage.setItem('metaapi.token',savedToken);localStorage.setItem('metaapi.accountId',savedAccount);ui.token.value='SAVED TOKEN';ui.token.disabled=true;ui.account.value=savedAccount;addLog('Saved credentials found — reconnecting automatically');void connectSdk();}
addLog('Pips-life engine loaded — candle bias + pullback/reversal detection + 70-pip favorable-only trailing');
