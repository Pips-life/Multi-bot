from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

# Per-position risk/exit thresholds.
s = s.replace("const INITIAL_SL_PIPS=100;\nconst TAKE_PROFIT_PIPS=200;", "const INITIAL_SL_PIPS=200;\nconst PROFIT_MANAGEMENT_PIPS=100;\nconst ADVERSE_MOMENTUM_PIPS=100;")
s = s.replace("const CANDLE_MS=300000;", "const CANDLE_MS=60000;")

# Replace onTick with per-position management. Protective SL remains broker-side
# at -200 pips for every filled position; momentum decisions are evaluated against
# each position's own entry price and current side.
start = s.index("async function onTick(mid,bid,ask,previous){")
end = s.index("function startForegroundService", start)
newtick = """async function onTick(mid,bid,ask,previous){
  reconcile();
  if(Number.isNaN(previous)){setStatus('Streaming XAUUSD — building direction model');return;}
  const positions=ownedPositions();
  if(positions.length){
    const pip=brokerPipSize();
    // Evaluate every position independently. Do not average entries: each trade
    // has its own +100/-100 pip decision and its own broker SL.
    for(const position of positions){
      const side=sideOf(position);
      const entry=Number(position.openPrice);
      const current=side==='BUY'?bid:ask;
      if(!side||!Number.isFinite(entry)||!Number.isFinite(current)||!Number.isFinite(pip)||pip<=0)continue;
      const pnlPips=side==='BUY'?(current-entry)/pip:(entry-current)/pip;
      const deltas=momentumDeltas.slice(-MOMENTUM_WINDOW);
      const momentum=deltas.reduce((a,b)=>a+b,0);
      const favorable=side==='BUY'?momentum>0:momentum<0;
      const adverse=side==='BUY'?momentum<0:momentum>0;
      const faded=side==='BUY'?momentum<=0:momentum>=0;

      // +100 pips: keep riding while directional momentum is strong; close
      // quickly on a genuine momentum fade so profit is not given back.
      if(pnlPips>=PROFIT_MANAGEMENT_PIPS){
        if(favorable){
          setStatus(`PROFIT +${pnlPips.toFixed(0)}p ${side} — momentum strong | MAXIMISE`);
        }else if(faded){
          await closePosition(position,`+${pnlPips.toFixed(0)}p — momentum faded`);
        }
        continue;
      }

      // -100 pips: if adverse momentum is growing, exit early. If adverse
      // momentum has faded, hold and allow recovery. The hard -200 pip SL
      // remains the final broker-side protection.
      if(pnlPips<=-ADVERSE_MOMENTUM_PIPS){
        if(adverse){
          await closePosition(position,`${pnlPips.toFixed(0)}p — adverse momentum growing`);
        }else{
          setStatus(`DRAW ${pnlPips.toFixed(0)}p ${side} — adverse momentum faded | HOLD`);
        }
      }
    }
    reconcile();
    if(ownedPositions().length>=MAX_POSITIONS)return;
  }

  const remaining=ownedPositions();
  const signal=directionSignal();
  if(!signal.side){if(!remaining.length)setStatus(`WAITING — building direction | samples ${priceHistory.length}/${SLOW_EMA+2}`);return;}
  if(remaining.length&&remaining.some(p=>sideOf(p)!==signal.side))return;
  await enter(signal.side,bid,ask);
}
"""
s = s[:start] + newtick + s[end:]

# Ensure the entry path starts with a 200-pip protective SL. The fill-first
# implementation in the current file subsequently re-applies the SL using the
# broker-confirmed openPrice, so every actual filled position gets its own SL.
s = s.replace("const reference=side==='BUY'?ask:bid,stopLoss=initialStop(side,reference);", "const reference=side==='BUY'?ask:bid,stopLoss=initialStop(side,reference);")

# Remove any fixed TP arguments if the older entry implementation still has them.
s = s.replace("connection.createMarketBuyOrder(SYMBOL,volume,stopLoss,normalizePrice(reference+TAKE_PROFIT_PIPS*brokerPipSize()),options)", "connection.createMarketBuyOrder(SYMBOL,volume,stopLoss,undefined,options)")
s = s.replace("connection.createMarketSellOrder(SYMBOL,volume,stopLoss,normalizePrice(reference-TAKE_PROFIT_PIPS*brokerPipSize()),options)", "connection.createMarketSellOrder(SYMBOL,volume,stopLoss,undefined,options)")

p.write_text(s)
