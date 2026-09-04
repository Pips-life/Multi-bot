import MetaApi, { SynchronizationListener } from 'metaapi.cloud-sdk';

const SYMBOL='XAUUSD';
const MAGIC=260903;
const TRAIL_PIPS=70;
const EXECUTION_VOLUME=0.01;
const XAUUSD_PIP_SIZE_FALLBACK=0.01;
const BIAS_LOOKBACK_CANDLES=5;
const DISPLACEMENT_ATR_MULTIPLIER=1.35;
const DISPLACEMENT_BODY_RATIO=0.60;
const MIN_BODY_PIPS=18;
const MAX_RETRACE_RATIO=0.65;
const REVERSAL_CONFIRM_RATIO=0.72;
const RESUME_CONFIRM_RATIO=0.10;
const MAX_CANDLES=80;

const $=id=>document.getElementById(id);
const ui={token:$('token'),account:$('account'),price:$('price'),balance:$('balance'),position:$('position'),stop:$('stop'),status:$('status'),save:$('save'),change:$('change'),start:$('start'),stopBot:$('stop')};
let api=null,account=null,connection=null,listener=null;
let trading=false,stopRequested=false,connecting=false,synchronized=false;
let lastMid=NaN,lastBid=NaN,lastAsk=NaN;
let currentPosition=null,currentStop=null;
let entryInFlight=false,stopActionInFlight=false,reconcileInFlight=false;
let directionBias='',marketPhase='WAITING';
let retracing=false,reversalCandidate=false;
let biasCandleTime=0,biasAnchor=NaN,biasExtreme=NaN;
let lastStatus='';
const eventLog=[],sessionHistory=[],candles=[];
let workingCandle=null;

function addLog(text){const now=new Date();eventLog.unshift({time:now,text:String(text)});if(eventLog.length>50)eventLog.pop();renderLogs();}
function setStatus(text){const value=String(text);if(value!==lastStatus){lastStatus=value;ui.status.textContent=value;addLog(value);}renderPageData();}
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

