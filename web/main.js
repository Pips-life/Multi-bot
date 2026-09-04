import MetaApi, { SynchronizationListener } from 'metaapi.cloud-sdk';

const SYMBOL = 'XAUUSD';
const MAGIC = 260903;
const TRAIL_PIPS = 100;
const TAKE_PROFIT_PIPS = 130;
const EXECUTION_VOLUME = 0.01;
const XAUUSD_PIP_SIZE_FALLBACK = 0.01;
const MAX_POSITIONS = 10;
const METAAPI_PAIR_LIMIT = 26;

const $ = id => document.getElementById(id);
const ui = { token:$('token'), account:$('account'), price:$('price'), balance:$('balance'), position:$('position'), stop:$('stop'), status:$('status'), save:$('save'), change:$('change'), start:$('start'), stopBot:$('stop') };
let api=null, account=null, connection=null, listener=null;
let trading=false, connecting=false, synchronized=false, lastMid=NaN, entryInFlight=false, lastStatus='';
const stopByPosition=new Map();
const tpByPosition=new Map();
const closingPositionIds=new Set();
const protectionInFlight=new Set();
let lastEntrySide='';

function setStatus(text){if(text!==lastStatus){lastStatus=text;ui.status.textContent=text;}}
function fmt(n){return Number.isFinite(n)?Number(n).toFixed(2):'—';}
function sideOf(x){const t=String(x?.type??'').toUpperCase();return t.includes('BUY')?'BUY':t.includes('SELL')?'SELL':'';}
function isOurs(x){if(!x||x.symbol!==SYMBOL)return false;return Number(x.magic)===MAGIC||String(x.clientId??'').startsWith('MB_')||String(x.clientId??'').startsWith('E')||String(x.clientId??'').startsWith('S');}
function idOf(x){return String(x?.id??x?.positionId??x?.orderId??'');}
function volumeOf(x){return Number(x?.volume??0);}
function positionTime(x){const t=Date.parse(String(x?.time??x?.updateTime??''));return Number.isFinite(t)?t:0;}
function brokerPipSize(){const s=connection?.terminalState?.specification(SYMBOL);const p=Number(s?.pipSize??s?.point??0);return p>0?p:XAUUSD_PIP_SIZE_FALLBACK;}
function brokerDigits(){const s=connection?.terminalState?.specification(SYMBOL);const d=Number(s?.digits??2);return Number.isFinite(d)?d:2;}
function normalizePrice(p){return Number(Number(p).toFixed(brokerDigits()));}
function normalizeVolume(raw,spec){const min=Number(spec?.minVolume??0.01),max=Number(spec?.maxVolume??100),step=Number(spec?.volumeStep??0.01);let v=Math.max(min,Math.min(max,raw));if(step>0)v=Math.floor(v/step+1e-10)*step;return Number(Math.max(min,v).toFixed(6));}
function currentVolume(){const s=connection?.terminalState?.specification(SYMBOL);return normalizeVolume(EXECUTION_VOLUME,s||{});}
function opposite(side){return side==='BUY'?'SELL':'BUY';}
function cleanToken(v){return String(v??'').trim().replace(/^Bearer\s+/i,'');}
function validAccountId(v){return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);}
function sdkConstructor(){const Ctor=MetaApi?.default??MetaApi;if(typeof Ctor!=='function')throw new Error('MetaApi browser SDK constructor is unavailable');return Ctor;}
function positions(){return (connection?.terminalState?.positions||[]).filter(isOurs);}
function orders(){return (connection?.terminalState?.orders||[]).filter(isOurs);}
function sanitizeMetaText(v){return String(v??'').replace(/[^A-Za-z0-9_-]/g,'');}
function compactClientId(prefix,raw){const p=sanitizeMetaText(prefix).slice(0,2)||'M';const r=sanitizeMetaText(raw);return `${p}${r.slice(-8)}`.slice(0,12);}
function stopClientId(positionId){return compactClientId('S',positionId);}
function entryClientId(){return compactClientId('E',Date.now().toString(36));}
function tradeOptions(comment,clientId){let c=sanitizeMetaText(comment).slice(0,10);let id=sanitizeMetaText(clientId).slice(0,15);if(c.length+id.length>METAAPI_PAIR_LIMIT)id=id.slice(0,Math.max(1,METAAPI_PAIR_LIMIT-c.length));return {comment:c,magic:MAGIC,clientId:id};}
function tpPrice(position){const p=Number(position.openPrice),step=TAKE_PROFIT_PIPS*brokerPipSize();return normalizePrice(sideOf(position)==='BUY'?p+step:p-step);}
function stopPrice(position,mid){const step=TRAIL_PIPS*brokerPipSize();return normalizePrice(sideOf(position)==='BUY'?mid-step:mid+step);}

