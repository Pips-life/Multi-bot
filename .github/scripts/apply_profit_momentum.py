from pathlib import Path

p = Path('web/main.js')
s = p.read_text()

# FINAL TRADING MANAGEMENT: per-position 100-pip opposite-stop trail.
# The stop order itself performs the broker-side reversal; completion handling
# closes the superseded position immediately with no intentional timer delay.
s = s.replace("const INITIAL_SL_PIPS=100;\nconst TAKE_PROFIT_PIPS=200;", "const OPPOSITE_STOP_TRAIL_PIPS=100;")
s = s.replace("const INITIAL_SL_PIPS=200;\nconst PROFIT_MANAGEMENT_PIPS=100;\nconst ADVERSE_MOMENTUM_PIPS=100;", "const OPPOSITE_STOP_TRAIL_PIPS=100;")
s = s.replace("const CANDLE_MS=300000;", "const CANDLE_MS=60000;")

marker = "let directionConfirmations=0;\n"
insert = r'''const oppositeTrailOrders=new Map();
const triggeredTrailOrders=new Set();
const trailPending=new Set();
function oppositeSide(side){return side==='BUY'?'SELL':side==='SELL'?'BUY':'';}
function oppositeTrailPrice(side,bid,ask){const pip=brokerPipSize();if(!Number.isFinite(pip)||pip<=0)return NaN;return normalizePrice(side==='BUY'?Number(bid)-OPPOSITE_STOP_TRAIL_PIPS*pip:Number(ask)+OPPOSITE_STOP_TRAIL_PIPS*pip);}
function orderIdOf(x){return String(x?.id??x?.orderId??'');}
async function cancelTrailOrder(orderId){if(!orderId||!connection)return;try{await connection.cancelOrder(orderId);}catch(e){}}
async function ensureOppositeTrail(position,bid,ask){
 const positionId=idOf(position),side=sideOf(position),volume=volumeOf(position);if(!positionId||!side||!Number.isFinite(volume)||volume<=0||!connection)return;
 const target=oppositeTrailPrice(side,bid,ask);if(!Number.isFinite(target))return;
 const state=oppositeTrailOrders.get(positionId);
 if(state?.orderId){const current=Number(state.price);const improves=side==='BUY'?target>current:target<current;if(!improves)return;try{await connection.modifyOrder(state.orderId,target,undefined);state.price=target;oppositeTrailOrders.set(positionId,state);}catch(e){const msg=String(e?.message||e);if(/not found|unknown order|does not exist|invalid order/i.test(msg))oppositeTrailOrders.delete(positionId);else return;}}
 if(oppositeTrailOrders.has(positionId)||trailPending.has(positionId))return;
 const opposite=oppositeSide(side);trailPending.add(positionId);try{let order;if(opposite==='BUY')order=await connection.createStopBuyOrder(SYMBOL,volume,target);else order=await connection.createStopSellOrder(SYMBOL,volume,target);const oid=orderIdOf(order);if(!oid)throw new Error('broker did not return opposite-stop order id');oppositeTrailOrders.set(positionId,{orderId:oid,price:target,side});setStatus(`TRAIL ${side} ${positionId.slice(-6)} — ${opposite} stop ${target} active`);}catch(e){setStatus(`TRAIL ${side} failed — ${e?.message||e}`);}finally{trailPending.delete(positionId);}
}
async function handleTriggeredTrail(order){
 const oid=orderIdOf(order);if(!oid||triggeredTrailOrders.has(oid))return;let sourceId='';for(const [positionId,state] of oppositeTrailOrders.entries()){if(state?.orderId===oid){sourceId=positionId;break;}}if(!sourceId)return;triggeredTrailOrders.add(oid);oppositeTrailOrders.delete(sourceId);trailPending.delete(sourceId);const source=ownedPositions().find(p=>idOf(p)===sourceId);if(source){try{await connection.closePosition(sourceId);setStatus(`REVERSE ${sourceId.slice(-6)} — old ${sideOf(source)} closed immediately`);}catch(e){setStatus(`REVERSE CLOSE ${sourceId.slice(-6)} failed — ${e?.message||e}`);}}}
async function reconcileOppositeTrails(bid,ask){const positions=ownedPositions();const ids=new Set(positions.map(idOf));for(const [positionId,state] of [...oppositeTrailOrders.entries()]){if(!ids.has(positionId)){await cancelTrailOrder(state?.orderId);oppositeTrailOrders.delete(positionId);}}for(const position of positions)await ensureOppositeTrail(position,bid,ask);}
'''
if marker in s and 'const oppositeTrailOrders=new Map();' not in s:s=s.replace(marker,marker+insert)

start=s.index("async function onTick(mid,bid,ask,previous){")
end=s.index("function startForegroundService",start)
newtick=r'''async function onTick(mid,bid,ask,previous){
 reconcile();
 if(Number.isNaN(previous)){setStatus('Streaming XAUUSD — opposite-stop trail armed when positions open');return;}
 const positions=ownedPositions();
 if(positions.length){await reconcileOppositeTrails(bid,ask);if(ownedPositions().length>=MAX_POSITIONS)return;}
 const remaining=ownedPositions();const signal=directionSignal();
 if(!signal.side){if(!remaining.length)setStatus(`WAITING — building direction | samples ${priceHistory.length}/${SLOW_EMA+2}`);return;}
 if(remaining.length&&remaining.some(p=>sideOf(p)!==signal.side))return;
 await enter(signal.side,bid,ask);
}
'''
s=s[:start]+newtick+s[end:]

s=s.replace("function initialStop(side,price){const pip=brokerPipSize(),base=Number(price);if(!Number.isFinite(base)||base<=0)return undefined;return normalizePrice(side==='BUY'?base-INITIAL_SL_PIPS*pip:base+INITIAL_SL_PIPS*pip);}", "function initialStop(){return undefined;}")
s=s.replace(",stopLoss,normalizePrice(reference+TAKE_PROFIT_PIPS*brokerPipSize()),options", ",undefined,undefined,options")
s=s.replace(",stopLoss,normalizePrice(reference-TAKE_PROFIT_PIPS*brokerPipSize()),options", ",undefined,undefined,options")
s=s.replace("onOrderCompleted(){reconcile();}", "onOrderCompleted(instanceIndex,order){void handleTriggeredTrail(order);reconcile();}")
s=s.replace("SL ${INITIAL_SL_PIPS}p | MOMENTUM EXIT", "100p OPPOSITE TRAIL")
s=s.replace("MOMENTUM EXIT", "100p OPPOSITE TRAIL")
p.write_text(s)

import subprocess
subprocess.run(['python3','.github/scripts/fix_opposite_stop_execution.py'],check=True)
