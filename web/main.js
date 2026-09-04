import MetaApi, { SynchronizationListener } from 'metaapi.cloud-sdk';

const SYMBOL = 'XAUUSD';
const MAGIC = 260904;
const SL_PIPS = 100;
const TP_PIPS = 130;
const MAX_POSITIONS = 4;
const EXECUTION_VOLUME = 0.01;
const XAUUSD_PIP_SIZE_FALLBACK = 0.01;
const HISTORY_SIZE = 40;
const FAST_EMA = 8;
const SLOW_EMA = 21;
const MIN_ENTRY_SPACING_PIPS = 35;

const $ = id => document.getElementById(id);
const ui = { token:$('token'), account:$('account'), price:$('price'), balance:$('balance'), position:$('position'), stop:$('stop'), status:$('status'), save:$('save'), change:$('change'), start:$('start'), stopBot:$('stop') };
let api=null, account=null, connection=null, listener=null;
let trading=false, connecting=false, synchronized=false;
let lastMid=NaN, entryInFlight=false, lastStatus='';
let lastEntryPrice=NaN;
const priceHistory=[];
const repairingPositionIds=new Set();

function setStatus(text){if(text!==lastStatus){lastStatus=text;ui.status.textContent=text;}}
function fmt(n){return Number.isFinite(n)?Number(n).toFixed(2):'—';}
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
  if(priceHistory.length<SLOW_EMA+2)return {side:'',score:0};
  const mids=priceHistory.map(x=>x.mid), fast=ema(mids.slice(-FAST_EMA*2),FAST_EMA), slow=ema(mids.slice(-SLOW_EMA*2),SLOW_EMA);
  const side=fast>slow?'BUY':fast<slow?'SELL':'';
  return {side,score:side?1:0};
}
function positionDistanceAllows(side,positions){if(!Number.isFinite(lastEntryPrice))return true;const pip=brokerPipSize();const same=[...positions].filter(p=>sideOf(p)===side).sort((a,b)=>positionTime(b)-positionTime(a))[0];const ref=Number(same?.openPrice??lastEntryPrice);return !Number.isFinite(ref)||Math.abs(lastMid-ref)/pip>=MIN_ENTRY_SPACING_PIPS;}
function protectiveLevels(side,reference){const base=Number(reference),pip=brokerPipSize();if(!Number.isFinite(base)||base<=0)return {stopLoss:undefined,takeProfit:undefined};return {stopLoss:normalizePrice(side==='BUY'?base-SL_PIPS*pip:base+SL_PIPS*pip),takeProfit:normalizePrice(side==='BUY'?base+TP_PIPS*pip:base-TP_PIPS*pip)};}
function tradeOptions(comment,clientId){return {comment,magic:MAGIC,clientId};}