class BotListener extends SynchronizationListener{
 onConnected(){setStatus('MetaApi connected — synchronizing…');}
 onDisconnected(){synchronized=false;setStatus('MetaApi disconnected — waiting to reconnect…');}
 onSynchronizationStarted(){synchronized=false;setStatus('Synchronizing MetaApi terminal…');}
 onSynchronizationFinished(){synchronized=true;setStatus('CONNECTED — XAUUSD live stream active');void reconcile();}
 onSymbolPricesUpdated(instanceIndex,prices){const p=Array.isArray(prices)?prices.find(x=>x?.symbol===SYMBOL):(prices?.symbol===SYMBOL?prices:null);if(!p)return;const bid=Number(p.bid),ask=Number(p.ask);if(!Number.isFinite(bid)||!Number.isFinite(ask))return;const mid=(bid+ask)/2;const previous=lastMid;lastMid=mid;ui.price.textContent=fmt(mid);const info=connection?.terminalState?.accountInformation;if(info?.balance!=null)ui.balance.textContent=fmt(Number(info.balance));if(trading&&synchronized)void onTick(mid,bid,ask,previous);}
 onPositionUpdated(instanceIndex,p){if(p?.symbol===SYMBOL)void reconcile();}
 onPositionRemoved(){void reconcile();}
 onOrderUpdated(instanceIndex,o){if(o?.symbol===SYMBOL)void reconcile();}
 onOrderCompleted(){void reconcile();}
 onOrderFailed(instanceIndex,id,error){setStatus(`Order failed: ${error?.message||error}`);void reconcile();}
}

async function connectSdk(){
 if(connecting||connection)return;
 const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();
 if(!token||token==='SAVED TOKEN'){setStatus('MetaAPI token is missing');return;}
 if(!accountId){setStatus('MetaAPI account ID is missing');return;}
 if(!validAccountId(accountId)){setStatus('MetaAPI account ID format is invalid');return;}
 connecting=true;
 setStatus('Connecting directly to MetaApi…');
 try{
  const C=sdkConstructor();
  api=new C(token);
  account=await api.metatraderAccountApi.getAccount(accountId);
  if(!account?.id)throw new Error('MetaApi account not found');
  setStatus('MetaApi account found — checking deployment…');
  if(typeof account.waitConnected==='function')await account.waitConnected();
  connection=account.getStreamingConnection();
  listener=new BotListener();
  connection.addSynchronizationListener(listener);
  await connection.connect();
  await connection.waitSynchronized();
  synchronized=true;
  await connection.subscribeToMarketData(SYMBOL);
  void reconcile();
  setStatus('CONNECTED — XAUUSD live stream active');
 }catch(e){
  const msg=e?.message||String(e);
  try{if(connection)await connection.close();}catch(_){}
  try{if(api)await api.close();}catch(_){}
  connection=null;account=null;api=null;synchronized=false;
  setStatus(`MetaApi connection failed: ${msg}`);
 }finally{connecting=false;}
}

