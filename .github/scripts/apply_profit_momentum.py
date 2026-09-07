from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

# --- Trading management: 200 pip protective SL, no fixed TP, momentum exits remain ---
s = s.replace("const INITIAL_SL_PIPS=100;\nconst TAKE_PROFIT_PIPS=200;", "const INITIAL_SL_PIPS=200;\nconst PROFIT_MANAGEMENT_PIPS=100;\nconst ADVERSE_MOMENTUM_PIPS=100;")
s = s.replace("const CANDLE_MS=300000;", "const CANDLE_MS=60000;")
s = s.replace("// After the whole position batch closes, wait 3 seconds before allowing a new batch.\nconst TRADE_COOLDOWN_MS=3000;\nlet lastClosureAt=0;", "// No fixed post-close cool-off: entries are governed by margin and confirmed direction.\n")
s = s.replace("if(previousOwnedCount>0&&positions.length===0){lastClosureAt=Date.now();setStatus('ALL POSITIONS CLOSED — 3s COOL-OFF before next batch');}", "if(previousOwnedCount>0&&positions.length===0){setStatus('ALL POSITIONS CLOSED — ready for next confirmed direction');}")
s = s.replace("async function closeOurs(reason){const positions=ownedPositions();if(!positions.length)return;await Promise.all(positions.map(p=>closePosition(p,reason)));lastClosureAt=Date.now();setStatus('ALL POSITIONS CLOSE REQUESTS SENT — 3s COOL-OFF');}", "async function closeOurs(reason){const positions=ownedPositions();if(!positions.length)return;await Promise.all(positions.map(p=>closePosition(p,reason)));setStatus('ALL POSITIONS CLOSE REQUESTS SENT');}")

old = "if(entryInFlight||positions.length>=MAX_POSITIONS||!connection||!synchronized||!positionDistanceAllows(side,positions))return;if(Date.now()-lastClosureAt<TRADE_COOLDOWN_MS){const left=TRADE_COOLDOWN_MS-(Date.now()-lastClosureAt);setStatus(`COOL-OFF ${left}ms before next batch`);return;}const slots=Math.max(0,MAX_POSITIONS-positions.length);if(!slots)return;const volume=currentVolume(),reference=side==='BUY'?ask:bid,stopLoss=initialStop(side,reference);"
new = "if(entryInFlight||positions.length>=MAX_POSITIONS||!connection||!synchronized||!positionDistanceAllows(side,positions))return;const info=connection?.terminalState?.accountInformation||{};const freeMargin=Number(info.freeMargin);if(Number.isFinite(freeMargin)&&freeMargin<=0){setStatus('ENTRY BLOCKED — insufficient free margin');return;}const slots=Math.max(0,MAX_POSITIONS-positions.length);if(!slots)return;const volume=currentVolume();const estimatedMarginPerTrade=Number(connection?.terminalState?.specification(SYMBOL)?.marginRequired)||0;const affordable=estimatedMarginPerTrade>0&&Number.isFinite(freeMargin)?Math.max(0,Math.floor(freeMargin/estimatedMarginPerTrade)):slots;const marginSlots=Math.min(slots,affordable||slots);if(!marginSlots)return;const reference=side==='BUY'?ask:bid,stopLoss=initialStop(side,reference);"
s = s.replace(old, new)
s = s.replace("for(let i=0;i<slots;i++)", "for(let i=0;i<marginSlots;i++)")

# Remove TP argument from both market-order calls. MetaApi receives undefined TP,
# so the broker gets the protective SL but no fixed take-profit order.
s = s.replace("connection.createMarketBuyOrder(SYMBOL,volume,stopLoss,normalizePrice(reference+TAKE_PROFIT_PIPS*brokerPipSize()),options)", "connection.createMarketBuyOrder(SYMBOL,volume,stopLoss,undefined,options)")
s = s.replace("connection.createMarketSellOrder(SYMBOL,volume,stopLoss,normalizePrice(reference-TAKE_PROFIT_PIPS*brokerPipSize()),options)", "connection.createMarketSellOrder(SYMBOL,volume,stopLoss,undefined,options)")
s = s.replace("lastEntryPrice=reference;setStatus(`OPEN BATCH ${side} ${marginSlots} × ${volume} — margin-aware | SL ${INITIAL_SL_PIPS}p | TP ${TAKE_PROFIT_PIPS}p`);", "lastEntryPrice=reference;setStatus(`OPEN BATCH ${side} ${marginSlots} × ${volume} — margin-aware | SL ${INITIAL_SL_PIPS}p | MOMENTUM EXIT`);")