function candleRange(c){return Math.max(Number(c.high)-Number(c.low),brokerPipSize());}
function candleBody(c){return Math.abs(Number(c.close)-Number(c.open));}
function candleDirection(c){return c.close>c.open?'BUY':c.close<c.open?'SELL':'';}
function median(values){if(!values.length)return NaN;const a=[...values].sort((x,y)=>x-y);const m=Math.floor(a.length/2);return a.length%2?a[m]:(a[m-1]+a[m])/2;}
function averageRange(history){const ranges=history.map(c=>candleRange(c)).filter(Number.isFinite);return median(ranges.slice(-BIAS_LOOKBACK_CANDLES));}
function displacementScore(c,history){const pip=brokerPipSize(),body=candleBody(c)/pip,range=candleRange(c)/pip,bodyRatio=range>0?candleBody(c)/candleRange(c):0,base=averageRange(history);const basePips=Number.isFinite(base)?base/pip:0;return {bodyPips:body,rangePips:range,bodyRatio,rangeExpansion:basePips>0?range/basePips:0,displaced:body>=MIN_BODY_PIPS&&bodyRatio>=DISPLACEMENT_BODY_RATIO&&(basePips<=0||range>=basePips*DISPLACEMENT_ATR_MULTIPLIER)};}
function setBiasFromClosedCandle(c){
  const history=candles.slice(0,-1);const d=candleDirection(c);const score=displacementScore(c,history);
  if(!d||!score.displaced)return false;
  directionBias=d;biasCandleTime=c.time;biasAnchor=c.close;biasExtreme=d==='BUY'?c.high:c.low;retraceCandidate=false;reversalCandidate=false;retracing=false;
  marketPhase=`BIAS ${d} — DISPLACEMENT`;
  addLog(`DECISIVE BIAS ${d} from previous closed candle | body ${score.bodyPips.toFixed(1)}p | range ${score.rangePips.toFixed(1)}p | expansion ${score.rangeExpansion.toFixed(2)}x`);
  return true;
}
function recentStructureDirection(){
  if(candles.length<3)return '';
  const a=candles[candles.length-2],b=candles[candles.length-1];
  if(b.high>a.high&&b.low>=a.low)return 'BUY';
  if(b.low<a.low&&b.high<=a.high)return 'SELL';
  return '';
}
function updateBiasFromClosed(){
  if(candles.length<2)return;
  const previous=candles[candles.length-1];
  if(previous.time===biasCandleTime)return;
  if(setBiasFromClosedCandle(previous))return;
  if(!directionBias){
    const d=recentStructureDirection();
    if(d){directionBias=d;biasCandleTime=previous.time;biasAnchor=previous.close;biasExtreme=d==='BUY'?previous.high:previous.low;marketPhase=`BIAS ${d} — STRUCTURE`;addLog(`FAST BIAS ${d} from previous closed candle structure`);}
  }
}
function updateCandle(mid,time=Date.now()){
  const bucket=Math.floor(time/60000)*60000;
  if(!workingCandle||workingCandle.time!==bucket){
    if(workingCandle){candles.push({...workingCandle});if(candles.length>MAX_CANDLES)candles.shift();updateBiasFromClosed();}
    workingCandle={time:bucket,open:mid,high:mid,low:mid,close:mid};
  }else{workingCandle.high=Math.max(workingCandle.high,mid);workingCandle.low=Math.min(workingCandle.low,mid);workingCandle.close=mid;}
}
function updateMarketPhase(mid){
  if(!directionBias||!workingCandle){marketPhase='BUILDING BIAS';return;}
  const c=workingCandle,pip=brokerPipSize();
  const adverse=directionBias==='BUY'?biasAnchor-mid:mid-biasAnchor;
  const favorable=directionBias==='BUY'?mid-biasAnchor:biasAnchor-mid;
  const anchorMove=Math.max(favorable,0),adversePips=Math.max(adverse,0)/pip;
  const impulsePips=Math.max(Math.abs((biasExtreme-biasAnchor)/pip),MIN_BODY_PIPS);
  const retraceRatio=impulsePips>0?adversePips/impulsePips:0;
  if(directionBias==='BUY')biasExtreme=Math.max(biasExtreme,mid);else biasExtreme=Math.min(biasExtreme,mid);
  retracing=adversePips>=MIN_BODY_PIPS*0.35&&retraceRatio<REVERSAL_CONFIRM_RATIO;
  reversalCandidate=retraceRatio>=REVERSAL_CONFIRM_RATIO;
  const currentDir=candleDirection(c);
  if(reversalCandidate){
    const structure=directionBias==='BUY'?mid<Number(c.low):mid>Number(c.high);
    if(structure){directionBias=directionBias==='BUY'?'SELL':'BUY';biasAnchor=mid;biasExtreme=mid;reversalCandidate=false;retracing=false;marketPhase=`DIRECTION CHANGED → ${directionBias}`;addLog(`CONFIRMED DIRECTION CHANGE → ${directionBias}`);}
    else marketPhase=`DEEP RETRACEMENT — ${directionBias} BIAS`;
    return;
  }
  if(retracing){marketPhase=`RETRACE/PAUSE — HOLD ${directionBias} — EXECUTE ${directionBias}`;return;}
  if(currentDir&&currentDir===directionBias&&anchorMove/pip>=RESUME_CONFIRM_RATIO)marketPhase=`RESUMING ${directionBias}`;
  else marketPhase=`BIAS ${directionBias}`;
}
function updateBiasState(mid){updateCandle(mid);updateMarketPhase(mid);}
function entrySignal(mid){
  if(!directionBias||!Number.isFinite(lastMid)||reversalCandidate)return '';
  const c=workingCandle;if(!c)return '';
  const pip=brokerPipSize();
  const move=directionBias==='BUY'?mid-lastMid:lastMid-mid;
  const bodyFromOpen=directionBias==='BUY'?mid-c.open:c.open-mid;
  const resumed=move>0&&bodyFromOpen/pip>=RESUME_CONFIRM_RATIO;
  // A retracement is a pause in the existing bias, not a reason to stand aside.
  // Execute the established bias even while price is retracing; never trade the retracement direction.
  if(retracing)return directionBias;
  return resumed?directionBias:'';
}

