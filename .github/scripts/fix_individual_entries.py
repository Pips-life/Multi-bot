from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

start = s.index("async function enter(side,bid,ask){")
end = s.index("async function waitForPosition", start)

new_enter = r'''async function enter(side,bid,ask){
  const initialPositions=ownedPositions();
  if(entryInFlight||initialPositions.length>=MAX_POSITIONS||!connection||!synchronized||!positionDistanceAllows(side,initialPositions))return;

  const info=connection?.terminalState?.accountInformation||{};
  const initialFreeMargin=Number(info.freeMargin);
  if(Number.isFinite(initialFreeMargin)&&initialFreeMargin<=0){
    setStatus('ENTRY BLOCKED — insufficient free margin');
    return;
  }

  const slots=Math.max(0,MAX_POSITIONS-initialPositions.length);
  if(!slots)return;
  const volume=currentVolume();
  entryInFlight=true;
  let opened=0;

  try{
    // Never submit a batch with Promise.all. Each position is validated and
    // confirmed by the broker before the next one is attempted. This prevents
    // MetaApi validation races when several orders consume the same margin.
    for(let i=0;i<slots;i++){
      const positions=ownedPositions();
      if(positions.length>=MAX_POSITIONS)break;
      if(!positionDistanceAllows(side,positions))break;

      const accountInfo=connection?.terminalState?.accountInformation||{};
      const freeMargin=Number(accountInfo.freeMargin);
      if(Number.isFinite(freeMargin)&&freeMargin<=0){
        setStatus(`ENTRY STOPPED — free margin exhausted after ${opened} position${opened===1?'':'s'}`);
        break;
      }

      const spec=connection?.terminalState?.specification(SYMBOL);
      const marginRequired=Number(spec?.marginRequired)||0;
      if(marginRequired>0&&Number.isFinite(freeMargin)&&freeMargin<marginRequired*volume){
        setStatus(`ENTRY STOPPED — balance/free margin allows ${opened} position${opened===1?'':'s'}`);
        break;
      }

      const latestPrice=side==='BUY'?Number(connection?.terminalState?.price(SYMBOL)?.ask):Number(connection?.terminalState?.price(SYMBOL)?.bid);
      const reference=Number.isFinite(latestPrice)&&latestPrice>0?latestPrice:(side==='BUY'?ask:bid);
      const stopLoss=initialStop(side,reference);
      if(!Number.isFinite(stopLoss))break;

      const clientId=`MB_${Date.now().toString(36)}_${i}_${Math.floor(Math.random()*36).toString(36)}`;
      const options={comment:`MB ${side}`,magic:MAGIC,clientId};

      try{
        if(side==='BUY') await connection.createMarketBuyOrder(SYMBOL,volume,stopLoss,undefined,options);
        else await connection.createMarketSellOrder(SYMBOL,volume,stopLoss,undefined,options);
        opened++;
        lastEntryPrice=reference;
        await waitForPosition(side,5000);
        reconcile();
        setStatus(`OPEN ${side} ${opened}/${slots} × ${volume} — individual margin-aware entry | SL ${INITIAL_SL_PIPS}p | MOMENTUM EXIT`);
      }catch(e){
        const msg=e?.message||String(e);
        // Stop immediately on validation/margin rejection. Do not resubmit the
        // same order and do not turn one failed entry into a batch failure.
        setStatus(`ENTRY ${side} ${opened+1} rejected — ${msg}`);
        break;
      }
    }

    if(opened>0)setStatus(`OPENED ${opened} individual ${side} position${opened===1?'':'s'} — balance/margin sized`);
    else setStatus(`NO ${side} ENTRY — account balance/free margin insufficient or broker validation rejected it`);
  }finally{
    entryInFlight=false;
  }
}
'''

s = s[:start] + new_enter + s[end:]
p.write_text(s)
