from pathlib import Path

p = Path('web/main.js')
s = p.read_text(encoding='utf-8')

def replace_func(src, name, new):
    i = src.find(f'async function {name}')
    if i < 0:
        i = src.find(f'function {name}')
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
  // A retracement/pause is an executable entry opportunity in the established bias.
  // Never trade the retracement direction.
  if(retracing)return directionBias;
  return resumed?directionBias:'';
}'''
s = replace_func(s, 'entrySignal', entry)

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
  }finally{
    lastMid=mid;
  }
}'''
s = replace_func(s, 'onTick', tick)

needle = 'let workingCandle=null;'
if 'const RUNNING_KEY=' not in s:
    s = s.replace(needle, needle + "\nconst RUNNING_KEY='pipslife.bot.running';\nfunction persistTradingState(){try{localStorage.setItem(RUNNING_KEY,trading&&!stopRequested?'1':'0');}catch(_){}}\nfunction storedTradingState(){try{return localStorage.getItem(RUNNING_KEY)==='1';}catch(_){return false;}}", 1)

if 'AndroidBot?.startForegroundBot' not in s:
    s = s.replace('stopRequested=false;trading=true;', "stopRequested=false;trading=true;persistTradingState();try{AndroidBot?.startForegroundBot?.();}catch(_){}", 1)
if 'AndroidBot?.stopForegroundBot' not in s:
    s = s.replace('stopRequested=true;trading=false;', "stopRequested=true;trading=false;persistTradingState();try{AndroidBot?.stopForegroundBot?.();}catch(_){}", 1)

if 'AUTO-RESUME — restoring background bot state' not in s:
    s += "\nsetTimeout(()=>{if(storedTradingState()&&ui.token?.value&&ui.account?.value){addLog('AUTO-RESUME — restoring background bot state');try{AndroidBot?.startForegroundBot?.();}catch(_){} if(!connection)void connectSdk().then(()=>{if(connection){trading=true;stopRequested=false;persistTradingState();setStatus('BOT RUNNING — background execution enabled');}});}},800);\n"

p.write_text(s, encoding='utf-8')
print('Execution/background patch applied.')