class BotListener extends SynchronizationListener{
  onConnected(){setStatus('MetaApi connected — synchronizing…');}
  onDisconnected(){synchronized=false;setStatus('MetaApi disconnected — waiting to reconnect…');}
  onSynchronizationStarted(){synchronized=false;setStatus('Synchronizing MetaApi terminal…');}
  onSynchronizationFinished(){synchronized=true;setStatus('CONNECTED — XAUUSD live stream active');void reconcile();}
  onSymbolPricesUpdated(instanceIndex,prices){const p=Array.isArray(prices)?prices.find(x=>x?.symbol===SYMBOL):(prices?.symbol===SYMBOL?prices:null);if(!p)return;const bid=Number(p.bid),ask=Number(p.ask);if(!Number.isFinite(bid)||!Number.isFinite(ask))return;const mid=(bid+ask)/2;lastBid=bid;lastAsk=ask;ui.price.textContent=fmt(mid);const info=connection?.terminalState?.accountInformation;if(info?.balance!=null)ui.balance.textContent=fmt(Number(info.balance));updateBiasState(mid);renderPageData();if(!trading||stopRequested||!synchronized){lastMid=mid;return;}void onTick(mid,bid,ask);}
  onPositionUpdated(instanceIndex,position){if(position?.symbol===SYMBOL)void reconcile();}
  onPositionRemoved(){void reconcile();}
  onOrderUpdated(instanceIndex,order){if(order?.symbol===SYMBOL)void reconcile();}
  onOrderCompleted(instanceIndex,order){if(order?.symbol===SYMBOL)void reconcile();}
  onOrderFailed(instanceIndex,orderId,error){setStatus(`Order failed: ${error?.message||error}`);void reconcile();}
}

