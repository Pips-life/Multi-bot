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

start_old = '''async function startBot(){'''
start_i = s.find(start_old)
if start_i < 0:
    raise SystemExit('missing startBot')
# Preserve the existing start logic but guarantee the foreground service is started first.
start_b = s.find('{', start_i)
start_depth = 0
start_quote = None
start_esc = False
for j in range(start_b, len(s)):
    ch=s[j]
    if start_quote:
        if start_esc: start_esc=False
        elif ch=='\\': start_esc=True
        elif ch==start_quote: start_quote=None
        continue
    if ch in "'\"`": start_quote=ch; continue
    if ch=='{': start_depth+=1
    elif ch=='}':
        start_depth-=1
        if start_depth==0:
            old_start=s[start_i:j+1]
            break
else:
    raise SystemExit('unclosed startBot')
if 'AndroidBot?.startForegroundBot' not in old_start:
    new_start=old_start.replace('{','{try{AndroidBot?.startForegroundBot?.();}catch(_){}',1)
    s=s.replace(old_start,new_start,1)

# Guarantee STOP BOT clears trading and removes the foreground service after all close requests.
stop_old_marker='async function stopAllTrading()'
stop_i=s.find(stop_old_marker)
if stop_i<0: raise SystemExit('missing stopAllTrading')
stop_b=s.find('{',stop_i)
depth=0;quote=None;esc=False
for j in range(stop_b,len(s)):
    ch=s[j]
    if quote:
        if esc: esc=False
        elif ch=='\\': esc=True
        elif ch==quote: quote=None
        continue
    if ch in "'\"`": quote=ch; continue
    if ch=='{': depth+=1
    elif ch=='}':
        depth-=1
        if depth==0:
            old_stop=s[stop_i:j+1]
            break
else: raise SystemExit('unclosed stopAllTrading')
if 'AndroidBot?.stopForegroundBot' not in old_stop:
    new_stop=old_stop.replace('{','{try{AndroidBot?.stopForegroundBot?.();}catch(_){}',1)
    s=s.replace(old_stop,new_stop,1)

p.write_text(s, encoding='utf-8')
print('Executable retracement decisions and enforced foreground/background execution patch applied.')
