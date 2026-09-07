from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

new_listener = r'''class BotListener extends SynchronizationListener{
 onConnected(){
  if(!synchronized)setStatus('MetaApi connected — initial synchronization…');
 }
 onDisconnected(){
  synchronized=false;
  setStatus('MetaApi disconnected — waiting to reconnect…');
 }
 onSynchronizationStarted(){
  // MetaApi can resynchronize its terminal while the live price stream remains healthy.
  // Do not demote an already-live engine back to "Synchronizing" and do not pause trading.
  if(!synchronized)setStatus('Synchronizing MetaApi terminal…');
 }
 onSynchronizationFinished(){
  synchronized=true;
  setStatus('CONNECTED — XAUUSD live stream active');
  reconcile();
 }
 onSymbolPricesUpdated(instanceIndex,prices){
  const p=Array.isArray(prices)?prices.find(x=>x?.symbol===SYMBOL):(prices?.symbol===SYMBOL?prices:null);
  if(!p)return;
  const bid=Number(p.bid),ask=Number(p.ask);
  if(!Number.isFinite(bid)||!Number.isFinite(ask)||bid<=0||ask<=0||ask<bid)return;
  const mid=(bid+ask)/2,previous=lastMid;
  lastMid=mid;
  updateCandle(mid,previous);
  priceHistory.push({mid,bid,ask,time:Date.now()});
  if(priceHistory.length>HISTORY_SIZE)priceHistory.shift();
  ui.price.textContent=fmt(mid);
  updateProfitLossUI();
  if(trading&&synchronized)void onTick(mid,bid,ask,previous);
 }
 onPositionUpdated(instanceIndex,position){if(position?.symbol===SYMBOL)reconcile();}
 onPositionRemoved(){reconcile();}
 onOrderUpdated(instanceIndex,order){if(order?.symbol===SYMBOL)reconcile();}
 onOrderCompleted(){reconcile();}
 onOrderFailed(instanceIndex,orderId,error){setStatus(`Order failed: ${error?.message||error}`);reconcile();}
}
'''

pattern = r'class BotListener extends SynchronizationListener\{.*?\n\}\nasync function connectSdk\(\)'
replacement = new_listener + 'async function connectSdk()'
updated, count = re.subn(pattern, replacement, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('Could not locate BotListener block; refusing to modify source')
p.write_text(updated)
print('Stabilized MetaApi synchronization status handling')
