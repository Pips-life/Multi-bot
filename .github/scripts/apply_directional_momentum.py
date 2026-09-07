from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

# Retracement is contextual, not a replacement for the existing direction model.
# The bot first establishes directional bias from EMA structure, slopes, momentum,
# candle direction and price location. A pullback into a prior displacement candle
# may reinforce that same bias, but it must not become a separate entry model.
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
    activeImpulse={...candle,age:0};
    setStatus(`DISPLACEMENT ${candle.side} — watching retracement without changing bias`);
  }else if(activeImpulse){
    activeImpulse.age++;
  }

  // Keep the displacement reference while the following price action remains
  // structurally inside/around it. It expires only when the market establishes
  // a new candle structure, not after a fixed pip/percentage window.
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
  if(priceHistory.length<SLOW_EMA+8)return {side:'',score:0,confirmed:false,mode:'building'};
  const mids=priceHistory.map(x=>x.mid);
  const fastSeries=mids.slice(-FAST_EMA*2),slowSeries=mids.slice(-SLOW_EMA*2);
  const fast=ema(fastSeries,FAST_EMA),slow=ema(slowSeries,SLOW_EMA);
  const fastPrev=ema(fastSeries.slice(0,-5),FAST_EMA),slowPrev=ema(slowSeries.slice(0,-5),SLOW_EMA);
  const fastSlope=fast-fastPrev,slowSlope=slow-slowPrev;
  const deltas=momentumDeltas.slice(-MOMENTUM_WINDOW);
  const momentum=deltas.reduce((a,b)=>a+b,0);
  const price=mids[mids.length-1];

  // Primary entry logic remains the original directional/momentum model.
  const buyScore=(fast>slow?1:0)+(fastSlope>0?1:0)+(slowSlope>0?1:0)+
    (momentum>0?1:0)+(candleSide==='BUY'?1:0)+(price>fast?1:0);
  const sellScore=(fast<slow?1:0)+(fastSlope<0?1:0)+(slowSlope<0?1:0)+
    (momentum<0?1:0)+(candleSide==='SELL'?1:0)+(price<fast?1:0);

  let rawSide='';
  if(buyScore>=4&&buyScore>sellScore)rawSide='BUY';
  else if(sellScore>=4&&sellScore>buyScore)rawSide='SELL';

  // Retracement never creates a new bias by itself. It can only reinforce the
  // established displacement direction when the base model agrees (or is
  // temporarily neutral) and price has not broken the displacement origin.
  const retrace=retracementSignal(rawSide);
  if(retrace.continuation){
    if(directionCandidate!==retrace.side){
      directionCandidate=retrace.side;
      directionConfirmations=1;
    }
    return {side:retrace.side,score:Math.max(buyScore,sellScore),confirmed:true,mode:'retracement-continuation',impulse:retrace.impulse};
  }

  // A genuine direction change must come from the primary model. A pullback
  // against the last candle is not enough to flip the bias while the larger
  // structure and momentum still point to the existing direction.
  if(!rawSide){
    if(directionCandidate)return {side:directionCandidate,score:0,confirmed:false,mode:'holding-bias'};
    directionConfirmations=0;
    return {side:'',score:0,confirmed:false,mode:'neutral'};
  }

  if(rawSide===directionCandidate){
    directionConfirmations++;
  }else{
    directionCandidate=rawSide;
    directionConfirmations=1;
  }

  const confirmed=directionConfirmations>=DIRECTION_CONFIRMATIONS;
  return {side:confirmed?rawSide:'',score:rawSide==='BUY'?buyScore:sellScore,confirmed,mode:'direction'};
}
'''
s = s[:start] + new_direction + s[end:]

# Remove obsolete fixed retracement/displacement constants. The adaptive model
# above derives its reference from the current market's completed candles.
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

async function manageOnePosition(position,bid,ask){
  const side=sideOf(position);
  const entry=Number(position?.openPrice);
  if(!side||!Number.isFinite(entry))return false;
  const pip=brokerPipSize();
  const current=side==='BUY'?Number(bid):Number(ask);
  if(!Number.isFinite(current)||pip<=0)return false;
  const profitPips=side==='BUY'?(current-entry)/pip:(entry-current)/pip;
  const m=adaptiveMomentumState(side);

  // Do not tighten the dynamic SL before the +100 pip profit threshold.
  // The original protective SL remains active below this threshold.
  if(profitPips>=100){
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

  // Momentum-based profit exits only become active after +100 pips.
  // Before +100, a position is allowed to breathe and is protected only by
  // its initial/previously established protective SL.
  if(profitPips>=100){
    const fading=!m.aligned || m.strength<0.5;
    const reversing=m.adverse&&m.accelerationAgainst&&Math.abs(m.recent)>=Math.abs(m.prior);
    if(reversing||fading){
      await closePosition(position,reversing
        ? `+${profitPips.toFixed(0)}p — momentum reversing`
        : `+${profitPips.toFixed(0)}p — momentum fading`);
      return true;
    }
  }

  // Losing positions still use the adverse-momentum protection; the +100 pip
  // threshold applies specifically to profit-taking/fade exits.
  if(profitPips<0&&m.adverse&&m.accelerationAgainst&&m.strength>=1){
    await closePosition(position,`${profitPips.toFixed(0)}p — adverse momentum strengthening`);
    return true;
  }
  return false;
}

async function onTick(mid,bid,ask,previous){
  reconcile();
  if(Number.isNaN(previous)){
    setStatus('Streaming XAUUSD — reading direction, momentum and retracement structure');
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

  // Existing direction remains the entry bias during a retracement. Only the
  // primary directional model can change the bias to the opposite side.
  if(positions.length&&positions.some(p=>sideOf(p)!==signal.side))return;
  await enter(signal.side,bid,ask);
}
'''
s = s[:start] + new_tick + s[end:]

s=s.replace("| TP ${TAKE_PROFIT_PIPS}p", "| MOMENTUM TP FROM +100p")
p.write_text(s)
