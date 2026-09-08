import MetaApi, { SynchronizationListener } from 'metaapi.cloud-sdk';

const SYMBOL='XAUUSD';
const MAGIC=260904;
const SL_PIPS=100;
const MAX_POSITIONS=4;
const EXECUTION_VOLUME=0.01;
const XAUUSD_PIP_SIZE_FALLBACK=0.01;
const HISTORY_SIZE=40;
const FAST_EMA=8;
const SLOW_EMA=21;
const QUICK_LOOKBACK_TICKS=4;
const QUICK_MIN_DIRECTIONAL_TICKS=3;
const QUICK_MIN_NET_PIPS=1.0;
const QUICK_MIN_VELOCITY_PIPS=0.25;
const QUICK_MIN_ACCELERATION_PIPS=0.03;
const MIN_ENTRY_SPACING_PIPS=3;
const EARLY_EXIT_LOOKBACK_TICKS=4;
const EARLY_EXIT_MIN_PROFIT_PIPS=2;
const EARLY_EXIT_MIN_ADVERSE_PIPS=1.5;
const EARLY_EXIT_HOLD_SCORE=0.55;

// +100 pips arms same-candle momentum reversal protection; it is NOT a TP.
const MOMENTUM_ARM_PIPS=100;
const REVERSAL_LOOKBACK_TICKS=4;
const REVERSAL_MIN_ADVERSE_PIPS=2.5;
const REVERSAL_MIN_PEAK_RETRACE_PIPS=4;

const $=id=>document.getElementById(id);
const ui={token:$('token'),account:$('account'),price:$('price'),balance:$('balance'),position:$('position'),stop:$('stop'),status:$('status'),save:$('save'),change:$('change'),start:$('start'),stopBot:$('stop')};
let api=null,account=null,connection=null,listener=null;
let trading=false,connecting=false,synchronized=false;
let lastMid=NaN,entryInFlight=false,lastStatus='';
let lastEntryPrice=NaN,signalSide='';
const priceHistory=[];
const repairingPositionIds=new Set();
const momentumExitState=new Map();

