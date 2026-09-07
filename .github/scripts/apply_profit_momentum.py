from pathlib import Path

p = Path('web/main.js')
s = p.read_text()

# Replace all previous fixed/dynamic profit exits with a per-position opposite
# stop trail. The stop is 100 pips behind the current favorable price, moves only
# in the favorable direction, and becomes the stop for the newly triggered trade.
s = s.replace("const INITIAL_SL_PIPS=100;\nconst TAKE_PROFIT_PIPS=200;", "const OPPOSITE_STOP_TRAIL_PIPS=100;")
s = s.replace("const INITIAL_SL_PIPS=200;\nconst PROFIT_MANAGEMENT_PIPS=100;\nconst ADVERSE_MOMENTUM_PIPS=100;", "const OPPOSITE_STOP_TRAIL_PIPS=100;")
s = s.replace("const CANDLE_MS=300000;", "const CANDLE_MS=60000;")
s = s.replace("const CANDLE_MS=60000;", "const CANDLE_MS=60000;")

# Per-position state. Every live position gets its own pending opposite stop and
# its own best trail price. No averaging across positions is used.
marker = "let directionConfirmations=0;\n"
insert = """
const oppositeTrailOrders=new Map();
const triggeredTrailOrders=new Set();

function oppositeSide(side){return side==='BUY'?'SELL':side==='SELL'?'BUY':'';}
function oppositeTrailPrice(side,bid,ask){
  const pip=brokerPipSize();
  if(!Number.isFinite(pip)||pip<=0)return NaN;
  return normalizePrice(side==='BUY'?Number(bid)-OPPOSITE_STOP_TRAIL_PIPS*pip:Number(ask)+OPPOSITE_STOP_TRAIL_PIPS*pip);
}
function orderIdOf(x){return String(x?.id??x?.orderId??'');}
function pendingOrders(){return(connection?.terminalState?.orders||[]).filter(x=>x?.symbol===SYMBOL);}

async function cancelTrailOrder(orderId){
  if(!orderId||!connection)return;
  try{await connection.cancelOrder(orderId);}catch(e){}
}

async function ensureOppositeTrail(position,bid,ask){
  const positionId=idOf(position),side=sideOf(position),volume=volumeOf(position);
  if(!positionId||!side||!Number.isFinite(volume)||volume<=0||!connection)return;
  const target=oppositeTrailPrice(side,bid,ask);
  if(!Number.isFinite(target))return;
  const state=oppositeTrailOrders.get(positionId);
  if(state?.orderId){
    const current=Number(state.price);
    const improves=side==='BUY'?target>current:target<current;
    if(!improves)return;
    try{
      await connection.modifyOrder(state.orderId,target,undefined);
      state.price=target;
      state.side=side;
      oppositeTrailOrders.set(positionId,state);
      setStatus(`TRAIL ${side} ${positionId.slice(-6)} — opposite stop ${target}`);
    }catch(e){
      // If the broker says the order no longer exists, recreate it below.
      const msg=String(e?.message||e);
      if(/not found|unknown order|does not exist|invalid order/i.test(msg)){
        oppositeTrailOrders.delete(positionId);
      }else{
        setStatus(`TRAIL MODIFY ${side} failed — ${msg}`);
        return;
      }
    }
  }
  if(oppositeTrailOrders.has(positionId))return;

  const opposite=oppositeSide(side);
  try{
    let order;
    // No magic/clientId/options are supplied so manualTrades accounts remain
    // compatible. The pending stop opens the opposite trade when triggered.
    if(opposite==='BUY') order=await connection.createStopBuyOrder(SYMBOL,volume,target);
    else order=await connection.createStopSellOrder(SYMBOL,volume,target);
    const oid=orderIdOf(order);
    if(!oid)throw new Error('broker did not return opposite-stop order id');
    oppositeTrailOrders.set(positionId,{orderId:oid,price:target,side});
    setStatus(`TRAIL ${side} ${positionId.slice(-6)} — ${opposite} stop ${target} active`);
  }catch(e){
    setStatus(`TRAIL ${side} failed — ${e?.message||e}`);
  }
}

async function handleTriggeredTrail(order){
  const oid=orderIdOf(order);
  if(!oid||triggeredTrailOrders.has(oid))return;
  let sourceId='';
  for(const [positionId,state] of oppositeTrailOrders.entries()){
    if(state?.orderId===oid){sourceId=positionId;break;}
  }
  if(!sourceId)return;
  triggeredTrailOrders.add(oid);
  oppositeTrailOrders.delete(sourceId);
  const source=ownedPositions().find(p=>idOf(p)===sourceId);
  // The opposite stop has already become the new running trade. Close only the
  // position that owned this stop; do not touch other independent positions.
  if(source){
    try{
      await connection.closePosition(sourceId);
      setStatus(`REVERSE ${sourceId.slice(-6)} — old ${sideOf(source)} closed; opposite stop is now running`);
    }catch(e){
      setStatus(`REVERSE CLOSE ${sourceId.slice(-6)} failed — ${e?.message||e}`);
    }
  }
}

async function reconcileOppositeTrails(bid,ask){
  const positions=ownedPositions();
  const ids=new Set(positions.map(idOf));
  for(const [positionId,state] of [...oppositeTrailOrders.entries()]){
    if(!ids.has(positionId)){
      await cancelTrailOrder(state?.orderId);
      oppositeTrailOrders.delete(positionId);
    }
  }
  for(const position of positions)await ensureOppositeTrail(position,bid,ask);
}
"""
if marker in s and 'const oppositeTrailOrders=new Map();' not in s:
    s=s.replace(marker,marker+insert)

