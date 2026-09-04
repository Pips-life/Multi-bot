from pathlib import Path

# Build-time guard + repair for the canonical Pips-life Multi-bot engine.
# MetaApi can reject a market entry when an attached SL is momentarily outside
# the broker's current validation constraints. Enter immediately, then attach
# the 70-pip SL using the synchronized live position. This preserves instant
# velocity execution while preventing entry validation from blocking the trade.
p = Path('web/main.js')
s = p.read_text(encoding='utf-8')

old = '''async function enter(side,spot){
  if(entryInFlight||currentPosition||!connection||!trading||stopRequested||!synchronized)return;
  const volume=currentVolume(),pipSize=brokerPipSize(),initialStop=stopCandidate(side,Number(spot),pipSize);
  if(volume<=0){setStatus('Cannot size trade: invalid XAUUSD execution volume');return;}
  if(!Number.isFinite(initialStop)||initialStop<=0){setStatus('Cannot calculate 70-pip stop');return;}
  entryInFlight=true;
  try{
    const options=tradeOptions(side);
    if(stopRequested||!trading)return;
    if(side==='BUY')await connection.createMarketBuyOrder(SYMBOL,volume,initialStop,undefined,options);
    else await connection.createMarketSellOrder(SYMBOL,volume,initialStop,undefined,options);
    if(stopRequested||!trading){await reconcile();if(currentPosition)await closePositionSafe(currentPosition);return;}
    lastDirection=side;setStatus(`OPEN ${side} ${volume} — INSTANT VELOCITY — SL ${fmt(initialStop)}`);
    await waitForPosition(side,3000);await reconcile();
  }catch(e){
    if(!stopRequested)setStatus(`Entry failed: ${e?.message||e}`);
  }finally{entryInFlight=false;}
}'''

new = '''async function enter(side,spot){
  if(entryInFlight||currentPosition||!connection||!trading||stopRequested||!synchronized)return;
  const volume=currentVolume();
  if(volume<=0){setStatus('ENTRY BLOCKED — invalid XAUUSD execution volume');return;}
  if(!Number.isFinite(Number(spot))||Number(spot)<=0){setStatus('ENTRY BLOCKED — invalid live XAUUSD price');return;}
  entryInFlight=true;
  try{
    const options=tradeOptions(side);
    if(stopRequested||!trading)return;

    // Execute the market order first. Do not attach the SL to the entry request:
    // this avoids broker-side entry validation rejecting an otherwise valid
    // instant market entry because the quote/stop distance changed by a tick.
    if(side==='BUY')await connection.createMarketBuyOrder(SYMBOL,volume,undefined,undefined,options);
    else await connection.createMarketSellOrder(SYMBOL,volume,undefined,undefined,options);

    if(stopRequested||!trading){await reconcile();if(currentPosition)await closePositionSafe(currentPosition);return;}
    lastDirection=side;setStatus(`OPEN ${side} ${volume} — INSTANT VELOCITY — applying 70-pip SL`);

    const position=await waitForPosition(side,3000);
    await reconcile();
    if(position&&trading&&!stopRequested)await setInitialStop(position);
  }catch(e){
    if(!stopRequested)setStatus(`Entry failed: ${e?.message||e}`);
  }finally{entryInFlight=false;}
}'''

if old in s:
    s = s.replace(old, new, 1)
elif new not in s:
    raise SystemExit('Canonical entry function not found; refusing to build a mismatched engine')

required = [
    "const TRAIL_PIPS=70;",
    "async function onTick(mid,bid,ask)",
    "async function enter(side,spot)",
    "createMarketBuyOrder(SYMBOL,volume,undefined,undefined,options)",
    "createMarketSellOrder(SYMBOL,volume,undefined,undefined,options)",
    "async function setInitialStop(position)",
    "function stopAllTrading()",
    "stopRequested=true;trading=false;",
    "await Promise.all(positions.map(p=>closePositionSafe(p)))",
]
missing=[x for x in required if x not in s]
if missing:
    raise SystemExit('Canonical Pips-life execution source validation failed: ' + ', '.join(missing))

p.write_text(s, encoding='utf-8')
print('Pips-life entry validation repair applied: market entry is immediate; 70-pip SL is attached after fill.')