function setStatus(text){if(text!==lastStatus){lastStatus=text;ui.status.textContent=text;}}
function fmt(n){return Number.isFinite(n)?Number(n).toFixed(2):'—';}
function sideOf(x){const t=String(x?.type??'').toUpperCase();return t.includes('BUY')?'BUY':t.includes('SELL')?'SELL':'';}
function isOurs(x){return !!x&&x.symbol===SYMBOL&&Number(x.magic)===MAGIC;}
function idOf(x){return String(x?.id??x?.positionId??x?.orderId??'');}
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
 if(priceHistory.length<QUICK_LOOKBACK_TICKS)return {side:'',score:0};
 const mids=priceHistory.map(x=>x.mid),recent=mids.slice(-QUICK_LOOKBACK_TICKS),pip=brokerPipSize();
 let ups=0,downs=0;
 for(let i=1;i<recent.length;i++){if(recent[i]>recent[i-1])ups++;else if(recent[i]<recent[i-1])downs++;}
 const netPips=(recent.at(-1)-recent[0])/pip;
 const velocityPips=netPips/Math.max(1,recent.length-1);
 const half=2;
 const firstHalf=(recent[half-1]-recent[0])/pip;
 const secondHalf=(recent.at(-1)-recent[half])/pip;
 const accelerationPips=secondHalf-firstHalf;
 const fast=ema(mids.slice(-FAST_EMA*2),FAST_EMA);
 const slow=ema(mids.slice(-SLOW_EMA*2),SLOW_EMA);
 const oldFast=ema(mids.slice(-(FAST_EMA*2+4),-4),FAST_EMA);
 const slopePips=(fast-oldFast)/pip;
 const bias=fast>slow?'BUY':fast<slow?'SELL':'';
 const bullish=ups>=QUICK_MIN_DIRECTIONAL_TICKS&&netPips>=QUICK_MIN_NET_PIPS&&velocityPips>=QUICK_MIN_VELOCITY_PIPS&&(accelerationPips>=QUICK_MIN_ACCELERATION_PIPS||slopePips>=0.30);
 const bearish=downs>=QUICK_MIN_DIRECTIONAL_TICKS&&netPips<=-QUICK_MIN_NET_PIPS&&velocityPips<=-QUICK_MIN_VELOCITY_PIPS&&(accelerationPips<=-QUICK_MIN_ACCELERATION_PIPS||slopePips<=-0.30);
 const side=bullish?'BUY':bearish?'SELL':'';
 const consistency=Math.max(ups,downs)/Math.max(1,recent.length-1);
 const velocityScore=Math.min(1,Math.abs(velocityPips)/1.25);
 const accelerationScore=Math.min(1,Math.abs(accelerationPips)/1.5);
 const biasScore=side&&bias===side?1:0;
 const score=Math.min(1,consistency*.5+velocityScore*.25+accelerationScore*.15+biasScore*.10);
 return {side,score,consistency,slopePips,netPips,velocityPips,accelerationPips,bias};
}
function confirmedDirection(){const s=directionSignal();signalSide=s.side;return s;}
function positionDistanceAllows(side,positions){if(!Number.isFinite(lastEntryPrice))return true;const pip=brokerPipSize();const same=[...positions].filter(p=>sideOf(p)===side).sort((a,b)=>positionTime(b)-positionTime(a))[0];const ref=Number(same?.openPrice??lastEntryPrice);return !Number.isFinite(ref)||Math.abs(lastMid-ref)/pip>=MIN_ENTRY_SPACING_PIPS;}
function protectiveLevels(side,reference){const base=Number(reference),pip=brokerPipSize();if(!Number.isFinite(base)||base<=0)return {stopLoss:undefined};return {stopLoss:normalizePrice(side==='BUY'?base-SL_PIPS*pip:base+SL_PIPS*pip)};}
// Deliberately omit clientId. The bot identifies its own positions by magic number,
// avoiding MetaApi clientId/comment validation and the old combined-length failure.
function tradeOptions(side){return {comment:side==='BUY'?'B':'S',magic:MAGIC};}
function errorText(e){const detail=e?.details;let extra='';try{extra=detail?` | details: ${typeof detail==='string'?detail:JSON.stringify(detail)}`:'';}catch(_){}const code=e?.stringCode||e?.numericCode?` [${e?.stringCode||e?.numericCode}]`:'';return `${e?.message||String(e)}${code}${extra}`;}
function candleId(timeMs){return Math.floor(Number(timeMs)/60000);}
function profitPips(position,reference){const open=Number(position?.openPrice),ref=Number(reference);if(!Number.isFinite(open)||!Number.isFinite(ref))return NaN;const pip=brokerPipSize();return sideOf(position)==='BUY'?(ref-open)/pip:(open-ref)/pip;}
function reversalDetected(state,side,reference,pip){
 state.prices.push(Number(reference));
 if(state.prices.length>REVERSAL_LOOKBACK_TICKS)state.prices.shift();
 if(state.prices.length<REVERSAL_LOOKBACK_TICKS)return false;
 let adverseMoves=0,favorableMoves=0;
 for(let i=1;i<state.prices.length;i++){const d=(state.prices[i]-state.prices[i-1])/pip;if(side==='BUY'){if(d<0)adverseMoves++;if(d>0)favorableMoves++;}else{if(d>0)adverseMoves++;if(d<0)favorableMoves++;}}
 const adverseFromPeak=side==='BUY'?(state.peak-reference)/pip:(reference-state.peak)/pip;
 const netAgainst=side==='BUY'?(state.prices[0]-state.prices.at(-1))/pip:(state.prices.at(-1)-state.prices[0])/pip;
 return adverseMoves>=2&&adverseMoves>favorableMoves&&netAgainst>=REVERSAL_MIN_ADVERSE_PIPS&&adverseFromPeak>=REVERSAL_MIN_PEAK_RETRACE_PIPS;
}
async function manageMomentumExits(positions,reference,bid,ask,now){
 const activeIds=new Set(positions.map(idOf));
 for(const id of momentumExitState.keys())if(!activeIds.has(id))momentumExitState.delete(id);
 for(const p of positions){
  const id=idOf(p),side=sideOf(p);if(!id||!side)continue;
  let state=momentumExitState.get(id);const currentCandle=candleId(now);
  if(!state){state={candle:null,armed:false,peak:Number(reference),prices:[],exitInFlight:false};momentumExitState.set(id,state);}
  if(state.candle!==currentCandle){state.candle=currentCandle;state.armed=false;state.peak=Number(reference);state.prices=[];state.exitInFlight=false;}
  const pp=profitPips(p,reference);if(!Number.isFinite(pp))continue;
  if(pp>=MOMENTUM_ARM_PIPS){state.armed=true;state.peak=side==='BUY'?Math.max(state.peak,Number(reference)):Math.min(state.peak,Number(reference));}
  else if(!state.armed){state.prices=[];continue;}
  if(!state.armed||state.exitInFlight)continue;
  if(side==='BUY')state.peak=Math.max(state.peak,Number(reference));else state.peak=Math.min(state.peak,Number(reference));
  if(reversalDetected(state,side,reference,brokerPipSize())){
   state.exitInFlight=true;setStatus(`QUICK EXIT — ${side} momentum reversed after +${pp.toFixed(1)} pips`);
   try{await connection.closePosition(id);}catch(e){state.exitInFlight=false;setStatus(`Quick exit failed: ${errorText(e)}`);}
  }
 }
}