class BotListener extends SynchronizationListener{
  onConnected(){setStatus('MetaApi connected — synchronizing…');}
  onDisconnected(){synchronized=false;setStatus('MetaApi disconnected — waiting to reconnect…');}
  onSynchronizationStarted(){synchronized=false;setStatus('Synchronizing MetaApi terminal…');}
  onSynchronizationFinished(){synchronized=true;setStatus('CONNECTED — XAUUSD live stream active');reconcile();}
  onSymbolPricesUpdated(instanceIndex,prices){const p=Array.isArray(prices)?prices.find(x=>x?.symbol===SYMBOL):(prices?.symbol===SYMBOL?prices:null);if(!p)return;const bid=Number(p.bid),ask=Number(p.ask);if(!Number.isFinite(bid)||!Number.isFinite(ask)||bid<=0||ask<=0||ask<bid)return;const mid=(bid+ask)/2;const previous=lastMid;lastMid=mid;priceHistory.push({mid,bid,ask,time:Date.now()});if(priceHistory.length>HISTORY_SIZE)priceHistory.shift();ui.price.textContent=fmt(mid);const info=connection?.terminalState?.accountInformation;if(info?.balance!=null)ui.balance.textContent=fmt(Number(info.balance));if(trading&&synchronized)void onTick(mid,bid,ask,previous);}
  onPositionUpdated(instanceIndex,position){if(position?.symbol===SYMBOL)reconcile();}
  onPositionRemoved(){reconcile();}
  onOrderUpdated(instanceIndex,order){if(order?.symbol===SYMBOL)reconcile();}
  onOrderCompleted(){reconcile();}
  onOrderFailed(instanceIndex,orderId,error){setStatus(`Order failed: ${error?.message||error}`);reconcile();}
}
async function connectSdk(){if(connecting||connection)return;const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();if(!token||token==='SAVED TOKEN'){setStatus('MetaAPI token is missing');return;}if(!accountId){setStatus('MetaAPI account ID is missing');return;}if(!validAccountId(accountId)){setStatus('MetaAPI account ID format is invalid');return;}connecting=true;setStatus('Connecting directly to MetaApi…');try{const MetaApiClass=sdkConstructor();api=new MetaApiClass(token);account=await api.metatraderAccountApi.getAccount(accountId);if(!account?.id)throw new Error('MetaApi account not found');if(typeof account.waitConnected==='function')await account.waitConnected();connection=account.getStreamingConnection();listener=new BotListener();connection.addSynchronizationListener(listener);await connection.connect();await connection.waitSynchronized();synchronized=true;await connection.subscribeToMarketData(SYMBOL);reconcile();setStatus('CONNECTED — XAUUSD live stream active');}catch(e){const msg=e?.message||String(e);try{await connection?.close();}catch(_){}try{await api?.close();}catch(_){}connection=null;account=null;api=null;synchronized=false;setStatus(`MetaApi connection failed: ${msg}`);}finally{connecting=false;}}
function ownedPositions(){return (connection?.terminalState?.positions||[]).filter(isOurs);}
function reconcile(){if(!connection?.terminalState)return;const positions=ownedPositions();const latest=[...positions].sort((a,b)=>positionTime(b)-positionTime(a))[0]||null;ui.position.textContent=positions.length?(positions.length===1?sideOf(latest):`${positions.length}/4 ${sideOf(latest)}`):'—';const sl=Number(latest?.stopLoss??0);ui.stop.textContent=sl>0?fmt(sl):'—';for(const p of positions)if(!repairingPositionIds.has(idOf(p)))void enforceProtection(p);}
async function enforceProtection(position){const id=idOf(position),open=Number(position.openPrice),side=sideOf(position);if(!id||repairingPositionIds.has(id)||!Number.isFinite(open)||!side||!connection)return;const {stopLoss,takeProfit}=protectiveLevels(side,open);if(!Number.isFinite(stopLoss)||!Number.isFinite(takeProfit))return;const actualSl=Number(position.stopLoss??0),actualTp=Number(position.takeProfit??0),pip=brokerPipSize();if(Math.abs(actualSl-stopLoss)<pip/2&&Math.abs(actualTp-takeProfit)<pip/2)return;repairingPositionIds.add(id);try{await connection.modifyPosition(id,stopLoss,takeProfit);}catch(e){setStatus(`Protection update failed: ${e?.message||e}`);}finally{repairingPositionIds.delete(id);}}
async function enter(side,bid,ask,signal){const positions=ownedPositions();if(entryInFlight||positions.length>=MAX_POSITIONS||!connection||!synchronized||!positionDistanceAllows(side,positions))return;const volume=currentVolume(),reference=side==='BUY'?ask:bid,{stopLoss,takeProfit}=protectiveLevels(side,reference);if(!Number.isFinite(stopLoss)||!Number.isFinite(takeProfit))return;entryInFlight=true;try{const clientId=`MB_${Date.now()}_${Math.floor(Math.random()*1000)}`,options=tradeOptions(`MB ${side} SL100 TP130`,clientId);if(side==='BUY')await connection.createMarketBuyOrder(SYMBOL,volume,stopLoss,takeProfit,options);else await connection.createMarketSellOrder(SYMBOL,volume,stopLoss,takeProfit,options);lastEntryPrice=reference;setStatus(`OPEN ${side} ${volume} — FIXED SL ${SL_PIPS} / TP ${TP_PIPS}`);await waitForPosition(side,5000);reconcile();}catch(e){setStatus(`Entry failed: ${e?.message||e}`);}finally{entryInFlight=false;}}
async function waitForPosition(side,timeoutMs){const end=Date.now()+timeoutMs;while(Date.now()<end){reconcile();const p=ownedPositions().find(x=>sideOf(x)===side);if(p){lastEntryPrice=Number(p.openPrice)||lastEntryPrice;return p;}await new Promise(r=>setTimeout(r,100));}return null;}
async function onTick(mid,bid,ask,previous){reconcile();if(Number.isNaN(previous)){setStatus('Streaming XAUUSD — building direction model');return;}const signal=directionSignal();if(!signal.side){if(!ownedPositions().length)setStatus(`WAITING — building direction | samples ${priceHistory.length}/${SLOW_EMA+2}`);return;}const positions=ownedPositions();if(positions.length>=MAX_POSITIONS){setStatus(`HOLDING ${positions.length}/${MAX_POSITIONS} ${signal.side} | FIXED SL ${SL_PIPS} / TP ${TP_PIPS}`);return;}if(positions.length&&positions.some(p=>sideOf(p)!==signal.side))return;await enter(signal.side,bid,ask,signal);}
function startForegroundService(){try{if(window.AndroidBot?.startForegroundBot)window.AndroidBot.startForegroundBot();}catch(_) {}}
function stopForegroundService(){try{if(window.AndroidBot?.stopForegroundBot)window.AndroidBot.stopForegroundBot();}catch(_) {}}
function saveCredentials(){const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();if(!token||token==='SAVED TOKEN'){setStatus('Enter a valid MetaAPI token');return;}if(!validAccountId(accountId)){setStatus('Enter a valid MetaAPI account ID');return;}localStorage.setItem('metaapi.token',token);localStorage.setItem('metaapi.accountId',accountId);ui.token.value='SAVED TOKEN';ui.token.disabled=true;const original=token;ui.token.value=original;connectSdk().finally(()=>{ui.token.value='SAVED TOKEN';ui.token.disabled=true;});}
function changeCredentials(){trading=false;stopForegroundService();localStorage.removeItem('metaapi.token');localStorage.removeItem('metaapi.accountId');if(connection)connection.close().catch(()=>{});if(api)api.close().catch(()=>{});connection=null;account=null;api=null;synchronized=false;ui.token.disabled=false;ui.token.value='';ui.account.value='';priceHistory.length=0;lastEntryPrice=NaN;setStatus('Enter new MetaAPI credentials');}
function startBot(){if(!connection||!synchronized){setStatus('Connect MetaApi first');return;}startForegroundService();trading=true;setStatus('BOT RUNNING — direction-first execution');}
function stopBot(){trading=false;stopForegroundService();setStatus('BOT STOPPED');}
ui.save.onclick=saveCredentials;ui.change.onclick=changeCredentials;ui.start.onclick=startBot;ui.stopBot.onclick=stopBot;
const savedToken=cleanToken(localStorage.getItem('metaapi.token')),savedAccount=String(localStorage.getItem('metaapi.accountId')||'').trim();
if(savedToken&&savedAccount){ui.token.value=savedToken;ui.account.value=savedAccount;connectSdk().finally(()=>{ui.token.value='SAVED TOKEN';ui.token.disabled=true;});}
