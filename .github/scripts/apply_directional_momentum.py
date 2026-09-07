from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

# Faster entry response while preserving the directional model.
s = s.replace("const DIRECTION_CONFIRMATIONS=3;", "const DIRECTION_CONFIRMATIONS=2;")

# Retracement is contextual, not a replacement for the existing direction model.
start = s.index("function finalizeCandle(){")
end = s.index("function updateCandle", start)

new_finalize = r'''function finalizeCandle(){
  if(!Number.isFinite(candleOpen)||!Number.isFinite(candleClose)||!Number.isFinite(candleHigh)||!Number.isFinite(candleLow))return;
  const candle={open:candleOpen,high:candleHigh,low:candleLow,close:candleClose,start:candleStart,
    rangePips:candleRangePips({open:candleOpen,high:candleHigh,low:candleLow,close:candleClose}),
    bodyPips:candleBodyPips({open:candleOpen,close:candleClose})};
  candle.side=candle.close>candle.open?'BUY':candle.close<candle.open?'SELL':'';
  candle.avgRangePips=averageCandleRange();
  completedCandles.push(candle);
  if(completedCandles.length>CANDLE_HISTORY_SIZE)completedCandles.shift();

  // Adaptive displacement detection: compare the completed candle with the
  // market's own recent range. No fixed pip size or fixed retracement percentage.
  const rows=completedCandles.slice(0,-1).slice(-CANDLE_HISTORY_SIZE);
  const recentRanges=rows.map(c=>Number(c.rangePips)).filter(Number.isFinite);
  const recentBodies=rows.map(c=>Number(c.bodyPips)).filter(Number.isFinite);
  const avgRange=recentRanges.length?recentRanges.reduce((a,b)=>a+b,0)/recentRanges.length:NaN;
  const avgBody=recentBodies.length?recentBodies.reduce((a,b)=>a+b,0)/recentBodies.length:NaN;
  const largeRange=!Number.isFinite(avgRange)||candle.rangePips>avgRange;
  const directionalBody=!Number.isFinite(avgBody)||candle.bodyPips>=avgBody;
  const directionalShare=candle.rangePips>0?candle.bodyPips/candle.rangePips:0;
  const displaced=!!candle.side&&largeRange&&directionalBody&&directionalShare>=0.5;

  if(displaced){
    // A displacement is also a profit-taking event. Snapshot positions that are
    // open at the displacement so any already-profitable trades can be closed
    // on the very next tick, before the normal post-displacement retracement
    // has a chance to reclaim their profit. New positions opened afterwards
    // are not included in this snapshot.
    const ids=typeof ownedPositions==='function'
      ? ownedPositions().map(p=>idOf(p)).filter(Boolean)
      : [];
    pendingDisplacementProfitTake={ids,side:candle.side,start:candle.start};
    activeImpulse={...candle,age:0};
    setStatus(`DISPLACEMENT ${candle.side} — taking existing profits before retracement`);
  }else if(activeImpulse){
    activeImpulse.age++;
  }

  // Keep the displacement reference while the following price action remains
  // structurally inside/around it. It expires when price breaks the impulse origin.
  if(activeImpulse){
    const impulseSide=activeImpulse.side;
    const price=Number(lastMid);
    const stillStructured=Number.isFinite(price)
      ? (impulseSide==='BUY'?price>=Number(activeImpulse.open):price<=Number(activeImpulse.open))
      : true;
    if(!stillStructured)activeImpulse=null;
  }
}
'''
s = s[:start] + new_finalize + s[end:]

start = s.index("function retracementSignal(){")
end = s.index("function directionSignal(){", start)

new_retrace = r'''function retracementSignal(baseSide=''){
  const impulse=activeImpulse;
  if(!impulse||!impulse.side)return {side:'',score:0,continuation:false,impulse:null};
  const direction=impulse.side;
  const price=Number(lastMid);
  const open=Number(impulse.open);
  const close=Number(impulse.close);
  if(!Number.isFinite(price)||!Number.isFinite(open)||!Number.isFinite(close)||close===open)
    return {side:'',score:0,continuation:false,impulse};

  // A retracement is a move back into the displacement candle while the market
  // still respects the displacement origin. Do not use a fixed percentage zone.
  const insideOrigin=direction==='BUY'?price>open:price<open;
  const pullbackAgainstCandle=candleSide && candleSide!==direction;
  const deltas=momentumDeltas.slice(-MOMENTUM_WINDOW);
  const momentum=deltas.reduce((a,b)=>a+b,0);
  const latest=Number(deltas[deltas.length-1]||0);
  const resumed=direction==='BUY'?momentum>0&&latest>0:momentum<0&&latest<0;
  const baseAgrees=baseSide===direction;
  const continuation=insideOrigin&&pullbackAgainstCandle&&resumed&&(baseAgrees||!baseSide);
  return {side:continuation?direction:'',score:continuation?1:0,continuation,impulse,direction};
}
'''
s = s[:start] + new_retrace + s[end:]