function earlyMomentumExitSignal(position,signal,reference){
 const side=sideOf(position),pp=profitPips(position,reference),pip=brokerPipSize();
 if(!side||!Number.isFinite(pp)||pp>=MOMENTUM_ARM_PIPS)return false;
 if(signal.side===side&&signal.score>=EARLY_EXIT_HOLD_SCORE&&((side==='BUY'&&signal.velocityPips>0)||(side==='SELL'&&signal.velocityPips<0)))return false;
 const recent=priceHistory.slice(-EARLY_EXIT_LOOKBACK_TICKS).map(x=>Number(x.mid));
 if(recent.length<EARLY_EXIT_LOOKBACK_TICKS)return false;
 const net=(recent.at(-1)-recent[0])/pip;
 const adverse=side==='BUY'?-net:net;
 const directionalLoss=signal.side&&signal.side!==side;
 const momentumStalled=signal.side===''||signal.score<EARLY_EXIT_HOLD_SCORE;
 if(pp>=EARLY_EXIT_MIN_PROFIT_PIPS&&(adverse>=EARLY_EXIT_MIN_ADVERSE_PIPS||directionalLoss||momentumStalled))return true;
 if(pp<=EARLY_EXIT_MIN_PROFIT_PIPS&&adverse>=EARLY_EXIT_MIN_ADVERSE_PIPS)return true;
 return false;
}
async function manageEarlyMomentumExits(positions,reference){
 for(const p of positions){
  const id=idOf(p);if(!id)continue;
  const signal=directionSignal();
  if(!earlyMomentumExitSignal(p,signal,reference))continue;
  const pp=profitPips(p,reference);
  setStatus(`EARLY EXIT — ${sideOf(p)} momentum faded${Number.isFinite(pp)?` at ${pp>=0?'+':''}${pp.toFixed(1)} pips`:''}`);
  try{await connection.closePosition(id);}catch(e){setStatus(`Early exit failed: ${errorText(e)}`);}
 }
}

