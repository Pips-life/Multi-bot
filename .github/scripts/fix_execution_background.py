from pathlib import Path

p = Path('web/main.js')
s = p.read_text(encoding='utf-8')

def replace_func(src, name, new):
    markers = (f'async function {name}', f'function {name}')
    i = -1
    for marker in markers:
        i = src.find(marker)
        if i >= 0:
            break
    if i < 0:
        raise SystemExit(f'missing {name}')
    b = src.find('{', i)
    if b < 0:
        raise SystemExit(f'missing brace {name}')
    depth = 0
    quote = None
    esc = False
    for j in range(b, len(src)):
        ch = src[j]
        if quote:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in "'\"`":
            quote = ch
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return src[:i] + new + src[j + 1:]
    raise SystemExit(f'unclosed {name}')

entry = '''function entrySignal(mid){
  if(!directionBias||!Number.isFinite(lastMid)||reversalCandidate)return '';
  const c=workingCandle;if(!c)return '';
  const pip=brokerPipSize();
  const move=directionBias==='BUY'?mid-lastMid:lastMid-mid;
  const bodyFromOpen=directionBias==='BUY'?mid-c.open:c.open-mid;
  const resumed=move>0&&bodyFromOpen/pip>=RESUME_CONFIRM_RATIO;
  if(retracing)return directionBias;
  return resumed?directionBias:'';
}'''
s = replace_func(s, 'entrySignal', entry)

enter = '''async function enter(side,spot){
  if(entryInFlight||currentPosition||!connection||!trading||stopRequested||!synchronized)return;
  if(directionBias!==side||reversalCandidate){setStatus(`ENTRY BLOCKED — ${marketPhase}`);return;}
  const volume=currentVolume(),pipSize=brokerPipSize(),initialStop=stopCandidate(side,Number(spot),pipSize);
  if(volume<=0){setStatus('Cannot size trade: invalid XAUUSD execution volume');return;}
  if(!Number.isFinite(initialStop)||initialStop<=0){setStatus('Cannot calculate 70-pip stop');return;}
  entryInFlight=true;
  try{
    const clientId=`MB_${side}_${Date.now()}`;
    const options={...tradeOptions(`MB Bias ${side} — displacement direction — 70pip Trail`),clientId};
    addLog(`ORDER REQUEST → ${side} ${volume} LOT @ ${fmt(Number(spot))} | SL ${fmt(initialStop)}`);
    const result=side==='BUY'
      ? await connection.createMarketBuyOrder(SYMBOL,volume,initialStop,undefined,options)
      : await connection.createMarketSellOrder(SYMBOL,volume,initialStop,undefined,options);
    addLog(`BROKER ORDER ACCEPTED → ${side} | ${result?.orderId||result?.positionId||result?.id||clientId}`);
    if(stopRequested||!trading){await reconcile();if(currentPosition)await closePositionSafe(currentPosition);return;}
    setStatus(`TRADE EXECUTED — ${side} ${volume} LOT | SL ${fmt(initialStop)}`);
    sessionHistory.unshift({time:Date.now(),text:`Trade executed: ${side} ${volume} LOT`});
    await waitForPosition(side,5000);
    await reconcile();
    if(!currentPosition||sideOf(currentPosition)!==side){
      setStatus(`ORDER ACCEPTED — waiting for ${side} position synchronization`);
      await new Promise(r=>setTimeout(r,1000));
      await reconcile();
    }
  }catch(e){
    const msg=e?.message||String(e);
    if(!stopRequested){
      addLog(`BROKER ORDER REJECTED → ${side} | ${msg}`);
      setStatus(`TRADE FAILED — ${msg}`);
    }
  }finally{entryInFlight=false;}
}'''
s = replace_func(s, 'enter', enter)

# Ensure the tick handler always reconciles broker state before deciding whether an entry is needed.
tick = '''async function onTick(mid,bid,ask){
  if(!Number.isFinite(mid))return;
  if(stopRequested||!trading||!synchronized){lastMid=mid;return;}
  try{
    await reconcile();
    if(stopRequested||!trading||!synchronized){lastMid=mid;return;}
    if(currentPosition){
      await trail(bid,ask);
      return;
    }
    const signal=entrySignal(mid);
    if(signal&&signal===directionBias&&!entryInFlight){
      const executionPrice=signal==='BUY'?ask:bid;
      addLog(`EXECUTION DECISION → ${signal} | phase ${marketPhase} | price ${fmt(executionPrice)}`);
      await enter(signal,executionPrice);
    }
  }catch(e){
    if(!stopRequested)setStatus(`Tick execution error: ${e?.message||e}`);
  }finally{lastMid=mid;}
}'''
s = replace_func(s, 'onTick', tick)

s = s.replace("currentStop={id:idOf(position),openPrice:candidate};", "currentStop={id:idOf(currentPosition),openPrice:candidate};")

if 'function startBot()' not in s and 'async function startBot()' not in s:
    raise SystemExit('missing startBot')
if 'function stopAllTrading()' not in s and 'async function stopAllTrading()' not in s:
    raise SystemExit('missing stopAllTrading')

p.write_text(s, encoding='utf-8')
print('Direct broker execution hardening applied: executable bias entries, broker acceptance logging, and trailing-state fix.')