# Replace the tick manager with the requested 1-minute momentum exit logic.
start = s.index("async function onTick(mid,bid,ask,previous){")
end = s.index("function startForegroundService", start)
newtick = """async function onTick(mid,bid,ask,previous){
  reconcile();
  if(Number.isNaN(previous)){setStatus('Streaming XAUUSD — building direction model');return;}
  const positions=ownedPositions();
  if(positions.length){
    const heldSide=sideOf(positions[0]);
    const pip=brokerPipSize();
    const current=heldSide==='BUY'?bid:ask;
    const avgEntry=positions.reduce((sum,p)=>sum+(Number(p.openPrice)||current),0)/Math.max(1,positions.length);
    const pnlPips=heldSide==='BUY'?(current-avgEntry)/pip:(avgEntry-current)/pip;
    const deltaSum=momentumDeltas.slice(-MOMENTUM_WINDOW).reduce((a,b)=>a+b,0);
    const favorableMomentum=heldSide==='BUY'?deltaSum>0:deltaSum<0;
    const adverseMomentum=heldSide==='BUY'?deltaSum<0:deltaSum>0;
    if(pnlPips>=PROFIT_MANAGEMENT_PIPS){
      if(favorableMomentum)setStatus(`PROFIT ${pnlPips.toFixed(0)}p — ${heldSide} momentum growing | HOLD`);
      else{await closeOurs(`+${pnlPips.toFixed(0)}p — 1m momentum faded`);reversalCounts.clear();return;}
    }else if(pnlPips<=-ADVERSE_MOMENTUM_PIPS){
      if(adverseMomentum){await closeOurs(`${pnlPips.toFixed(0)}p — 1m adverse momentum growing`);reversalCounts.clear();return;}
      else setStatus(`DRAW ${pnlPips.toFixed(0)}p — momentum may recover | HOLD`);
    }else setStatus(`HOLDING ${positions.length}/${MAX_POSITIONS} ${heldSide} | ${pnlPips.toFixed(0)}p | SL ${INITIAL_SL_PIPS}p | MOMENTUM EXIT`);
    if(positions.length>=MAX_POSITIONS)return;
  }
  const signal=directionSignal();
  if(!signal.side){if(!positions.length)setStatus(`WAITING — building direction | samples ${priceHistory.length}/${SLOW_EMA+2}`);return;}
  if(positions.length&&positions.some(p=>sideOf(p)!==signal.side))return;
  await enter(signal.side,bid,ask);
}
"""
s = s[:start] + newtick + s[end:]

# --- Persistent MetaApi connection -------------------------------------------------
# Replace connectSdk with a reconnect-safe implementation. Credentials remain in
# localStorage until the explicit CHANGE action clears them.
connect_pattern = re.compile(r"async function connectSdk\(\)\{.*?\nfunction ownedPositions\(\)", re.S)
connect_impl = r'''let reconnectTimer=null;
let reconnectAttempt=0;
let intentionalDisconnect=false;

function storedCredentials(){
  return {
    token:cleanToken(localStorage.getItem('metaapi.token')),
    accountId:String(localStorage.getItem('metaapi.accountId')||'').trim()
  };
}

function scheduleReconnect(){
  if(intentionalDisconnect||reconnectTimer||connecting)return;
  const creds=storedCredentials();
  if(!creds.token||!validAccountId(creds.accountId))return;
  const delay=Math.min(15000,Math.max(2000,2000*Math.pow(1.5,reconnectAttempt++)));
  reconnectTimer=setTimeout(()=>{reconnectTimer=null;void connectSdk(true);},delay);
  setStatus('MetaApi connection lost — auto-reconnecting…');
}

async function connectSdk(isReconnect=false){
  if(connecting||connection)return;
  const stored=storedCredentials();
  const token=cleanToken(ui.token.value)&&cleanToken(ui.token.value)!=='SAVED TOKEN'?cleanToken(ui.token.value):stored.token;
  const accountId=ui.account.value.trim()||stored.accountId;
  if(!token||token==='SAVED TOKEN'||!accountId||!validAccountId(accountId)){
    if(!isReconnect)setStatus('MetaAPI credentials not configured');
    return;
  }
  localStorage.setItem('metaapi.token',token);
  localStorage.setItem('metaapi.accountId',accountId);
  intentionalDisconnect=false;
  connecting=true;
  setStatus(isReconnect?'Reconnecting MetaApi…':'Connecting MetaApi…');
  try{
    const MetaApiClass=sdkConstructor();
    api=new MetaApiClass(token);
    account=await api.metatraderAccountApi.getAccount(accountId);
    if(!account?.id)throw new Error('MetaApi account not found');
    if(typeof account.waitConnected==='function')await account.waitConnected();
    connection=account.getStreamingConnection();
    listener=new BotListener();
    connection.addSynchronizationListener(listener);
    await connection.connect();
    await connection.waitSynchronized();
    synchronized=true;
    reconnectAttempt=0;
    await connection.subscribeToMarketData(SYMBOL);
    reconcile();
    setStatus('CONNECTED — XAUUSD live stream active');
  }catch(e){
    const msg=e?.message||String(e);
    try{await connection?.close();}catch(_){}
    try{await api?.close();}catch(_){}
    connection=null;account=null;api=null;synchronized=false;
    setStatus(`MetaApi unavailable — retrying automatically`);
    scheduleReconnect();
  }finally{connecting=false;}
}

function ownedPositions()'''
s2, n = connect_pattern.subn(connect_impl, s, count=1)
if n != 1:
    raise RuntimeError('connectSdk replacement failed')
