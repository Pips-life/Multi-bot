from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text(encoding='utf-8')

s = s.replace("const MIN_VELOCITY_PIPS=1;", "const MIN_VELOCITY_PIPS=0.10;")
s = s.replace("const MIN_VELOCITY_PIPS=0.35;", "const MIN_VELOCITY_PIPS=0.10;")
s = s.replace("const ENTRY_COOLDOWN_MS=3000;", "const ENTRY_COOLDOWN_MS=1000;")

if "function marketQuality(){" in s:
    start = s.index('function marketQuality(){')
    end = s.index('\nfunction updateBias()', start)
    s = s[:start] + s[end + 1:]

start = s.index('function evaluateMarket(mid,previous){')
end = s.index('\nfunction dynamicTrailPips', start)
evaluate = """function evaluateMarket(mid,previous){updateBias();if(!marketBias)return {action:'WAIT',reason:'building candle bias'};if(reversalConfirmed(marketBias,mid)){const old=marketBias;marketBias=old==='BUY'?'SELL':'BUY';pullbackActive=false;addLog(`DIRECTION CHANGE CONFIRMED — ${old} → ${marketBias}`);return {action:'BIAS_CHANGED',reason:'market structure broken'};}const against=marketBias==='BUY'?mid<previous:mid>previous;if(against){pullbackActive=true;return {action:'PULLBACK',reason:`${marketBias} bias retained`};}if(pullbackActive&&directionalVelocity(marketBias,mid,previous)){pullbackActive=false;return {action:'ENTRY',side:marketBias,reason:'pullback resumed with velocity'};}if(!pullbackActive&&directionalVelocity(marketBias,mid,previous))return {action:'ENTRY',side:marketBias,reason:'velocity expansion'};return {action:'WAIT',reason:`${marketBias} bias`};}"""
s = s[:start] + evaluate + s[end:]

if 'function symbolSpecification(){' not in s:
    marker = 'function brokerPipSize(){'
    helper = """function symbolSpecification(){try{const ts=connection?.terminalState;return ts&&typeof ts.specification==='function'?(ts.specification(SYMBOL)||{}):{};}catch(_){return {};}}\n"""
    s = s.replace(marker, helper + marker, 1)
s = re.sub(r"function brokerPipSize\(\)\{[^\n]*\}", "function brokerPipSize(){const spec=symbolSpecification();const p=Number(spec?.pipSize??spec?.point??0);return p>0?p:XAUUSD_PIP_SIZE_FALLBACK;}", s, count=1)
s = re.sub(r"function brokerDigits\(\)\{[^\n]*\}", "function brokerDigits(){const spec=symbolSpecification();const d=Number(spec?.digits??2);return Number.isFinite(d)?d:2;}", s, count=1)
s = re.sub(r"function currentVolume\(\)\{[^\n]*\}", "function currentVolume(){return normalizeVolume(EXECUTION_VOLUME,symbolSpecification()||{minVolume:.01,maxVolume:100,volumeStep:.01});}", s, count=1)

# MetaApi trade options: use only fields accepted by the market-order API.
# The magic field was causing the broker-side request to return Validation failed.
s = re.sub(r"function tradeOptions\(side\)\{[^\n]*\}", "function tradeOptions(side){return{comment:side==='BUY'?'MB_BUY':'MB_SELL',clientId:`MB_${side[0]}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2,7)}`};}", s, count=1)