start = s.index("function directionSignal(){")
end = s.index("function positionDistanceAllows", start)

new_direction = r'''function directionSignal(){
  // Start evaluating sooner; the EMA model still needs enough samples to be meaningful.
  if(priceHistory.length<SLOW_EMA+4)return {side:'',score:0,confirmed:false,mode:'building'};
  const mids=priceHistory.map(x=>x.mid);
  const fastSeries=mids.slice(-FAST_EMA*2),slowSeries=mids.slice(-SLOW_EMA*2);
  const fast=ema(fastSeries,FAST_EMA),slow=ema(slowSeries,SLOW_EMA);
  const fastPrev=ema(fastSeries.slice(0,-4),FAST_EMA),slowPrev=ema(slowSeries.slice(0,-4),SLOW_EMA);
  const fastSlope=fast-fastPrev,slowSlope=slow-slowPrev;
  const deltas=momentumDeltas.slice(-MOMENTUM_WINDOW);
  const momentum=deltas.reduce((a,b)=>a+b,0);
  const price=mids[mids.length-1];

  const buyScore=(fast>slow?1:0)+(fastSlope>0?1:0)+(slowSlope>0?1:0)+
    (momentum>0?1:0)+(candleSide==='BUY'?1:0)+(price>fast?1:0);
  const sellScore=(fast<slow?1:0)+(fastSlope<0?1:0)+(slowSlope<0?1:0)+
    (momentum<0?1:0)+(candleSide==='SELL'?1:0)+(price<fast?1:0);

  let rawSide='';
  if(buyScore>=4&&buyScore>sellScore)rawSide='BUY';
  else if(sellScore>=4&&sellScore>buyScore)rawSide='SELL';

  const retrace=retracementSignal(rawSide);
  if(retrace.continuation){
    directionCandidate=retrace.side;
    directionConfirmations=DIRECTION_CONFIRMATIONS;
    return {side:retrace.side,score:Math.max(buyScore,sellScore),confirmed:true,mode:'retracement-continuation',impulse:retrace.impulse};
  }

  if(!rawSide){
    if(directionCandidate)return {side:directionCandidate,score:0,confirmed:false,mode:'holding-bias'};
    directionConfirmations=0;
    return {side:'',score:0,confirmed:false,mode:'neutral'};
  }

  if(rawSide===directionCandidate)directionConfirmations++;
  else{
    directionCandidate=rawSide;
    directionConfirmations=1;
  }

  // High-conviction direction (5/6 model points) executes immediately.
  // A normal 4-point signal needs only two consecutive confirmations.
  const score=rawSide==='BUY'?buyScore:sellScore;
  const confirmed=score>=5||directionConfirmations>=DIRECTION_CONFIRMATIONS;
  return {side:confirmed?rawSide:'',score,confirmed,mode:'direction'};
}
'''
s = s[:start] + new_direction + s[end:]

# Remove obsolete fixed retracement/displacement constants. The adaptive model
# derives its reference from the current market's completed candles.
for name in ('LARGE_CANDLE_MULTIPLIER','MIN_LARGE_CANDLE_PIPS','RETRACEMENT_MIN',
             'RETRACEMENT_MAX','IMPULSE_LOOKBACK_CANDLES'):
    s = re.sub(rf'const {name}=[^;]+;\s*', '', s)

start = s.index("async function onTick(mid,bid,ask,previous){")
end = s.index("function startForegroundService", start)