async function connectSdk(){if(connecting||connection)return;const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();if(!token||token==='SAVED TOKEN'){setStatus('MetaAPI token is missing');return;}if(!accountId){setStatus('MetaAPI account ID is missing');return;}if(!validAccountId(accountId)){setStatus('MetaAPI account ID format is invalid');return;}connecting=true;setStatus('Connecting directly to MetaApi…');try{const MetaApiClass=sdkConstructor();api=new MetaApiClass(token);account=await api.metatraderAccountApi.getAccount(accountId);if(!account?.id)throw new Error('MetaApi account not found');setStatus('MetaApi account found — checking deployment…');if(typeof account.waitConnected==='function')await account.waitConnected();connection=account.getStreamingConnection();listener=new BotListener();connection.addSynchronizationListener(listener);await connection.connect();await connection.waitSynchronized();synchronized=true;await connection.subscribeToMarketData(SYMBOL);void reconcile();setStatus('CONNECTED — XAUUSD live stream active');}catch(e){const msg=e?.message||String(e);try{if(connection)await connection.close();}catch(_){}try{if(api)await api.close();}catch(_){}connection=null;account=null;api=null;synchronized=false;setStatus(`MetaApi connection failed: ${msg}`);}finally{connecting=false;renderPageData();}}
async function reconcile(){if(reconcileInFlight||!connection?.terminalState)return;reconcileInFlight=true;try{const state=connection.terminalState;const positions=(state.positions||[]).filter(isOurs);const legacyStops=(state.orders||[]).filter(isOurs).filter(o=>String(o.type??'').toUpperCase().includes('STOP'));for(const o of legacyStops)void cancelOrder(idOf(o));currentPosition=positions[0]||null;const stopPrice=Number(currentPosition?.stopLoss??0);currentStop=currentPosition?{id:idOf(currentPosition),openPrice:stopPrice}:null;ui.position.textContent=currentPosition?sideOf(currentPosition):'—';ui.stop.textContent=stopPrice>0?fmt(stopPrice):'—';if(currentPosition&&!stopPrice&&!stopActionInFlight)void setInitialStop(currentPosition);renderPageData();}finally{reconcileInFlight=false;}}
function tradeOptions(comment){return{comment,magic:MAGIC};}
async function enter(side,spot){if(entryInFlight||currentPosition||!connection||!trading||stopRequested||!synchronized)return;if(directionBias!==side||reversalCandidate){setStatus(`ENTRY BLOCKED — ${marketPhase}`);return;}const volume=currentVolume(),pipSize=brokerPipSize(),initialStop=stopCandidate(side,Number(spot),pipSize);if(volume<=0){setStatus('Cannot size trade: invalid XAUUSD execution volume');return;}if(!Number.isFinite(initialStop)||initialStop<=0){setStatus('Cannot calculate 70-pip stop');return;}entryInFlight=true;try{const options=tradeOptions(`MB Bias ${side} — displacement direction — 70pip Trail`);if(stopRequested||!trading)return;if(side==='BUY')await connection.createMarketBuyOrder(SYMBOL,volume,initialStop,undefined,options);else await connection.createMarketSellOrder(SYMBOL,volume,initialStop,undefined,options);if(stopRequested||!trading){await reconcile();if(currentPosition)await closePositionSafe(currentPosition);return;}setStatus(`OPEN ${side} ${volume} — DISPLACEMENT BIAS — SL ${fmt(initialStop)}`);await waitForPosition(side,3000);await reconcile();}catch(e){if(!stopRequested)setStatus(`Entry failed: ${e?.message||e}`);}finally{entryInFlight=false;}}
async function waitForPosition(side,timeoutMs){const end=Date.now()+timeoutMs;while(Date.now()<end){await reconcile();if(currentPosition&&sideOf(currentPosition)===side)return currentPosition;await new Promise(r=>setTimeout(r,50));}return currentPosition;}
async function setInitialStop(position){if(!position||stopActionInFlight||!connection)return;const side=sideOf(position),spot=side==='BUY'?Number(lastBid):Number(lastAsk);if(!Number.isFinite(spot))return;const candidate=stopCandidate(side,spot,brokerPipSize());if(!Number.isFinite(candidate)||candidate<=0)return;stopActionInFlight=true;try{await connection.modifyPosition(idOf(position),candidate,undefined);currentStop={id:idOf(position),openPrice:candidate};ui.stop.textContent=fmt(candidate);}catch(e){if(!stopRequested)setStatus(`Initial SL failed: ${e?.message||e}`);}finally{stopActionInFlight=false;}}
async function trail(bid,ask){if(!currentPosition||stopActionInFlight||stopRequested)return;const side=sideOf(currentPosition),spot=side==='BUY'?bid:ask,candidate=stopCandidate(side,spot,brokerPipSize());const existing=Number(currentPosition.stopLoss??currentStop?.openPrice??0),improve=side==='BUY'?candidate>existing:candidate<existing;if((existing>0&&!improve)||!Number.isFinite(candidate)||candidate<=0)return;stopActionInFlight=true;try{await connection.modifyPosition(idOf(currentPosition),candidate,undefined);currentPosition.stopLoss=candidate;currentStop={id:idOf(position),openPrice:candidate};ui.stop.textContent=fmt(candidate);}catch(e){if(!stopRequested)setStatus(`SL trail failed: ${e?.message||e}`);}finally{stopActionInFlight=false;}}
async function onTick(mid,bid,ask){if(!trading||stopRequested||!synchronized)return;if(!currentPosition){const signal=entrySignal(mid);if(signal){setStatus(`EXECUTING ${signal} — ${marketPhase}`);await enter(signal,signal==='BUY'?ask:bid);}}else await trail(bid,ask);if(currentPosition)setStatus(`Running ${sideOf(currentPosition)} | ${marketPhase} | SL ${fmt(Number(currentPosition.stopLoss??0))}`);else if(directionBias)setStatus(`WAITING | ${marketPhase} | EXECUTION PENDING`);lastMid=mid;}
async function cancelOrder(id){if(id&&connection){try{await connection.cancelOrder(id);}catch(_){}}}
async function closePositionSafe(position){if(!position||!connection)return false;try{await connection.closePosition(idOf(position));return true;}catch(e){addLog(`Close position failed: ${e?.message||e}`);return false;}}
async function stopAllTrading(){stopRequested=true;trading=false;ui.stopBot.classList.add('active');ui.start.classList.remove('active');stopForegroundService();setStatus('STOPPING — closing all Pips-life positions and cancelling orders…');try{const positions=(connection?.terminalState?.positions||[]).filter(isOurs);const orders=(connection?.terminalState?.orders||[]).filter(isOurs);await Promise.all(orders.map(o=>cancelOrder(idOf(o))));await Promise.all(positions.map(p=>closePositionSafe(p)));await new Promise(r=>setTimeout(r,300));await reconcile();currentPosition=null;currentStop=null;ui.position.textContent='—';ui.stop.textContent='—';setStatus('BOT STOPPED — all Pips-life positions closed; new orders disabled');sessionHistory.unshift({time:Date.now(),text:'Bot stopped — positions closed and orders disabled'});}catch(e){setStatus(`BOT STOP ERROR — ${e?.message||e}`);}}
function startForegroundService(){try{if(window.AndroidBot?.startForegroundBot)window.AndroidBot.startForegroundBot();}catch(_){}}
function stopForegroundService(){try{if(window.AndroidBot?.stopForegroundBot)window.AndroidBot.stopForegroundBot();}catch(_) {}}
function saveCredentials(){const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();if(!token||token==='SAVED TOKEN'){setStatus('Enter a valid MetaAPI token');return;}if(!validAccountId(accountId)){setStatus('Enter a valid MetaAPI account ID');return;}localStorage.setItem('metaapi.token',token);localStorage.setItem('metaapi.accountId',accountId);ui.token.value='SAVED TOKEN';ui.token.disabled=true;addLog('Credentials saved locally');connectSdk();}
function changeCredentials(){stopAllTrading();localStorage.removeItem('metaapi.token');localStorage.removeItem('metaapi.accountId');try{connection?.close();api?.close();}catch(_){}connection=null;account=null;api=null;synchronized=false;ui.token.disabled=false;ui.token.value='';ui.account.value='';setStatus('Enter new MetaAPI credentials');}
function startBot(){stopRequested=false;if(!connection||!synchronized){setStatus('START BLOCKED — Connect MetaApi first');return;}trading=true;startForegroundService();ui.start.classList.add('active');ui.stopBot.classList.remove('active');setStatus(`BOT RUNNING — ${directionBias?`BIAS ${directionBias}`:'building direction bias'}`);addLog('BOT STARTED — bias decisions execute in established direction; retracement is not traded as reversal');}
function showPage(name){['dashboard','trades','history','logs'].forEach(p=>{const el=$(`page-${p}`);if(el)el.classList.toggle('active',p===name);const nav=$(`nav-${p}`);if(nav)nav.classList.toggle('active',p===name);});renderPageData();window.scrollTo({top:0,behavior:'smooth'});}
function renderTrades(){const el=$('tradesInfo');if(!el)return;if(!connection){el.innerHTML='<div class="empty">MetaApi is not connected.<br>Connect from Dashboard to view live trades.</div>';return;}const pos=currentPosition,stop=currentStop;el.innerHTML=`<div class="info-row"><span>Engine</span><b class="${trading?'green':''}">${trading?'RUNNING':'STOPPED'}</b></div><div class="info-row"><span>Connection</span><b>${synchronized?'CONNECTED':'SYNCING'}</b></div><div class="info-row"><span>Direction bias</span><b>${directionBias||'BUILDING'}</b></div><div class="info-row"><span>Market phase</span><b>${marketPhase}</b></div><div class="info-row"><span>Bias source</span><b>${biasCandleTime?new Date(biasCandleTime).toLocaleTimeString():'WAITING FOR CLOSED CANDLE'}</b></div><div class="info-row"><span>Symbol</span><b>${SYMBOL}</b></div><div class="info-row"><span>Position</span><b>${pos?sideOf(pos):'NONE'}</b></div><div class="info-row"><span>Volume</span><b>${pos?fmt(volumeOf(pos))+' LOT':'—'}</b></div><div class="info-row"><span>Entry</span><b>${pos?fmt(Number(pos.openPrice)):'—'}</b></div><div class="info-row"><span>Trailing SL</span><b class="red">${stop&&Number(stop.openPrice)>0?fmt(Number(stop.openPrice)):'—'}</b></div>`;}
function renderHistory(){const el=$('historyInfo');if(!el)return;if(!sessionHistory.length){el.innerHTML='<div class="empty">No completed bot events in this app session yet.</div>';return;}el.innerHTML=sessionHistory.slice(0,30).map(x=>`<div class="info-row"><span>${new Date(x.time).toLocaleTimeString()}</span><b>${x.text}</b></div>`).join('');}
function renderLogs(){const el=$('logsInfo');if(!el)return;el.innerHTML=eventLog.length?eventLog.map(x=>`<div class="log-row"><span class="log-time">${x.time.toLocaleTimeString()}</span>${String(x.text).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</div>`).join(''):'<div class="empty">No events yet.</div>';}
function renderPageData(){const p=currentPosition,s=currentStop;if($('sideBadge')){const side=sideOf(p);$('sideBadge').textContent=side||directionBias||'WAITING';$('sideBadge').classList.toggle('sell',side==='SELL');}if($('positionPrice'))$('positionPrice').textContent=p?fmt(Number(p.openPrice)):'—';if($('stopDetail'))$('stopDetail').textContent=s&&Number(s.openPrice)>0?fmt(Number(s.openPrice)):'—';renderTrades();renderHistory();renderLogs();}
ui.save.onclick=saveCredentials;ui.change.onclick=changeCredentials;ui.start.onclick=startBot;ui.stopBot.onclick=stopAllTrading;
$('nav-dashboard').onclick=()=>showPage('dashboard');$('nav-trades').onclick=()=>showPage('trades');$('nav-history').onclick=()=>showPage('history');$('nav-logs').onclick=()=>showPage('logs');
const savedToken=cleanToken(localStorage.getItem('metaapi.token')),savedAccount=String(localStorage.getItem('metaapi.accountId')||'').trim();if(savedToken&&savedAccount){ui.token.value=savedToken;ui.account.value=savedAccount;addLog('Saved credentials found — reconnecting');connectSdk().finally(()=>{ui.token.value='SAVED TOKEN';ui.token.disabled=true;});}
addLog('Pips-life engine loaded — previous-candle displacement bias + retracement/change detection + executable entries');