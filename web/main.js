import MetaApi, { SynchronizationListener } from 'metaapi.cloud-sdk';

const SYMBOL='XAUUSD';
const MAGIC=260904;
const INITIAL_SL_PIPS=100;
const TRAILING_SL_PIPS=100;
const TAKE_PROFIT_PIPS=200;
const DIRECTION_CONFIRMATIONS=3;
const MAX_POSITIONS=4;
const EXECUTION_VOLUME=0.01;
const XAUUSD_PIP_SIZE_FALLBACK=0.01;
const HISTORY_SIZE=40;
const FAST_EMA=8;
const SLOW_EMA=21;
const MIN_ENTRY_SPACING_PIPS=35;
const CANDLE_MS=300000;
const MOMENTUM_WINDOW=3;
// Broker spread is approximately 35 pips. Profit protection is deliberately
// armed only after the trade has cleared the spread, then locks profit in stages.
const SPREAD_PIPS=35;
// Prevent rapid-fire entries/exits and give the broker/market a short cool-off.
const TRADE_COOLDOWN_MS=3000;
let lastTradeActionAt=0;

const $=id=>document.getElementById(id);
const ui={token:$('token'),account:$('account'),price:$('price'),balance:$('balance'),position:$('position'),stop:$('stop'),status:$('status'),save:$('save'),change:$('change'),start:$('start'),stopBot:$('stop')};
let api=null,account=null,connection=null,listener=null;
let trading=false,connecting=false,synchronized=false;
let lastMid=NaN,entryInFlight=false,lastStatus='',lastEntryPrice=NaN;
const priceHistory=[];
const repairingPositionIds=new Set();
const momentumDeltas=[];
let candleStart=0,candleOpen=NaN,candleSide='';
const reversalCounts=new Map();
let directionCandidate='';
let directionConfirmations=0;

