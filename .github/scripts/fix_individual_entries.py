from pathlib import Path

p = Path('web/main.js')
s = p.read_text()

# MetaApi accounts configured with manualTrades=true require magic=0 on trades.
# The previous build forced MAGIC=260904, which can produce MetaApi Validation
# failed before a market order reaches the broker. Use the account's configured
# magic for position ownership instead of assuming the strategy magic.
old_is_ours = "function isOurs(x){return !!x&&x.symbol===SYMBOL&&(Number(x.magic)===MAGIC||String(x.clientId??'').startsWith('MB_'));}"
new_is_ours = "function isOurs(x){if(!x||x.symbol!==SYMBOL)return false;const accountMagic=Number(account?.magic);const allowedMagic=Number.isFinite(accountMagic)?accountMagic:(account?.manualTrades===true?0:MAGIC);return Number(x.magic)===allowedMagic||String(x.clientId??'').startsWith('MB_');}"
s = s.replace(old_is_ours,new_is_ours)

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
    // Use the broker-minimal market request. No strategy magic, clientId,
    // comment, SL or TP is sent on the initial order. MetaApi documents that
    // accounts using manualTrades require magic=0; forcing our own magic can
    // therefore cause a Validation failed response before execution.
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
      const reference=side==='BUY'?Number(price?.ask):Number(price?.bid);
      const fallback=side==='BUY'?Number(ask):Number(bid);
      const entryPrice=Number.isFinite(reference)&&reference>0?reference:fallback;
      if(!Number.isFinite(entryPrice)||entryPrice<=0){
        setStatus('ENTRY STOPPED — live broker price unavailable');
        break;
      }

      try{
        if(side==='BUY') await connection.createMarketBuyOrder(SYMBOL,volume);
        else await connection.createMarketSellOrder(SYMBOL,volume);

        const position=await waitForPosition(side,7000);
        if(!position){
          setStatus(`ENTRY ${side} submitted but broker position confirmation timed out`);
          break;
        }

        opened++;
        const filledPrice=Number(position.openPrice)||entryPrice;
        lastEntryPrice=filledPrice;

        // Attach the requested 200-pip protective SL only after the broker has
        // supplied the actual fill price. Retry briefly for terminal sync lag.
        const stopLoss=initialStop(side,filledPrice);
        if(Number.isFinite(stopLoss)){
          let slApplied=false;
          for(let attempt=1;attempt<=3&&!slApplied;attempt++){
            try{
              await connection.modifyPosition(idOf(position),stopLoss,undefined);
              slApplied=true;
            }catch(slError){
              if(attempt===3){
                setStatus(`OPEN ${side} ${opened}/${slots} — SL placement rejected after 3 attempts: ${slError?.message||slError}`);
              }else await new Promise(r=>setTimeout(r,250*attempt));
            }
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