class BotListener extends SynchronizationListener{
 onConnected(){setStatus('MetaApi connected — synchronizing…');}
 onDisconnected(){synchronized=false;setStatus('MetaApi disconnected — waiting to reconnect…');}
 onSynchronizationStarted(){synchronized=false;setStatus('Synchronizing MetaApi terminal…');}
 onSynchronizationFinished(){synchronized=true;setStatus('CONNECTED — XAUUSD live stream active');reconcile();}
 onSymbolPricesUpdated(instanceIndex,prices){const p=Array.isArray(prices)?prices.find(x=>x?.symbol===SYMBOL):(prices?.symbol===SYMBOL?prices:null);if(!p)return;const bid=Number(p.bid),ask=Number(p.ask);if(!Number.isFinite(bid)||!Number.isFinite(ask)||bid<=0||ask<=0||ask<bid)return;const mid=(bid+ask)/2,previous=lastMid;lastMid=mid;priceHistory.push({mid,bid,ask,time:Date.now()});if(priceHistory.length>HISTORY_SIZE)priceHistory.shift();ui.price.textContent=fmt(mid);const info=connection?.terminalState?.accountInformation;if(info?.balance!=null)ui.balance.textContent=fmt(Number(info.balance));if(trading&&synchronized)void onTick(mid,bid,ask,previous);}
 onPositionUpdated(instanceIndex,position){if(position?.symbol===SYMBOL)reconcile();}
 onPositionRemoved(){reconcile();}
 onOrderUpdated(instanceIndex,order){if(order?.symbol===SYMBOL)reconcile();}
 onOrderCompleted(){reconcile();}
 onOrderFailed(instanceIndex,orderId,error){setStatus(`Order failed: ${errorText(error)}`);reconcile();}
}
async function connectSdk(){if(connecting)return false;if(connection&&synchronized)return true;const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();if(!token||token==='SAVED TOKEN'){setStatus('MetaAPI token is missing');return false;}if(!accountId){setStatus('MetaAPI account ID is missing');return false;}if(!validAccountId(accountId)){setStatus('MetaAPI account ID format is invalid');return false;}connecting=true;setStatus('Connecting directly to MetaApi…');try{const MetaApiClass=sdkConstructor();if(!api)api=new MetaApiClass(token);if(!account)account=await api.metatraderAccountApi.getAccount(accountId);if(!account?.id)throw new Error('MetaApi account not found');if(typeof account.waitConnected==='function')await account.waitConnected();if(!connection){connection=account.getStreamingConnection();listener=new BotListener();connection.addSynchronizationListener(listener);}await connection.connect();await connection.waitSynchronized();synchronized=true;await connection.subscribeToMarketData(SYMBOL);reconcile();setStatus('CONNECTED — XAUUSD live stream active');return true;}catch(e){const msg=errorText(e);try{await connection?.close();}catch(_){}try{await api?.close();}catch(_){}connection=null;account=null;api=null;synchronized=false;setStatus(`MetaApi connection failed: ${msg}`);return false;}finally{connecting=false;}}
function ownedPositions(){return (connection?.terminalState?.positions||[]).filter(isOurs);}
function reconcile(){if(!connection?.terminalState)return;const positions=ownedPositions();const latest=[...positions].sort((a,b)=>positionTime(b)-positionTime(a))[0]||null;ui.position.textContent=positions.length?(positions.length===1?sideOf(latest):`${positions.length}/4 ${sideOf(latest)}`):'—';const sl=Number(latest?.stopLoss??0);ui.stop.textContent=sl>0?fmt(sl):'—';for(const p of positions)if(!repairingPositionIds.has(idOf(p)))void enforceProtection(p);}
async function enforceProtection(position){const id=idOf(position),open=Number(position.openPrice),side=sideOf(position);if(!id||repairingPositionIds.has(id)||!Number.isFinite(open)||!side||!connection)return;const {stopLoss}=protectiveLevels(side,open);if(!Number.isFinite(stopLoss))return;repairingPositionIds.add(id);try{const actualSl=Number(position.stopLoss??0),pip=brokerPipSize();if(Math.abs(actualSl-stopLoss)>=pip/2)await connection.modifyPosition(id,stopLoss,undefined);}catch(e){setStatus(`Protection update failed: ${errorText(e)}`);}finally{repairingPositionIds.delete(id);}}
async function enter(side,bid,ask,signal){const positions=ownedPositions();if(entryInFlight||positions.length>=MAX_POSITIONS||!connection||!synchronized||!positionDistanceAllows(side,positions))return;const volume=currentVolume(),reference=side==='BUY'?ask:bid,{stopLoss}=protectiveLevels(side,reference);if(!Number.isFinite(stopLoss))return;entryInFlight=true;try{const options=tradeOptions(side);if(side==='BUY')await connection.createMarketBuyOrder(SYMBOL,volume,stopLoss,undefined,options);else await connection.createMarketSellOrder(SYMBOL,volume,stopLoss,undefined,options);lastEntryPrice=reference;setStatus(`OPEN ${side} ${volume} — quick momentum ${Math.round(signal.score*100)}% | reversal exit armed at +${MOMENTUM_ARM_PIPS} pips`);await waitForPosition(side,5000);reconcile();}catch(e){setStatus(`Entry failed: ${errorText(e)}`);}finally{entryInFlight=false;}}
async function waitForPosition(side,timeoutMs){const end=Date.now()+timeoutMs;while(Date.now()<end){reconcile();const p=ownedPositions().find(x=>sideOf(x)===side);if(p){lastEntryPrice=Number(p.openPrice)||lastEntryPrice;return p;}await new Promise(r=>setTimeout(r,100));}return null;}
async function onTick(mid,bid,ask,previous){const positions=ownedPositions();if(positions.length){await manageEarlyMomentumExits(positions,mid);await manageMomentumExits(positions,mid,bid,ask,Date.now());}reconcile();if(Number.isNaN(previous)){setStatus('Streaming XAUUSD — building quick momentum model');return;}const signal=confirmedDirection();if(!signal.side){if(!ownedPositions().length)setStatus(`SCANNING — quick momentum | ${priceHistory.length}/${QUICK_LOOKBACK_TICKS} ticks`);return;}const livePositions=ownedPositions();if(livePositions.length>=MAX_POSITIONS){setStatus(`HOLDING ${livePositions.length}/${MAX_POSITIONS} ${signal.side} — momentum active | reversal exit +${MOMENTUM_ARM_PIPS}`);return;}if(livePositions.length&&livePositions.some(p=>sideOf(p)!==signal.side))return;await enter(signal.side,bid,ask,signal);}
function startForegroundService(){try{if(window.AndroidBot?.startForegroundBot)window.AndroidBot.startForegroundBot();}catch(_) {}}
function stopForegroundService(){try{if(window.AndroidBot?.stopForegroundBot)window.AndroidBot.stopForegroundBot();}catch(_) {}}
function bindUi(){ui.save.onclick=()=>{localStorage.setItem('metaapiToken',cleanToken(ui.token.value));localStorage.setItem('metaapiAccount',ui.account.value.trim());setStatus('Credentials saved on device');};ui.change.onclick=()=>{ui.token.value='';ui.account.value='';localStorage.removeItem('metaapiToken');localStorage.removeItem('metaapiAccount');setStatus('Credentials cleared');};ui.start.onclick=async()=>{if(trading||connecting)return;signalSide='';lastMid=NaN;priceHistory.length=0;trading=false;startForegroundService();setStatus('START BOT — connecting…');const ok=await connectSdk();if(!ok){stopForegroundService();return;}trading=true;setStatus('BOT STARTED — scanning quick XAUUSD momentum');};ui.stopBot.onclick=async()=>{trading=false;stopForegroundService();setStatus('BOT STOPPED');};ui.token.value=localStorage.getItem('metaapiToken')||'';ui.account.value=localStorage.getItem('metaapiAccount')||'';}
bindUi();