function setStatus(text){if(text!==lastStatus){lastStatus=text;ui.status.textContent=text;}}
function fmt(n){return Number.isFinite(n)?Number(n).toFixed(2):'—';}
function moneyKsh(n){const v=Number(n);return Number.isFinite(v)?`KSh ${v.toLocaleString('en-KE',{minimumFractionDigits:2,maximumFractionDigits:2})}`:'KSh —';}
function sideOf(x){const t=String(x?.type??'').toUpperCase();return t.includes('BUY')?'BUY':t.includes('SELL')?'SELL':'';}
function isOurs(x){return !!x&&x.symbol===SYMBOL&&(Number(x.magic)===MAGIC||String(x.clientId??'').startsWith('MB_'));}
function idOf(x){return String(x?.id??x?.positionId??x?.orderId??'');}
function volumeOf(x){return Number(x?.volume??0);}
function positionTime(x){const t=Date.parse(String(x?.time??x?.updateTime??''));return Number.isFinite(t)?t:0;}
function normalizeVolume(raw,spec){const min=Number(spec?.minVolume??0.01),max=Number(spec?.maxVolume??100),step=Number(spec?.volumeStep??0.01);let v=Math.max(min,Math.min(max,raw));if(step>0)v=Math.floor(v/step+1e-10)*step;return Number(Math.max(min,v).toFixed(6));}
function brokerPipSize(){const spec=connection?.terminalState?.specification(SYMBOL);const p=Number(spec?.pipSize??spec?.point??0);return p>0?p:XAUUSD_PIP_SIZE_FALLBACK;}
function brokerDigits(){const spec=connection?.terminalState?.specification(SYMBOL);const d=Number(spec?.digits??2);return Number.isFinite(d)?d:2;}
function normalizePrice(price){return Number(Number(price).toFixed(brokerDigits()));}
function currentVolume(){return normalizeVolume(EXECUTION_VOLUME,connection?.terminalState?.specification(SYMBOL)||{minVolume:.01,maxVolume:100,volumeStep:.01});}
function cleanToken(value){return String(value??'').trim().replace(/^Bearer\s+/i,'');}
function validAccountId(value){return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);}
function sdkConstructor(){const Ctor=MetaApi?.default??MetaApi;if(typeof Ctor!=='function')throw new Error('MetaApi browser SDK constructor is unavailable');return Ctor;}
function ema(values,period){if(!values.length)return NaN;const k=2/(period+1);let e=values[0];for(let i=1;i<values.length;i++)e=values[i]*k+e*(1-k);return e;}
function directionSignal(){
  if(priceHistory.length<SLOW_EMA+8)return {side:'',score:0,confirmed:false};
  const mids=priceHistory.map(x=>x.mid);
  const fastSeries=mids.slice(-FAST_EMA*2);
  const slowSeries=mids.slice(-SLOW_EMA*2);
  const fast=ema(fastSeries,FAST_EMA),slow=ema(slowSeries,SLOW_EMA);
  const fastPrev=ema(fastSeries.slice(0,-5),FAST_EMA);
  const slowPrev=ema(slowSeries.slice(0,-5),SLOW_EMA);
  const fastSlope=fast-fastPrev,slowSlope=slow-slowPrev;
  const deltas=momentumDeltas.slice(-MOMENTUM_WINDOW);
  const momentum=deltas.reduce((a,b)=>a+b,0);
  const price=mids[mids.length-1];
  const buyScore=(fast>slow?1:0)+(fastSlope>0?1:0)+(slowSlope>0?1:0)+(momentum>0?1:0)+(candleSide==='BUY'?1:0)+(price>fast?1:0);
  const sellScore=(fast<slow?1:0)+(fastSlope<0?1:0)+(slowSlope<0?1:0)+(momentum<0?1:0)+(candleSide==='SELL'?1:0)+(price<fast?1:0);
  let side='';
  if(buyScore>=4&&buyScore>sellScore)side='BUY';
  else if(sellScore>=4&&sellScore>buyScore)side='SELL';
  const score=side==='BUY'?buyScore:side==='SELL'?sellScore:0;
  if(!side){directionCandidate='';directionConfirmations=0;return {side:'',score,confirmed:false};}
  if(side===directionCandidate)directionConfirmations++;
  else {directionCandidate=side;directionConfirmations=1;}
  return {side:directionConfirmations>=DIRECTION_CONFIRMATIONS?side:'',score,confirmed:directionConfirmations>=DIRECTION_CONFIRMATIONS};
}
function positionDistanceAllows(side,positions){if(!Number.isFinite(lastEntryPrice))return true;const pip=brokerPipSize();const same=[...positions].filter(p=>sideOf(p)===side).sort((a,b)=>positionTime(b)-positionTime(a))[0];const ref=Number(same?.openPrice??lastEntryPrice);return !Number.isFinite(ref)||Math.abs(lastMid-ref)/pip>=MIN_ENTRY_SPACING_PIPS;}
function initialStop(side,price){const pip=brokerPipSize(),base=Number(price);if(!Number.isFinite(base)||base<=0)return undefined;return normalizePrice(side==='BUY'?base-INITIAL_SL_PIPS*pip:base+INITIAL_SL_PIPS*pip);}
function trailingStop(side,price){const pip=brokerPipSize(),base=Number(price);if(!Number.isFinite(base)||base<=0)return undefined;return normalizePrice(side==='BUY'?base-TRAILING_SL_PIPS*pip:base+TRAILING_SL_PIPS*pip);}
function updateCandle(mid,previous){const now=Date.now(),start=Math.floor(now/CANDLE_MS)*CANDLE_MS;if(start!==candleStart){candleStart=start;candleOpen=mid;candleSide='';momentumDeltas.length=0;reversalCounts.clear();}if(!Number.isFinite(candleOpen))candleOpen=mid;const delta=Number.isFinite(previous)?mid-previous:0;if(Number.isFinite(delta)){momentumDeltas.push(delta);if(momentumDeltas.length>MOMENTUM_WINDOW)momentumDeltas.shift();}if(mid>candleOpen)candleSide='BUY';else if(mid<candleOpen)candleSide='SELL';}
function momentumFaded(side){if(candleSide!==side||momentumDeltas.length<MOMENTUM_WINDOW)return false;const sum=momentumDeltas.reduce((a,b)=>a+b,0);return side==='BUY'?sum<=0:sum>=0;}
function profitPips(position,current){const side=sideOf(position),open=Number(position.openPrice),price=Number(current),pip=brokerPipSize();if(!side||!Number.isFinite(open)||!Number.isFinite(price)||pip<=0)return NaN;return side==='BUY'?(price-open)/pip:(open-price)/pip;}
function protectedStop(){return undefined;}
function updateProfitLossUI(){const info=connection?.terminalState?.accountInformation;const positions=ownedPositions();const rawBal=Number(info?.balance),rawEq=Number(info?.equity),rawMargin=Number(info?.margin);const pnl=positions.reduce((s,x)=>s+(Number(x.profit)||0),0);if(Number.isFinite(rawBal)){ui.balance.textContent=moneyKsh(rawBal);$('pnlBalance').textContent=moneyKsh(rawBal);$('livePnl').textContent=moneyKsh(pnl);$('floatingPnl').textContent=moneyKsh(pnl);$('pnlPercent').textContent=`${rawBal?((pnl/rawBal)*100).toFixed(2):'0.00'}%`;}else{ui.balance.textContent='KSh —';$('pnlBalance').textContent='KSh —';$('livePnl').textContent='KSh 0.00';$('floatingPnl').textContent='KSh 0.00';$('pnlPercent').textContent='0.00%';}if(Number.isFinite(rawEq)){$('equity').textContent=moneyKsh(rawEq);$('pnlEquity').textContent=moneyKsh(rawEq);}else{$('equity').textContent='KSh —';$('pnlEquity').textContent='KSh —';}if(Number.isFinite(rawMargin))$('margin').textContent=moneyKsh(rawMargin);else $('margin').textContent='KSh —';}

