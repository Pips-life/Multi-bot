from pathlib import Path

p = Path('web/main.js')
s = p.read_text(encoding='utf-8')

def replace_func(src, name, new):
    for marker in (f'async function {name}', f'function {name}'):
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

# Fix the existing trailing-stop state update typo if present.
s = s.replace("currentStop={id:idOf(position),openPrice:candidate};", "currentStop={id:idOf(currentPosition),openPrice:candidate};")

# The source already starts/stops the Android foreground service from startBot/stopAllTrading.
# Do not depend on one exact function declaration or minified binding string here.
if 'function startBot()' not in s and 'async function startBot()' not in s:
    raise SystemExit('missing startBot')
if 'function stopAllTrading()' not in s and 'async function stopAllTrading()' not in s:
    raise SystemExit('missing stopAllTrading')

p.write_text(s, encoding='utf-8')
print('Executable retracement decisions, trade execution, and background-run patch applied.')