new_tick = r'''function adaptiveMomentumState(side){
  const pip=brokerPipSize();
  const deltas=momentumDeltas.slice(-MOMENTUM_WINDOW);
  const total=deltas.reduce((a,b)=>a+b,0);
  const recent=deltas.length?deltas[deltas.length-1]:0;
  const prior=deltas.length>1?deltas[deltas.length-2]:recent;
  const avgRangePips=Number(averageCandleRange());
  const avgRange=Number.isFinite(avgRangePips)?avgRangePips*pip:0;
  const candleRange=Number.isFinite(candleHigh)&&Number.isFinite(candleLow)?Math.abs(candleHigh-candleLow):0;
  const scale=Math.max(avgRange,candleRange,Math.abs(total),pip);
  const acceleration=recent-prior;
  const aligned=side==='BUY'?total>0:total<0;
  const adverse=side==='BUY'?total<0:total>0;
  const accelerationAgainst=side==='BUY'?acceleration<0:acceleration>0;
  const strength=Math.abs(total)/scale;
  return {total,recent,prior,acceleration,scale,aligned,adverse,accelerationAgainst,strength};
}

function positionProfitPips(position,bid,ask){
  const side=sideOf(position);
  const entry=Number(position?.openPrice);
  const pip=brokerPipSize();
  const current=side==='BUY'?Number(bid):Number(ask);
  if(!side||!Number.isFinite(entry)||!Number.isFinite(current)||!Number.isFinite(pip)||pip<=0)return NaN;
  return side==='BUY'?(current-entry)/pip:(entry-current)/pip;
}

async function takeDisplacementProfits(bid,ask){
  const pending=pendingDisplacementProfitTake;
  if(!pending||!Array.isArray(pending.ids)||!pending.ids.length)return false;
  pendingDisplacementProfitTake=null;
  let closed=false;
  for(const position of ownedPositions()){
    const id=idOf(position);
    if(!id||!pending.ids.includes(id))continue;
    const profitPips=positionProfitPips(position,bid,ask);
    // Only close trades that are still profitable. If spread temporarily
    // removes the profit, leave the position under its normal management.
    if(Number.isFinite(profitPips)&&profitPips>0){
      await closePosition(position,`+${profitPips.toFixed(0)}p — displacement profit take before reclamation`);
      closed=true;
    }
  }
  return closed;
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

  // Once a trade is well into profit, protect it dynamically while allowing
  // strong momentum to continue. The distance is derived from current market
  // range rather than a fixed TP.
  if(profitPips>=100){
    const distance=Math.max(m.scale*0.35,pip);
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

  // Begin profit protection before +100 so a winning move is not allowed to
  // travel all the way back to entry before the momentum exit activates.
  if(profitPips>=70){
    const fading=!m.aligned||m.strength<0.5;
    const reversing=m.adverse&&m.accelerationAgainst&&Math.abs(m.recent)>=Math.abs(m.prior);
    if(reversing||fading){
      await closePosition(position,reversing
        ? `+${profitPips.toFixed(0)}p — momentum reversing`
        : `+${profitPips.toFixed(0)}p — momentum fading`);
      return true;
    }
  }

  // Keep the requested -100 pip decision boundary. Below that point, only a
  // genuinely strengthening adverse move closes early; otherwise the trade is
  // allowed to recover under its broker-side -200 pip protective SL.
  if(profitPips<=-100){
    const adverseGrowing=m.adverse&&m.accelerationAgainst&&Math.abs(m.recent)>=Math.abs(m.prior);
    if(adverseGrowing){
      await closePosition(position,`${profitPips.toFixed(0)}p — adverse momentum growing`);
      return true;
    }
    setStatus(`DRAW ${profitPips.toFixed(0)}p ${side} — adverse momentum faded | HOLD`);
  }
  return false;
}

async function onTick(mid,bid,ask,previous){
  reconcile();
  if(Number.isNaN(previous)){
    setStatus('Streaming XAUUSD — reading direction, momentum and retracement structure');
    return;
  }

  // Profit-taking has first priority after every detected displacement. This
  // intentionally runs before new entries and before normal trailing logic so
  // an existing winner is banked before the post-displacement reclamation.
  const displacementClosed=await takeDisplacementProfits(bid,ask);
  if(displacementClosed){reconcile();return;}

  const positions=[...ownedPositions()];
  let closed=false;
  for(const position of positions){
    if(await manageOnePosition(position,bid,ask))closed=true;
  }
  if(closed){reconcile();return;}
  if(positions.length>=MAX_POSITIONS)return;

  const signal=directionSignal();
  if(!signal.side)return;
  if(positions.length&&positions.some(p=>sideOf(p)!==signal.side))return;
  await enter(signal.side,bid,ask);
}
'''
s = s[:start] + new_tick + s[end:]

# The state is created in web/main.js by earlier build-time scripts. Add a
# defensive declaration only if the target file does not already define it.
if 'pendingDisplacementProfitTake' not in s.split('function finalizeCandle(){',1)[0]:
    marker='let activeImpulse=null;'
    if marker in s:
        s=s.replace(marker,marker+'\nlet pendingDisplacementProfitTake=null;',1)
    else:
        s='let pendingDisplacementProfitTake=null;\n'+s

p.write_text(s)
