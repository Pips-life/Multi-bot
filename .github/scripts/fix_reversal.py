from pathlib import Path
import re

path = Path('web/main.js')
s = path.read_text()

new_reconcile = r'''function reconcile(){
  if(!connection?.terminalState)return;
  const state=connection.terminalState;
  const positions=(state.positions||[]).filter(isOurs);
  const orders=(state.orders||[]).filter(isOurs);
  const old=currentPosition;

  // A stop order creates the opposite position on hedging accounts. Do not rely
  // on positions[0]: terminal-state ordering is not guaranteed. Detect the
  // newly-created opposite position explicitly and close the old position.
  let next=old&&positions.find(p=>idOf(p)===idOf(old))||null;
  const reversal=old&&positions.find(p=>idOf(p)!==idOf(old)&&sideOf(p)!==sideOf(old));
  if(reversal) next=reversal;
  if(!next&&positions.length) next=positions[0];

  if(old&&next&&idOf(old)!==idOf(next)&&sideOf(old)!==sideOf(next)){
    void handleReversal(old,next,positions);
  }else if(!old&&next){
    currentPosition=next;
  }

  // If the platform has already replaced the position in-place (netting mode),
  // the position id may remain the same while the side changes. Re-arm the
  // opposite stop from the updated position instead of leaving the old stop.
  if(old&&next&&idOf(old)===idOf(next)&&sideOf(old)!==sideOf(next)){
    currentPosition=next;
    currentStop=null;
    void cancelStaleStops(orders,next);
    if(!stopActionInFlight)void placeOppositeStop(next);
  }

  currentPosition=next;
  const stops=orders.filter(o=>String(o.type??'').toUpperCase().includes('STOP'));
  const expected=next?opposite(sideOf(next)):'';
  currentStop=stops.find(o=>sideOf(o)===expected)||null;
  ui.position.textContent=next?sideOf(next):'—';
  const stopPrice=Number(currentStop?.openPrice??currentStop?.currentPrice??0);
  ui.stop.textContent=stopPrice>0?fmt(stopPrice):'—';
  renderPageData();
  if(next&&!currentStop&&!stopActionInFlight)void placeOppositeStop(next);
  if(!next&&stops.length)for(const o of stops)void cancelOrder(idOf(o));
}

async function cancelStaleStops(orders,position){
  const expected=opposite(sideOf(position));
  for(const o of (orders||[]).filter(x=>String(x.type??'').toUpperCase().includes('STOP')&&sideOf(x)!==expected)){
    await cancelOrder(idOf(o));
  }
}
'''

pattern = re.compile(r"function reconcile\(\)\{.*?\n\}\n\nasync function handleReversal", re.S)
if not pattern.search(s):
    raise SystemExit('reconcile block not found')
s = pattern.sub(new_reconcile + "\nasync function handleReversal", s, count=1)

new_reversal = r'''async function handleReversal(oldPosition,newPosition,allPositions=[]){
  if(idOf(oldPosition)===idOf(newPosition))return;
  try{
    // On MT5 hedging, the opposite stop opens a second position; explicitly
    // close the old ticket. If CLOSE_ID is rejected because the broker has
    // already closed it, continue with the new running position.
    const live=(connection?.terminalState?.positions||[]).find(p=>idOf(p)===idOf(oldPosition));
    if(live)await connection.closePosition(idOf(oldPosition));
  }catch(e){
    const msg=String(e?.message||e);
    if(!/not found|does not exist|position.*closed|already.*closed/i.test(msg)){
      setStatus(`Closing previous position failed: ${msg}`);
    }
  }
  currentPosition=newPosition;
  currentStop=null;
  try{await cancelStaleStops(connection?.terminalState?.orders||[],newPosition);}catch(_){}
  await placeOppositeStop(newPosition);
}
'''
pattern2 = re.compile(r"async function handleReversal\(oldPosition,newPosition\)\{.*?\n\}\nfunction tradeOptions", re.S)
if not pattern2.search(s):
    raise SystemExit('handleReversal block not found')
s = pattern2.sub(new_reversal + "function tradeOptions", s, count=1)

path.write_text(s)
print('patched reversal handling')
