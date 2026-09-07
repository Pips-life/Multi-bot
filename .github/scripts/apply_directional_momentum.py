from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

# Direction model: large impulse candles are treated as directional evidence; a
# controlled 30-70% retracement with renewed tick momentum is an entry signal.
s = s.replace("const MIN_LARGE_CANDLE_PIPS=80;", "const MIN_LARGE_CANDLE_PIPS=80;")
s = s.replace("const RETRACEMENT_MIN=0.30;", "const RETRACEMENT_MIN=0.30;")
s = s.replace("const RETRACEMENT_MAX=0.70;", "const RETRACEMENT_MAX=0.70;")
s = s.replace("const IMPULSE_LOOKBACK_CANDLES=3;", "const IMPULSE_LOOKBACK_CANDLES=3;\nconst MOMENTUM_FADE_MIN_PIPS=8;\nconst MOMENTUM_ACCEL_PIPS=3;\nconst DYNAMIC_BE_TRIGGER_PIPS=25;\nconst DYNAMIC_LOCK_1_TRIGGER_PIPS=50;\nconst DYNAMIC_LOCK_2_TRIGGER_PIPS=80;\nconst DYNAMIC_LOCK_3_TRIGGER_PIPS=120;")

# Replace the position manager with per-position trailing SL + momentum TP logic.
start = s.index("async function onTick(mid,bid,ask,previous){")
end = s.index("function startForegroundService", start)
newtick = r'''async function manageOnePosition(position,bid,ask){
  const side=sideOf(position);
  const entry=Number(position?.openPrice);
  if(!side||!Number.isFinite(entry))return false;

  const pip=brokerPipSize();
  const current=side==='BUY'?Number(bid):Number(ask);
  if(!Number.isFinite(current)||pip<=0)return false;
  const profitPips=side==='BUY'?(current-entry)/pip:(entry-current)/pip;

  const deltas=momentumDeltas.slice(-MOMENTUM_WINDOW);
  const momentumPips=deltas.reduce((a,b)=>a+b,0)/pip;
  const lastPips=Number(deltas[deltas.length-1]||0)/pip;
  const priorPips=deltas.length>1?Number(deltas[deltas.length-2]||0)/pip:0;
  const favorable=side==='BUY'?momentumPips>0:momentumPips<0;
  const adverse=side==='BUY'?momentumPips<0:momentumPips>0;
  const adverseGrowing=adverse && Math.abs(lastPips)>=MOMENTUM_FADE_MIN_PIPS && Math.abs(lastPips)>=Math.abs(priorPips)+MOMENTUM_ACCEL_PIPS;
  const fading=side==='BUY' ? (lastPips<=0 || momentumPips<=0) : (lastPips>=0 || momentumPips>=0);

  // Dynamic SL is calculated independently from each fill price. It only moves
  // toward profit and never widens the broker's existing protective stop.
  let lockPips=0;
  if(profitPips>=DYNAMIC_LOCK_3_TRIGGER_PIPS)lockPips=80;
  else if(profitPips>=DYNAMIC_LOCK_2_TRIGGER_PIPS)lockPips=50;
  else if(profitPips>=DYNAMIC_LOCK_1_TRIGGER_PIPS)lockPips=25;
  else if(profitPips>=DYNAMIC_BE_TRIGGER_PIPS)lockPips=5;

  if(lockPips>0){
    const desired=normalizePrice(side==='BUY'?entry+lockPips*pip:entry-lockPips*pip);
    const old=Number(position?.stopLoss);
    const improves=side==='BUY' ? (!Number.isFinite(old)||desired>old+pip*0.5) : (!Number.isFinite(old)||desired<old-pip*0.5);
    if(improves){
      try{await connection.modifyPosition(idOf(position),desired,undefined);}
      catch(e){setStatus(`DYNAMIC SL retry ${side} ${idOf(position)} — ${e?.message||e}`);}
    }
  }

  // Dynamic TP: there is deliberately no fixed TP price. A profitable position
  // exits when its 1-minute momentum fades, or immediately when adverse momentum
  // is accelerating against it. This is evaluated independently per position.
  if(profitPips>0 && (adverseGrowing || (profitPips>=DYNAMIC_BE_TRIGGER_PIPS && fading))){
    await closePosition(position, adverseGrowing
      ? `+${profitPips.toFixed(0)}p — adverse momentum accelerating`
      : `+${profitPips.toFixed(0)}p — profitable momentum fading`);
    return true;
  }

  // Losing trades get a fast directional escape only when the move against them
  // is strengthening. If momentum is still turning back toward the entry, keep
  // the individual 200-pip protective SL active.
  if(profitPips<=-ADVERSE_MOMENTUM_PIPS && adverseGrowing){
    await closePosition(position, `${profitPips.toFixed(0)}p — adverse momentum accelerating`);
    return true;
  }

  return false;
}

async function onTick(mid,bid,ask,previous){
  reconcile();
  if(Number.isNaN(previous)){
    setStatus('Streaming XAUUSD — building candle/momentum direction');
    return;
  }

  const positions=[...ownedPositions()];
  let closed=false;
  for(const position of positions){
    if(await manageOnePosition(position,bid,ask))closed=true;
  }
  if(closed){reconcile();return;}

  if(positions.length>=MAX_POSITIONS)return;

  const signal=directionSignal();
  if(!signal.side){
    if(!positions.length){
      const avg=averageCandleRange();
      const candleSize=Number.isFinite(candleOpen)&&Number.isFinite(candleClose)?Math.abs(candleClose-candleOpen)/brokerPipSize():0;
      setStatus(`WAITING — direction ${candleSize.toFixed(0)}p candle | avg ${Number.isFinite(avg)?avg.toFixed(0):'—'}p | momentum ${momentumDeltas.reduce((a,b)=>a+b,0)/brokerPipSize()>=0?'BUY':'SELL'}-lean`);
    }
    return;
  }

  // Never add to an existing position against its direction. A retracement entry
  // is allowed only when the large candle has not been structurally broken and
  // fresh tick momentum has resumed in the impulse direction.
  if(positions.length&&positions.some(p=>sideOf(p)!==signal.side))return;
  await enter(signal.side,bid,ask);
}
'''
s=s[:start]+newtick+s[end:]

# Make the large-candle retracement model stricter and more explicit: body must
# dominate the candle and price must remain on the impulse side of its open.
old = "const large=candle.rangePips>=MIN_LARGE_CANDLE_PIPS&&(!Number.isFinite(avg)||candle.rangePips>=avg*LARGE_CANDLE_MULTIPLIER)&&candle.bodyPips>=candle.rangePips*0.55;"
new = "const large=candle.rangePips>=MIN_LARGE_CANDLE_PIPS&&(!Number.isFinite(avg)||candle.rangePips>=avg*LARGE_CANDLE_MULTIPLIER)&&candle.bodyPips>=candle.rangePips*0.60;"
s=s.replace(old,new)

# Remove stale fixed-TP wording if an older copy survived the trading-management pass.
s=s.replace("| TP ${TAKE_PROFIT_PIPS}p", "| MOMENTUM TP")

p.write_text(s)