async function ensureTakeProfit(position){
 const pid=idOf(position);if(!pid||protectionInFlight.has(`tp:${pid}`))return;
 const target=tpPrice(position);if(!Number.isFinite(target)||target<=0)return;
 const existing=Number(position.takeProfit??position.tp??0);
 if(existing>0&&Math.abs(existing-target)<=Math.max(brokerPipSize()/2,10**(-brokerDigits()))){tpByPosition.set(pid,target);return;}
 protectionInFlight.add(`tp:${pid}`);
 try{
  const result=await connection.modifyPosition(pid,undefined,target);
  if(result?.stringCode&&result.stringCode!=='TRADE_RETCODE_DONE')throw new Error(result.message||result.stringCode);
  tpByPosition.set(pid,target);
  setStatus(`${sideOf(position)} ${pid.slice(-6)} — TP 130 pips set @ ${fmt(target)}`);
 }catch(e){setStatus(`TP placement failed for ${pid.slice(-6)}: ${e?.message||e}`);}finally{protectionInFlight.delete(`tp:${pid}`);}
}

async function ensureStop(position,mid){
 const pid=idOf(position);if(!pid||protectionInFlight.has(`sl:${pid}`))return;
 const existing=stopByPosition.get(pid);if(existing&&connection?.terminalState?.orders?.some(o=>idOf(o)===existing.id))return;
 const price=stopPrice(position,mid),volume=volumeOf(position)||currentVolume();if(!volume||!Number.isFinite(price)||price<=0)return;
 protectionInFlight.add(`sl:${pid}`);
 try{
  const clientId=stopClientId(pid),options=tradeOptions('REVSTOP',clientId);
  const result=sideOf(position)==='BUY'?await connection.createStopSellOrder(SYMBOL,volume,price,undefined,undefined,options):await connection.createStopBuyOrder(SYMBOL,volume,price,undefined,undefined,options);
  if(result?.stringCode&&result.stringCode!=='TRADE_RETCODE_DONE')throw new Error(result.message||result.stringCode);
  await new Promise(r=>setTimeout(r,20));void reconcile();
  const found=orders().find(o=>String(o.clientId??'')===clientId);
  if(found)stopByPosition.set(pid,{id:idOf(found),price,side:sideOf(position)});
 }catch(e){setStatus(`STOP placement failed for ${pid.slice(-6)}: ${e?.message||e}`);}finally{protectionInFlight.delete(`sl:${pid}`);}
}

async function trailPosition(position,mid){
 const pid=idOf(position),state=stopByPosition.get(pid);if(!state||protectionInFlight.has(`trail:${pid}`))return;
 const candidate=stopPrice(position,mid),existing=Number(state.price);const improve=sideOf(position)==='BUY'?candidate>existing:candidate<existing;if(!improve)return;
 protectionInFlight.add(`trail:${pid}`);
 try{const r=await connection.modifyOrder(state.id,candidate,undefined,undefined);if(r?.stringCode&&r.stringCode!=='TRADE_RETCODE_DONE')throw new Error(r.message||r.stringCode);state.price=candidate;}catch(e){setStatus(`STOP trail failed for ${pid.slice(-6)}: ${e?.message||e}`);}finally{protectionInFlight.delete(`trail:${pid}`);}
}

async function reconcile(){
 if(!connection?.terminalState||!synchronized)return;
 const ps=positions(),os=orders();
 ui.position.textContent=ps.length?ps.map(p=>sideOf(p)).join(' + '):'—';
 const first=ps[0];const firstStop=first?stopByPosition.get(idOf(first)):null;ui.stop.textContent=firstStop?fmt(firstStop.price):'—';
 const stopOrders=os.filter(o=>String(o.type??'').toUpperCase().includes('STOP'));
 for(const p of ps)void ensureTakeProfit(p);
 for(const p of ps){const pid=idOf(p),cid=stopClientId(pid);const found=stopOrders.find(o=>String(o.clientId??'')===cid);if(found)stopByPosition.set(pid,{id:idOf(found),price:Number(found.openPrice??found.currentPrice??0),side:sideOf(p)});else if(!stopByPosition.has(pid)&&Number.isFinite(lastMid))void ensureStop(p,lastMid);}
 for(const [pid,state] of stopByPosition){if(!ps.some(p=>idOf(p)===pid)){void cancelOrder(state.id);stopByPosition.delete(pid);tpByPosition.delete(pid);}}
}

