from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

# The stop itself opens the opposite position at the broker. The old position
# must then be closed immediately, with no timer-based reaction. Keep the
# close call on the same event/tick turn; broker/network latency is outside
# the app's control, so a literal 0.1 ms network guarantee is impossible.

old_reconcile = re.search(r"async function reconcileOppositeTrails\(bid,ask\)\{.*?\n\}", s, re.S)
if not old_reconcile:
    raise SystemExit('Expected reconcileOppositeTrails function not found')
new_reconcile = r'''async function reconcileOppositeTrails(bid,ask){
 const positions=ownedPositions();
 const ids=new Set(positions.map(idOf));
 for(const [positionId,state] of [...oppositeTrailOrders.entries()]){
  if(!ids.has(positionId)){await cancelTrailOrder(state?.orderId);oppositeTrailOrders.delete(positionId);}
 }
 // First detect an already-crossed mapped stop. This path performs the close
 // in the same tick with no setTimeout/setInterval delay.
 for(const position of positions){
  const positionId=idOf(position),state=oppositeTrailOrders.get(positionId);if(!state?.orderId)continue;
  const side=sideOf(position),target=Number(state.price);if(!Number.isFinite(target))continue;
  const crossed=side==='BUY'?Number(bid)<=target:side==='SELL'?Number(ask)>=target:false;
  if(crossed){void handleTriggeredTrail({id:state.orderId,orderId:state.orderId});}
 }
 // Maintain exactly one mapped stop for every surviving position.
 for(const position of positions)await ensureOppositeTrail(position,bid,ask);
}'''
s = s[:old_reconcile.start()] + new_reconcile + s[old_reconcile.end():]

# Replace any listener variants after the build transforms. Do not depend on
# one exact formatting/signature because other workflow scripts may rewrite it.
listener_re = re.compile(r"\s*onOrderUpdated\([^\n]*\)\{.*?\}\s*\n\s*onOrderCompleted\([^\n]*\)\{.*?\}", re.S)
if not listener_re.search(s):
    # Also accept the original no-argument callback form.
    listener_re = re.compile(r"\s*onOrderUpdated\([^\n]*\)\{.*?\}\s*\n\s*onOrderCompleted\(\)\{.*?\}", re.S)
if not listener_re.search(s):
    raise SystemExit('Expected order listener block not found')
new_listener = r'''
 onOrderUpdated(instanceIndex,order){
  if(order?.symbol===SYMBOL){
   const state=String(order?.state??order?.currentState??order?.status??'').toUpperCase();
   if(state==='COMPLETED'||state==='FILLED'||state==='EXECUTED')void handleTriggeredTrail(order);
   reconcile();
  }
 }
 onOrderCompleted(instanceIndex,order){void handleTriggeredTrail(order);reconcile();}'''
s = listener_re.sub(new_listener, s, count=1)

# Strengthen the trigger handler: mark the mapping consumed first, then issue
# the broker close immediately. Never wait for a timer and never close the new
# opposite position by mistake.
handler_re = re.compile(r"async function handleTriggeredTrail\(order\)\{.*?\n\}", re.S)
if not handler_re.search(s):
    raise SystemExit('Expected handleTriggeredTrail function not found')
new_handler = r'''async function handleTriggeredTrail(order){
 const oid=orderIdOf(order);if(!oid||triggeredTrailOrders.has(oid))return;
 let sourceId='';for(const [positionId,state] of oppositeTrailOrders.entries()){if(state?.orderId===oid){sourceId=positionId;break;}}
 if(!sourceId)return;
 triggeredTrailOrders.add(oid);const state=oppositeTrailOrders.get(sourceId);oppositeTrailOrders.delete(sourceId);trailPending.delete(sourceId);
 const source=ownedPositions().find(p=>idOf(p)===sourceId);
 if(!source)return;
 // No intentional delay: send the close immediately on the trigger event.
 try{await connection.closePosition(sourceId);setStatus(`REVERSE ${sourceId.slice(-6)} — old ${sideOf(source)} closed immediately`);}
 catch(e){setStatus(`REVERSE CLOSE ${sourceId.slice(-6)} failed — ${e?.message||e}`);}
}'''
s = handler_re.sub(new_handler, s, count=1)

p.write_text(s)
