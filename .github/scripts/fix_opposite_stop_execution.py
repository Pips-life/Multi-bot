from pathlib import Path

p = Path('web/main.js')
s = p.read_text()

# The broker stop must remain one-per-position, but the old implementation
# relied only on onOrderCompleted. Add a tick-side trigger fallback and order
# update handling so the superseded position is closed even when the broker
# streaming callback does not emit a completed-order event.
old = '''async function reconcileOppositeTrails(bid,ask){const positions=ownedPositions();const ids=new Set(positions.map(idOf));for(const [positionId,state] of [...oppositeTrailOrders.entries()]){if(!ids.has(positionId)){await cancelTrailOrder(state?.orderId);oppositeTrailOrders.delete(positionId);}}for(const position of positions)await ensureOppositeTrail(position,bid,ask);}'''
new = '''async function reconcileOppositeTrails(bid,ask){
 const positions=ownedPositions();
 const ids=new Set(positions.map(idOf));
 for(const [positionId,state] of [...oppositeTrailOrders.entries()]){
  if(!ids.has(positionId)){await cancelTrailOrder(state?.orderId);oppositeTrailOrders.delete(positionId);}
 }
 for(const position of positions)await ensureOppositeTrail(position,bid,ask);
 // Fallback: if price reaches the mapped stop level, close only that source
 // position immediately. The broker stop is already at the same level and
 // performs the opposite-side entry; this path covers missing completion events.
 for(const position of positions){
  const positionId=idOf(position),state=oppositeTrailOrders.get(positionId);if(!state||!state.orderId)continue;
  const side=sideOf(position),target=Number(state.price);if(!Number.isFinite(target))continue;
  const crossed=side==='BUY'?Number(bid)<=target:side==='SELL'?Number(ask)>=target:false;
  if(crossed)void handleTriggeredTrail({id:state.orderId,orderId:state.orderId});
 }
}'''
if old not in s: raise SystemExit('Expected reconcileOppositeTrails block not found')
s=s.replace(old,new)

old_listener = '''onOrderUpdated(instanceIndex,order){if(order?.symbol===SYMBOL)reconcile();}
onOrderCompleted(instanceIndex,order){void handleTriggeredTrail(order);reconcile();}'''
new_listener = '''onOrderUpdated(instanceIndex,order){if(order?.symbol===SYMBOL){if(order?.state==='COMPLETED'||order?.currentState==='COMPLETED'||order?.status==='COMPLETED')void handleTriggeredTrail(order);reconcile();}}
onOrderCompleted(instanceIndex,order){void handleTriggeredTrail(order);reconcile();}'''
if old_listener not in s: raise SystemExit('Expected order listener block not found')
s=s.replace(old_listener,new_listener)

# Retry stop creation briefly. This handles transient broker/API rejection without
# allowing duplicate orders because trailPending remains set for the whole retry.
old_create = '''const opposite=oppositeSide(side);trailPending.add(positionId);try{let order;if(opposite==='BUY')order=await connection.createStopBuyOrder(SYMBOL,volume,target);else order=await connection.createStopSellOrder(SYMBOL,volume,target);const oid=orderIdOf(order);if(!oid)throw new Error('broker did not return opposite-stop order id');oppositeTrailOrders.set(positionId,{orderId:oid,price:target,side});setStatus(`TRAIL ${side} ${positionId.slice(-6)} — ${opposite} stop ${target} active`);}catch(e){setStatus(`TRAIL ${side} failed — ${e?.message||e}`)}finally{trailPending.delete(positionId);}'''
new_create = '''const opposite=oppositeSide(side);trailPending.add(positionId);let lastError=null;try{for(let attempt=1;attempt<=3;attempt++){try{let order;if(opposite==='BUY')order=await connection.createStopBuyOrder(SYMBOL,volume,target);else order=await connection.createStopSellOrder(SYMBOL,volume,target);const oid=orderIdOf(order);if(!oid)throw new Error('broker did not return opposite-stop order id');oppositeTrailOrders.set(positionId,{orderId:oid,price:target,side});setStatus(`TRAIL ${side} ${positionId.slice(-6)} — ${opposite} stop ${target} active`);lastError=null;break;}catch(e){lastError=e;if(attempt<3)await new Promise(r=>setTimeout(r,100*attempt));}}if(lastError)setStatus(`TRAIL ${side} failed after 3 attempts — ${lastError?.message||lastError}`);}finally{trailPending.delete(positionId);}'''
if old_create not in s: raise SystemExit('Expected create block not found')
s=s.replace(old_create,new_create)

p.write_text(s)