# Remove the old per-position momentum/fixed-TP onTick and replace it with the
# opposite-stop loop. The trail is updated on every price event, independently
# for every position. A triggered stop creates the opposite running position;
# the completed-order callback then closes only its predecessor.
start=s.index("async function onTick(mid,bid,ask,previous){")
end=s.index("function startForegroundService",start)
newtick="""async function onTick(mid,bid,ask,previous){
  reconcile();
  if(Number.isNaN(previous)){setStatus('Streaming XAUUSD — opposite-stop trail armed when positions open');return;}

  const positions=ownedPositions();
  if(positions.length){
    await reconcileOppositeTrails(bid,ask);
    // Do not run the previous displacement TP, +100 profit exit, or -100
    // adverse-momentum exit. The independent 100-pip opposite stop is now the
    // complete running exit/reversal mechanism.
    if(ownedPositions().length>=MAX_POSITIONS)return;
  }

  const remaining=ownedPositions();
  const signal=directionSignal();
  if(!signal.side){
    if(!remaining.length)setStatus(`WAITING — building direction | samples ${priceHistory.length}/${SLOW_EMA+2}`);
    return;
  }
  if(remaining.length&&remaining.some(p=>sideOf(p)!==signal.side))return;
  await enter(signal.side,bid,ask);
}
"""
s=s[:start]+newtick+s[end:]

# initialStop is retained only for compatibility with older helper code. The new
# entry flow must not attach a fixed SL because the opposite pending stop is the
# sole exit/reversal mechanism.
s=s.replace("function initialStop(side,price){const pip=brokerPipSize(),base=Number(price);if(!Number.isFinite(base)||base<=0)return undefined;return normalizePrice(side==='BUY'?base-INITIAL_SL_PIPS*pip:base+INITIAL_SL_PIPS*pip);}", "function initialStop(){return undefined;}")

# Remove any fixed TP arguments left by older entry code.
s=s.replace(",stopLoss,normalizePrice(reference+TAKE_PROFIT_PIPS*brokerPipSize()),options", ",undefined,undefined,options")
s=s.replace(",stopLoss,normalizePrice(reference-TAKE_PROFIT_PIPS*brokerPipSize()),options", ",undefined,undefined,options")

# Listener: a completed pending stop is the reversal event. Handle it before
# reconciliation so the predecessor can be closed immediately.
s=s.replace("onOrderCompleted(){reconcile();}", "onOrderCompleted(instanceIndex,order){void handleTriggeredTrail(order);reconcile();}")

# Update stale status text referring to the previous fixed 200-pip SL.
s=s.replace("SL ${INITIAL_SL_PIPS}p | MOMENTUM EXIT", "100p OPPOSITE TRAIL")
s=s.replace("MOMENTUM EXIT", "100p OPPOSITE TRAIL")

p.write_text(s)
"