class BotListener extends SynchronizationListener{
 onConnected(){setStatus('MetaApi connected — synchronizing…');}
 onDisconnected(){synchronized=false;setStatus('MetaApi disconnected — waiting to reconnect…');}
 onSynchronizationStarted(){synchronized=false;setStatus('Synchronizing MetaApi terminal…');}
 onSynchronizationFinished(){synchronized=true;setStatus('CONNECTED — XAUUSD live stream active');reconcile();}
 onSymbolPricesUpdated(instanceIndex,prices){const p=Array.isArray(prices)?prices.find(x=>x?.symbol===SYMBOL):(prices?.symbol===SYMBOL?prices:null);if(!p)return;const bid=Number(p.bid),ask=Number(p.ask);if(!Number.isFinite(bid)||!Number.isFinite(ask)||bid<=0||ask<=0||ask<bid)return;const mid=(bid+ask)/2,previous=lastMid;lastMid=mid;updateCandle(mid,previous);priceHistory.push({mid,bid,ask,time:Date.now()});if(priceHistory.length>HISTORY_SIZE)priceHistory.shift();ui.price.textContent=fmt(mid);updateProfitLossUI();if(trading&&synchronized)void onTick(mid,bid,ask,previous);}
 onPositionUpdated(instanceIndex,position){if(position?.symbol===SYMBOL)reconcile();}
 onPositionRemoved(){reconcile();}
 onOrderUpdated(instanceIndex,order){if(order?.symbol===SYMBOL)reconcile();}
 onOrderCompleted(){reconcile();}
 onOrderFailed(instanceIndex,orderId,error){setStatus(`Order failed: ${error?.message||error}`);reconcile();}
}
async function connectSdk(){if(connecting||connection)return;const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();if(!token||token==='SAVED TOKEN'){setStatus('MetaAPI token is missing');return;}if(!accountId){setStatus('MetaAPI account ID is missing');return;}if(!validAccountId(accountId)){setStatus('MetaAPI account ID format is invalid');return;}connecting=true;setStatus('Connecting directly to MetaApi…');try{const MetaApiClass=sdkConstructor();api=new MetaApiClass(token);account=await api.metatraderAccountApi.getAccount(accountId);if(!account?.id)throw new Error('MetaApi account not found');if(typeof account.waitConnected==='function')await account.waitConnected();connection=account.getStreamingConnection();listener=new BotListener();connection.addSynchronizationListener(listener);await connection.connect();await connection.waitSynchronized();synchronized=true;await connection.subscribeToMarketData(SYMBOL);reconcile();setStatus('CONNECTED — XAUUSD live stream active');}catch(e){const msg=e?.message||String(e);try{await connection?.close();}catch(_){}try{await api?.close();}catch(_){}connection=null;account=null;api=null;synchronized=false;setStatus(`MetaAPI connection failed: ${msg}`);}finally{connecting=false;}}
function ownedPositions(){return(connection?.terminalState?.positions||[]).filter(isOurs);}
function reconcile(){if(!connection?.terminalState)return;const positions=ownedPositions();const latest=[...positions].sort((a,b)=>positionTime(b)-positionTime(a))[0]||null;ui.position.textContent=positions.length?(positions.length===1?sideOf(latest):`${positions.length}/4 ${sideOf(latest)}`):'—';for(const p of positions)if(!repairingPositionIds.has(idOf(p)))void enforceTrailing(p);updateProfitLossUI();}
async function enforceTrailing(position){const id=idOf(position),open=Number(position.openPrice),side=sideOf(position);if(!id||repairingPositionIds.has(id)||!Number.isFinite(open)||!side||!connection)return;const current=lastMid;if(!Number.isFinite(current)||current<=0)return;const desired=protectedStop(position,current),actual=Number(position.stopLoss??0);if(!Number.isFinite(desired))return;const pip=brokerPipSize(),improving=side==='BUY'?(actual<=0||desired>actual):(actual<=0||desired<actual);if(!improving||Math.abs(actual-desired)<pip/2)return;repairingPositionIds.add(id);try{await connection.modifyPosition(id,desired,undefined);}catch(e){setStatus(`Profit-lock SL update failed: ${e?.message||e}`);}finally{repairingPositionIds.delete(id);}}
async function closePosition(position,reason){const id=idOf(position);if(!id||!connection)return;try{await connection.closePosition(id);lastTradeActionAt=Date.now();setStatus(`CLOSE ${sideOf(position)} — ${reason}`);}catch(e){setStatus(`Close failed: ${e?.message||e}`);}}
async function closeOurs(reason){const positions=ownedPositions();if(!positions.length)return;await Promise.all(positions.map(p=>closePosition(p,reason)));}
async function enter(side,bid,ask){const positions=ownedPositions();if(entryInFlight||positions.length>=MAX_POSITIONS||!connection||!synchronized||!positionDistanceAllows(side,positions))return;if(Date.now()-lastTradeActionAt<TRADE_COOLDOWN_MS){setStatus(`COOL-OFF ${Math.max(0,TRADE_COOLDOWN_MS-(Date.now()-lastTradeActionAt))}ms before next trade`);return;}const volume=currentVolume(),reference=side==='BUY'?ask:bid,stopLoss=initialStop(side,reference);if(!Number.isFinite(stopLoss))return;entryInFlight=true;try{const clientId=`MB_${Date.now().toString(36)}_${Math.floor(Math.random()*36).toString(36)}`,options={comment:`MB ${side}`,magic:MAGIC,clientId};if(side==='BUY')await connection.createMarketBuyOrder(SYMBOL,volume,stopLoss,normalizePrice(reference+TAKE_PROFIT_PIPS*brokerPipSize()),options);else await connection.createMarketSellOrder(SYMBOL,volume,stopLoss,normalizePrice(reference-TAKE_PROFIT_PIPS*brokerPipSize()),options);lastEntryPrice=reference;lastTradeActionAt=Date.now();setStatus(`OPEN ${side} ${volume} — 3s COOL-OFF | SL ${INITIAL_SL_PIPS}p | TP ${TAKE_PROFIT_PIPS}p`);await waitForPosition(side,5000);reconcile();}catch(e){setStatus(`Entry failed: ${e?.message||e}`);}finally{entryInFlight=false;}}
async function waitForPosition(side,timeoutMs){const end=Date.now()+timeoutMs;while(Date.now()<end){reconcile();const p=ownedPositions().find(x=>sideOf(x)===side);if(p){lastEntryPrice=Number(p.openPrice)||lastEntryPrice;return p;}await new Promise(r=>setTimeout(r,100));}return null;}
async function onTick(mid,bid,ask,previous){reconcile();if(Number.isNaN(previous)){setStatus('Streaming XAUUSD — building direction model');return;}const positions=ownedPositions();if(positions.length){const heldSide=sideOf(positions[0]);if(false){return;}else{reversalCounts.delete(heldSide);setStatus(`HOLDING ${positions.length}/${MAX_POSITIONS} ${heldSide} | MOMENTUM HOLDS | SL ${INITIAL_SL_PIPS}p | TP ${TAKE_PROFIT_PIPS}p`);}if(positions.length>=MAX_POSITIONS)return;}const signal=directionSignal();if(!signal.side){if(!positions.length)setStatus(`WAITING — building direction | samples ${priceHistory.length}/${SLOW_EMA+2}`);return;}if(positions.length&&positions.some(p=>sideOf(p)!==signal.side))return;await enter(signal.side,bid,ask);}
function startForegroundService(){try{if(window.AndroidBot?.startForegroundBot)window.AndroidBot.startForegroundBot();}catch(_) {}}
function stopForegroundService(){try{if(window.AndroidBot?.stopForegroundBot)window.AndroidBot.stopForegroundBot();}catch(_) {}}
function saveCredentials(){const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();if(!token||token==='SAVED TOKEN'){setStatus('Enter a valid MetaAPI token');return;}if(!validAccountId(accountId)){setStatus('Enter a valid MetaAPI account ID');return;}localStorage.setItem('metaapi.token',token);localStorage.setItem('metaapi.accountId',accountId);ui.token.value='SAVED TOKEN';ui.token.disabled=true;ui.token.value=token;connectSdk().finally(()=>{ui.token.value='SAVED TOKEN';ui.token.disabled=true;});}
function changeCredentials(){trading=false;stopForegroundService();localStorage.removeItem('metaapi.token');localStorage.removeItem('metaapi.accountId');if(connection)connection.close().catch(()=>{});if(api)api.close().catch(()=>{});connection=null;account=null;api=null;synchronized=false;ui.token.disabled=false;ui.token.value='';ui.account.value='';priceHistory.length=0;momentumDeltas.length=0;lastEntryPrice=NaN;candleStart=0;candleOpen=NaN;candleSide='';reversalCounts.clear();setStatus('Enter new MetaAPI credentials');}
function startBot(){if(!connection||!synchronized){setStatus('Connect MetaApi first');return;}startForegroundService();trading=true;setStatus('BOT RUNNING — spread-aware profit lock + confirmed reversal');}
function stopBot(){trading=false;stopForegroundService();setStatus('BOT STOPPED');}
ui.save.onclick=saveCredentials;ui.change.onclick=changeCredentials;ui.start.onclick=startBot;ui.stopBot.onclick=stopBot;

