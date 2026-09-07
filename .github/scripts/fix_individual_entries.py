from pathlib import Path

p = Path('web/main.js')
s = p.read_text()

start = s.index("async function enter(side,bid,ask){")
end = s.index("async function waitForPosition", start)

new_enter = r'''async function enter(side,bid,ask){
  const initialPositions=ownedPositions();
  if(entryInFlight||initialPositions.length>=MAX_POSITIONS||!connection||!synchronized||!positionDistanceAllows(side,initialPositions))return;

  const accountInfo=connection?.terminalState?.accountInformation||{};
  const freeMargin=Number(accountInfo.freeMargin);
  if(Number.isFinite(freeMargin)&&freeMargin<=0){
    setStatus('ENTRY BLOCKED — broker reports no free margin');
    return;
  }

  const slots=Math.max(0,MAX_POSITIONS-initialPositions.length);
  if(!slots)return;
  const volume=currentVolume();
  entryInFlight=true;
  let opened=0;

  try{
    // One order at a time. Do not pre-submit a batch: MetaApi/broker validation
    // can race when several XAUUSD orders consume margin simultaneously.
    for(let i=0;i<slots;i++){
      const positions=ownedPositions();
      if(positions.length>=MAX_POSITIONS)break;
      if(!positionDistanceAllows(side,positions))break;

      const liveInfo=connection?.terminalState?.accountInformation||{};
      const liveFreeMargin=Number(liveInfo.freeMargin);
      if(Number.isFinite(liveFreeMargin)&&liveFreeMargin<=0){
        setStatus(`ENTRY STOPPED — broker free margin exhausted after ${opened}`);
        break;
      }

      const price=connection?.terminalState?.price(SYMBOL);
      const reference=side==='BUY'?Number(price?.ask):(Number(price?.bid));
      const fallback=side==='BUY'?Number(ask):Number(bid);
      const entryPrice=Number.isFinite(reference)&&reference>0?reference:fallback;
      if(!Number.isFinite(entryPrice)||entryPrice<=0){
        setStatus('ENTRY STOPPED — live broker price unavailable');
        break;
      }

      const clientId=`MB_${Date.now().toString(36)}_${i}_${Math.floor(Math.random()*36).toString(36)}`;
      const options={comment:`MB ${side}`,magic:MAGIC,clientId};

      try{
        // Fill first without attaching a potentially invalid/stale SL/TP price.
        // Once the broker confirms the position, place the protective SL using
        // the actual filled price. This avoids broker validation failures caused
        // by spread/stop-level changes between signal and execution.
        if(side==='BUY') await connection.createMarketBuyOrder(SYMBOL,volume,undefined,undefined,options);
        else await connection.createMarketSellOrder(SYMBOL,volume,undefined,undefined,options);

        const position=await waitForPosition(side,7000);
        if(!position){
          setStatus(`ENTRY ${side} submitted but broker position confirmation timed out`);
          break;
        }

        opened++;
        const filledPrice=Number(position.openPrice)||entryPrice;
        lastEntryPrice=filledPrice;

        const stopLoss=initialStop(side,filledPrice);
        if(Number.isFinite(stopLoss)){
          try{
            await connection.modifyPosition(idOf(position),stopLoss,undefined);
          }catch(slError){
            // Never reject an otherwise valid fill because a protective SL was
            // rejected. Keep monitoring the position and report the exact issue.
            setStatus(`OPEN ${side} ${opened}/${slots} — SL placement rejected: ${slError?.message||slError}`);
          }
        }

        reconcile();
        if(!lastStatus.includes('SL placement rejected')){
          setStatus(`OPEN ${side} ${opened}/${slots} × ${volume} — broker confirmed | SL ${INITIAL_SL_PIPS}p | MOMENTUM EXIT`);
        }
      }catch(e){
        const msg=e?.message||String(e);
        setStatus(`ENTRY ${side} ${opened+1} rejected by broker — ${msg}`);
        break;
      }
    }

    if(opened>0)setStatus(`OPENED ${opened} individual ${side} position${opened===1?'':'s'} — broker-confirmed`);
    else if(!lastStatus.includes('broker')&&!lastStatus.includes('ENTRY '))setStatus(`NO ${side} ENTRY — broker did not confirm a position`);
  }finally{
    entryInFlight=false;
  }
}
'''

s = s[:start] + new_enter + s[end:]
p.write_text(s)