async function enter(side){
 if(!connection||!synchronized||entryInFlight||positions().length>=MAX_POSITIONS)return;
 const volume=currentVolume();if(volume<=0)return;entryInFlight=true;
 try{
  const cid=entryClientId(),options=tradeOptions('ENTRY',cid);
  if(side==='BUY')await connection.createMarketBuyOrder(SYMBOL,volume,undefined,undefined,options);else await connection.createMarketSellOrder(SYMBOL,volume,undefined,undefined,options);
  lastEntrySide=side;setStatus(`OPEN ${side} ${volume} — installing 130-pip TP + reversal STOP…`);
  const end=Date.now()+5000;
  while(Date.now()<end){
   const ps=positions();
   const p=[...ps].reverse().find(x=>sideOf(x)===side&&!tpByPosition.has(idOf(x)));
   if(p){await ensureTakeProfit(p);await ensureStop(p,lastMid);return;}
   await new Promise(r=>setTimeout(r,50));
  }
 }catch(e){setStatus(`Entry failed: ${e?.message||e}`);}finally{entryInFlight=false;}
}

async function closePosition(p){const pid=idOf(p);if(!pid||closingPositionIds.has(pid))return;closingPositionIds.add(pid);try{await connection.closePosition(pid);}catch(e){const m=String(e?.message||e);if(!/not found|does not exist|closed/i.test(m))setStatus(`Close failed ${pid.slice(-6)}: ${m}`);}finally{closingPositionIds.delete(pid);}}

async function onTick(mid,bid,ask,previous){
 if(!synchronized)return;
 await reconcile();
 const ps=positions();
 for(const p of ps)await trailPosition(p,mid);
 if(!ps.length){
  if(entryInFlight||Number.isNaN(previous)){if(Number.isNaN(previous))setStatus('Streaming XAUUSD — waiting for first movement');return;}
  if(previous<mid&&lastEntrySide!=='BUY')await enter('BUY');else if(previous>mid&&lastEntrySide!=='SELL')await enter('SELL');return;
 }
 if(previous<mid&&lastEntrySide==='SELL')await enter('BUY');else if(previous>mid&&lastEntrySide==='BUY')await enter('SELL');
 const activeTps=ps.filter(p=>Number(p.takeProfit??0)>0).length;
 setStatus(`RUNNING ${ps.length} position(s) | 130-pip TP active on ${activeTps}/${ps.length}`);
}

async function cancelOrder(id){if(id&&connection){try{await connection.cancelOrder(id);}catch(_) {}}}
function startForegroundService(){try{window.AndroidBot?.startForegroundBot?.();}catch(_) {}}
function stopForegroundService(){try{window.AndroidBot?.stopForegroundBot?.();}catch(_) {}}
function saveCredentials(){const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();if(!token||token==='SAVED TOKEN'||!validAccountId(accountId)){setStatus('Enter valid MetaAPI credentials');return;}localStorage.setItem('metaapi.token',token);localStorage.setItem('metaapi.accountId',accountId);ui.token.value='SAVED TOKEN';ui.token.disabled=true;void connectSdk();}
function changeCredentials(){trading=false;stopForegroundService();void (async()=>{if(connection)try{await connection.close();}catch(_){}if(api)try{await api.close();}catch(_){}connection=null;account=null;api=null;synchronized=false;stopByPosition.clear();tpByPosition.clear();ui.token.disabled=false;ui.token.value='';ui.account.value='';setStatus('Enter new MetaAPI credentials');})();}
function startBot(){if(!connection||!synchronized){setStatus('Connect MetaApi first');return;}startForegroundService();trading=true;setStatus('BOT RUNNING — broker-side 130-pip TP + independent STOPs active');}
function stopBot(){trading=false;stopForegroundService();setStatus('BOT STOPPED');}
ui.save.onclick=saveCredentials;ui.change.onclick=changeCredentials;ui.start.onclick=startBot;ui.stopBot.onclick=stopBot;
const savedToken=cleanToken(localStorage.getItem('metaapi.token')),savedAccount=String(localStorage.getItem('metaapi.accountId')||'').trim();if(savedToken&&savedAccount){ui.token.value=savedToken;ui.account.value=savedAccount;void connectSdk().finally(()=>{ui.token.value='SAVED TOKEN';ui.token.disabled=true;});}