s = s2

# Make listener disconnects recover automatically without requiring new credentials.
s = s.replace("onDisconnected(){synchronized=false;setStatus('MetaApi disconnected — waiting to reconnect…');}", "onDisconnected(){synchronized=false;setStatus('MetaApi connection lost — reconnecting automatically…');scheduleReconnect();}")

# Explicit credential change is the ONLY path that clears saved keys.
change_pattern = re.compile(r"function changeCredentials\(\)\{.*?\n", re.S)
change_impl = """function changeCredentials(){\n  trading=false;\n  intentionalDisconnect=true;\n  if(reconnectTimer){clearTimeout(reconnectTimer);reconnectTimer=null;}\n  localStorage.removeItem('metaapi.token');\n  localStorage.removeItem('metaapi.accountId');\n  try{connection?.close();}catch(_){}\n  try{api?.close();}catch(_){}\n  connection=null;account=null;api=null;synchronized=false;listener=null;\n  ui.token.disabled=false;ui.token.value='';ui.account.value='';\n  priceHistory.length=0;momentumDeltas.length=0;directionCandidate='';directionConfirmations=0;\n  setStatus('Credentials cleared — enter new MetaApi keys');\n}\n"""
s2, n = change_pattern.subn(change_impl, s, count=1)
if n != 1:
    raise RuntimeError('changeCredentials replacement failed')
s = s2

# Replace the old credential saver if present so SAVE always persists before connecting.
s = re.sub(r"function saveCredentials\(\)\{.*?\nfunction changeCredentials", """function saveCredentials(){\n  const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();\n  if(!token||token==='SAVED TOKEN'){setStatus('Enter a valid MetaAPI token');return;}\n  if(!validAccountId(accountId)){setStatus('Enter a valid MetaAPI account ID');return;}\n  localStorage.setItem('metaapi.token',token);\n  localStorage.setItem('metaapi.accountId',accountId);\n  ui.token.value='SAVED TOKEN';\n  ui.token.disabled=true;\n  void connectSdk(false);\n}\nfunction changeCredentials""", s, count=1, flags=re.S)

# Persist connection across app stop/restart and recover after network restoration.
s += r'''

// Persistent session bootstrap. STOP only stops trading; it does not erase or
// intentionally disconnect the MetaApi session. If Android recreates the WebView,
// these stored credentials reconnect automatically without asking the user again.
function restoreSavedMetaApiSession(){
  const creds=storedCredentials();
  if(!creds.token||!validAccountId(creds.accountId))return;
  ui.token.value='SAVED TOKEN';
  ui.token.disabled=true;
  ui.account.value=creds.accountId;
  void connectSdk(false);
}

window.addEventListener('online',()=>{if(!connection&&!connecting)void connectSdk(true);});
window.addEventListener('focus',()=>{if(!connection&&!connecting)void connectSdk(true);});
setInterval(()=>{
  if(!connection&&!connecting) scheduleReconnect();
  else if(connection&&synchronized) {
    // Keep the engine state explicitly connected even while the bot is stopped.
    const text=String(ui.status.textContent||'');
    if(!trading && (/stopped|not connected|reconnect/i.test(text))) setStatus('CONNECTED — engine idle (bot stopped)');
  }
},5000);
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',restoreSavedMetaApiSession,{once:true});
else restoreSavedMetaApiSession();
'''

p.write_text(s)