entry_pattern = r"async function enter\(side,spot\)\{.*?\n(?=async function waitForNewPosition)"
entry = """function validateEntry(side,spot){\n  if(!connection)return {ok:false,reason:'MetaApi connection unavailable'};\n  if(!trading||stopRequested)return {ok:false,reason:'bot is not running'};\n  if(side!=='BUY'&&side!=='SELL')return {ok:false,reason:'invalid trade direction'};\n  const price=Number(spot);\n  if(!Number.isFinite(price)||price<=0)return {ok:false,reason:'invalid live XAUUSD price'};\n  const spec=symbolSpecification();\n  const volume=currentVolume();\n  const min=Number(spec?.minVolume??0.01),max=Number(spec?.maxVolume??100);\n  if(!Number.isFinite(volume)||volume<=0||volume<min||volume>max)return {ok:false,reason:'invalid XAUUSD execution volume'};\n  return {ok:true,price,volume};\n}\n\nasync function enter(side,spot){\n if(entryInFlight||!connection||!trading||stopRequested)return;\n if(Date.now()-lastEntryAt<ENTRY_COOLDOWN_MS)return;\n const check=validateEntry(side,spot);\n if(!check.ok){setStatus(`ENTRY BLOCKED — ${check.reason}`);return;}\n const volume=check.volume;\n entryInFlight=true;\n try{\n  const options=tradeOptions(side);\n  if(stopRequested||!trading)return;\n  if(side==='BUY')await connection.createMarketBuyOrder(SYMBOL,volume,undefined,undefined,options);\n  else await connection.createMarketSellOrder(SYMBOL,volume,undefined,undefined,options);\n  lastEntryAt=Date.now();\n  lastDirection=side;\n  setStatus(`OPEN ${side} ${volume} — applying independent protection`);\n  await waitForNewPosition(side,4000);\n  await reconcile();\n }catch(e){if(!stopRequested){const detail=e?.message||String(e);const code=e?.stringCode||e?.numericCode||'';const details=e?.details?` ${JSON.stringify(e.details)}`:'';setStatus(`Entry failed: ${detail}${code?` [${code}]`:''}${details}`);}}\n finally{entryInFlight=false;}\n}\n\n"""
s, count = re.subn(entry_pattern, entry, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('Pips-life entry validation patch could not locate enter()')

stop_pattern = r"async function setInitialStop\(position\)\{.*?\n(?=async function )"
stop = """async function setInitialStop(position,retries=4){\n const id=idOf(position);\n if(!id||stopActions.has(id)||!connection||stopRequested)return false;\n const side=sideOf(position),spot=side==='BUY'?Number(lastBid):Number(lastAsk);\n if(!Number.isFinite(spot)||spot<=0)return false;\n const candidate=normalizePrice(side==='BUY'?spot-TRAIL_PIPS*brokerPipSize():spot+TRAIL_PIPS*brokerPipSize());\n if(!Number.isFinite(candidate)||candidate<=0)return false;\n stopActions.add(id);\n try{\n  for(let attempt=1;attempt<=retries;attempt++){\n   if(stopRequested||!connection)return false;\n   try{\n    await connection.modifyPosition(id,candidate,undefined);\n    await new Promise(r=>setTimeout(r,100));\n    const live=(connection.terminalState?.positions||[]).find(p=>idOf(p)===id);\n    const confirmed=Number(live?.stopLoss??0);\n    const protectedOk=side==='BUY'?confirmed>0&&confirmed>=candidate:confirmed>0&&confirmed<=candidate;\n    if(protectedOk){\n     positionStops.set(id,confirmed);\n     position.stopLoss=confirmed;\n     addLog(`SL CONFIRMED ${id} ${side} ${fmt(confirmed)} (${attempt}/${retries})`);\n     return true;\n    }\n   }catch(e){\n    if(attempt===retries)addLog(`SL FAILED ${id}: ${e?.message||e}`);\n   }\n   await new Promise(r=>setTimeout(r,150*attempt));\n  }\n  addLog(`SL NOT CONFIRMED ${id} after ${retries} attempts`);\n  return false;\n }finally{stopActions.delete(id);}\n}\n\n"""
s, count = re.subn(stop_pattern, stop, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('Pips-life SL patch could not locate setInitialStop()')

s = s.replace("if(sideOf(p)&&!stopPrice&&!stopActions.has(id))void setInitialStop(p);", "if(sideOf(p)&&(!stopPrice||!positionStops.get(id))&&!stopActions.has(id))void setInitialStop(p,4);")

required = [
    "const MIN_VELOCITY_PIPS=0.10;",
    "const ENTRY_COOLDOWN_MS=1000;",
    "function evaluateMarket(mid,previous)",
    "function dynamicTrailPips(position,bid,ask)",
    "function validateEntry(side,spot)",
    "async function enter(side,spot)",
    "async function setInitialStop(position,retries=4)",
    "async function trailPosition(position,bid,ask)",
    "async function closeOnMomentumReversal(position,bid,ask)",
    "async function manageOpenPositions(bid,ask)",
    "const previous=lastMid;",
    "const decision=evaluateMarket(mid,previous);",
]
missing = [x for x in required if x not in s]
if missing:
    raise SystemExit('Pips-life execution validation failed: ' + ', '.join(missing))
if 'market noise filter' in s or 'MIN_CANDLE_RANGE_PIPS' in s or 'MIN_DIRECTIONAL_EFFICIENCY' in s:
    raise SystemExit('Noise-filter code is still present in canonical execution source')

p.write_text(s,encoding='utf-8')
print('Entry validation gate fixed and MetaApi market-order options normalized.')
