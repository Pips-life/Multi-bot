from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

# Adaptive candle/momentum model: do not impose fixed pip/percentage gates on
# candle size, retracement depth, momentum fade, or profit locking. The live
# candle range and recent momentum are the reference for each market condition.
start = s.index("async function onTick(mid,bid,ask,previous){")
end = s.index("function startForegroundService", start)

newtick = r'''function adaptiveMomentumState(side){
  const pip=brokerPipSize();
  const deltas=momentumDeltas.slice(-MOMENTUM_WINDOW);
  const total=deltas.reduce((a,b)=>a+b,0);
  const recent=deltas.length?deltas[deltas.length-1]:0;
  const prior=deltas.length>1?deltas[deltas.length-2]:recent;
  const avgRange=Number(averageCandleRange());
  const candleRange=Number.isFinite(candleHigh)&&Number.isFinite(candleLow)?Math.abs(candleHigh-candleLow):0;
  const scale=Math.max(avgRange||0,candleRange||0,Math.abs(total)||0,pip);
  const acceleration=recent-prior;
  const aligned=side==='BUY'?total>0:total<0;
  const adverse=side==='BUY'?total<0:total>0;
  const accelerationAgainst=side==='BUY'?acceleration<0:acceleration>0;
  const strength=Math.abs(total)/scale;
  return {total,recent,prior,acceleration,scale,aligned,adverse,accelerationAgainst,strength};
}

async function manageOnePosition(position,bid,ask){
  const side=sideOf(position);
  const entry=Number(position?.openPrice);
  if(!side||!Number.isFinite(entry))return false;
  const pip=brokerPipSize();
  const current=side==='BUY'?Number(bid):Number(ask);
  if(!Number.isFinite(current)||pip<=0)return false;
  const profitPips=side==='BUY'?(current-entry)/pip:(entry-current)/pip;
  const m=adaptiveMomentumState(side);

  // Per-position dynamic SL: trail from this position's actual fill using the
  // current candle/momentum range. Never widen an existing broker stop.
  if(profitPips>0){
    const distance=Math.max(m.scale*0.5,pip);
    const desired=normalizePrice(side==='BUY'?current-distance:current+distance);
    const old=Number(position?.stopLoss);
    const improves=side==='BUY'
      ?(!Number.isFinite(old)||desired>old+pip*0.5)
      :(!Number.isFinite(old)||desired<old-pip*0.5);
    if(improves){
      try{await connection.modifyPosition(idOf(position),desired,undefined);}
      catch(e){setStatus(`DYNAMIC SL retry ${side} ${idOf(position)} — ${e?.message||e}`);}
    }
  }

  // No fixed TP. Let momentum run while it is aligned. Close a profitable
  // position when directional momentum fades, and close immediately when the
  // momentum impulse is turning decisively against it.
  if(profitPips>0){
    const fading=!m.aligned || m.strength<0.5;
    const reversing=m.adverse && m.accelerationAgainst && Math.abs(m.recent)>=Math.abs(m.prior);
    if(reversing||fading){
      await closePosition(position,reversing
        ? `+${profitPips.toFixed(0)}p — momentum reversing`
        : `+${profitPips.toFixed(0)}p — momentum fading`);
      return true;
    }
  }

  // Losing positions are not closed merely because they are negative. Exit
  // quickly only when momentum is strengthening against the position; otherwise
  // retain the individual protective SL and allow recovery.
  if(profitPips<0 && m.adverse && m.accelerationAgainst && m.strength>=1){
    await closePosition(position,`${profitPips.toFixed(0)}p — adverse momentum strengthening`);
    return true;
  }
  return false;
}

async function onTick(mid,bid,ask,previous){
  reconcile();
  if(Number.isNaN(previous)){
    setStatus('Streaming XAUUSD — reading candle size and momentum');
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
  if(!signal.side)return;

  // Large-candle continuation is handled by directionSignal using candle body,
  // range and live momentum. Retracement entries are not blocked by a fixed
  // percentage: a pullback inside the impulse candle can be used when momentum
  // resumes in the impulse direction and the candle structure remains intact.
  if(positions.length&&positions.some(p=>sideOf(p)!==signal.side))return;
  await enter(signal.side,bid,ask);
}
'''
s=s[:start]+newtick+s[end:]

# Remove all fixed threshold constants introduced by the previous version.
for name in ('MIN_LARGE_CANDLE_PIPS','RETRACEMENT_MIN','RETRACEMENT_MAX','IMPULSE_LOOKBACK_CANDLES',
             'MOMENTUM_FADE_MIN_PIPS','MOMENTUM_ACCEL_PIPS','DYNAMIC_BE_TRIGGER_PIPS',
             'DYNAMIC_LOCK_1_TRIGGER_PIPS','DYNAMIC_LOCK_2_TRIGGER_PIPS','DYNAMIC_LOCK_3_TRIGGER_PIPS'):
    s=re.sub(rf'const {name}=[^;]+;\s*', '', s)

s=s.replace("| TP ${TAKE_PROFIT_PIPS}p", "| MOMENTUM TP")
p.write_text(s)
