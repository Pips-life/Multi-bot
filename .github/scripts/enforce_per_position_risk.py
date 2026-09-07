from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

# Every position gets an individual 200-pip protective SL.
s = s.replace("const INITIAL_SL_PIPS=100;", "const INITIAL_SL_PIPS=200;")

start = s.index("async function onTick(mid,bid,ask,previous){")
end = s.index("function startForegroundService", start)

newtick = r'''async function ensurePositionStop(position){
  if(!connection||!position)return;
  const id=idOf(position), side=sideOf(position), entry=Number(position.openPrice);
  if(!id||!side||!Number.isFinite(entry)||entry<=0)return;
  const pip=brokerPipSize();
  const required=initialStop(side,entry);
  if(!Number.isFinite(required))return;
  const existing=Number(position.stopLoss);
  const tolerance=pip*0.5;
  if(Number.isFinite(existing)&&Math.abs(existing-required)<=tolerance)return;
  try{
    await connection.modifyPosition(id,required,undefined);
    setStatus(`${side} ${id.slice(0,8)} — protective SL enforced at -${INITIAL_SL_PIPS}p`);
  }catch(e){
    setStatus(`SL enforcement failed ${id.slice(0,8)} — ${e?.message||e}`);
  }
}

async function manageOpenPositions(positions,bid,ask){
  const pip=brokerPipSize();
  const deltaSum=momentumDeltas.slice(-MOMENTUM_WINDOW).reduce((a,b)=>a+b,0);
  const tasks=[];
  for(const position of positions){
    const side=sideOf(position);
    const entry=Number(position.openPrice);
    if(!side||!Number.isFinite(entry)||entry<=0)continue;
    // Enforce a real broker-side SL separately for every position.
    tasks.push(ensurePositionStop(position));
    const current=side==='BUY'?Number(bid):Number(ask);
    const pnlPips=side==='BUY'?(current-entry)/pip:(entry-current)/pip;
    const adverseMomentum=side==='BUY'?deltaSum<0:deltaSum>0;
    const momentumFadedOrNeutral=!adverseMomentum;

    // At -100p, only close this individual position when adverse momentum is
    // actually growing. If the negative momentum has faded/neutralized, HOLD
    // and let the protected -200p SL remain in force.
    if(pnlPips<=-100 && adverseMomentum){
      tasks.push(closePosition(position,`${pnlPips.toFixed(0)}p — adverse momentum growing`));
    }else if(pnlPips<=-100 && momentumFadedOrNeutral){
      setStatus(`${side} ${pnlPips.toFixed(0)}p — adverse momentum faded | HOLD | SL -${INITIAL_SL_PIPS}p`);
    }
  }
  await Promise.all(tasks);
}

async function onTick(mid,bid,ask,previous){
  reconcile();
  if(Number.isNaN(previous)){setStatus('Streaming XAUUSD — building direction model');return;}
  const positions=ownedPositions();
  if(positions.length){
    await manageOpenPositions(positions,bid,ask);
    // Never use an aggregate/average entry price for risk management.
    // Each open position is independently protected and independently eligible
    // for the -100p adverse-momentum exit.
    if(positions.length>=MAX_POSITIONS)return;
  }
  const signal=directionSignal();
  if(!signal.side){
    if(!positions.length)setStatus(`WAITING — building direction | samples ${priceHistory.length}/${SLOW_EMA+2}`);
    return;
  }
  if(positions.length&&positions.some(p=>sideOf(p)!==signal.side))return;
  await enter(signal.side,bid,ask);
}
'''

s = s[:start] + newtick + s[end:]
p.write_text(s)