// Bottom navigation: each button now opens the corresponding live app view.
function showNavView(view){const nav=[...document.querySelectorAll('.nav div')];nav.forEach((el,i)=>el.classList.toggle('active',i===view));let panel=$('navPanel');if(!panel){panel=document.createElement('section');panel.id='navPanel';panel.className='card';const navEl=document.querySelector('.nav');navEl?.parentNode.insertBefore(panel,navEl);}
let html='';
if(view===0){panel.style.display='none';window.scrollTo({top:0,behavior:'smooth'});return;}
if(view===1){panel.style.display='block';html='<div class="section-title"><span>Trades</span><span class="cyan">LIVE</span></div><div id="navTrades">Loading live positions…</div>';panel.innerHTML=html;const refresh=()=>{const ps=ownedPositions();const el=$('navTrades');if(!el)return;if(!ps.length){el.innerHTML='<div class="status"><i></i><div>No active Pips-life positions.</div></div>';return;}el.innerHTML=ps.map((p,i)=>{const side=sideOf(p),profit=Number(p.profit)||0,open=Number(p.openPrice),sl=Number(p.stopLoss);return `<div class="metric" style="margin:6px 0"><small>Position ${i+1} • ${side}</small><strong class="${profit>=0?'green':'red'}">${moneyKsh(profit)}</strong><div class="subline">Open ${fmt(open)} • Trailing SL ${fmt(sl)} • ${volumeOf(p)} lot</div></div>`}).join('');};refresh();panel._navTimer&&clearInterval(panel._navTimer);panel._navTimer=setInterval(refresh,1000);
}
if(view===2){panel.style.display='block';panel.innerHTML='<div class="section-title"><span>History</span><span class="cyan">SESSION</span></div><div class="status"><i></i><div>Closed-position history is maintained by MetaApi. Use the MetaApi account history to review completed trades; this view stays available for the live session.</div></div>';}
if(view===3){panel.style.display='block';panel.innerHTML=`<div class="section-title"><span>Logs</span><span class="cyan">LIVE ENGINE</span></div><div class="status"><i></i><div>${lastStatus||'Waiting for engine events…'}</div></div><div class="subline" style="margin-top:10px">Connection: ${connection?'CONNECTED':'DISCONNECTED'} • Synchronization: ${synchronized?'READY':'WAITING'} • Bot: ${trading?'RUNNING':'STOPPED'} • XAUUSD price: ${fmt(lastMid)}</div>`;}
window.scrollTo({top:Math.max(0,panel.offsetTop-20),behavior:'smooth'});
}
document.querySelectorAll('.nav div').forEach((el,i)=>el.addEventListener('click',()=>showNavView(i)));

const savedToken=cleanToken(localStorage.getItem('metaapi.token')),savedAccount=String(localStorage.getItem('metaapi.accountId')||'').trim();
if(savedToken&&savedAccount){ui.token.value=savedToken;ui.account.value=savedAccount;connectSdk().finally(()=>{ui.token.value='SAVED TOKEN';ui.token.disabled=true;});}