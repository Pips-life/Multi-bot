from pathlib import Path

# Release builds use the canonical Pips-life execution engine.
# Keep candle/range/efficiency noise filtering disabled while retaining a
# minimal broker-spread guard and direction bias.
p = Path('web/main.js')
s = p.read_text(encoding='utf-8')

s = s.replace("const MIN_VELOCITY_PIPS=1;", "const MIN_VELOCITY_PIPS=0.10;")
s = s.replace("const MIN_VELOCITY_PIPS=0.35;", "const MIN_VELOCITY_PIPS=0.10;")
s = s.replace("const ENTRY_COOLDOWN_MS=3000;", "const ENTRY_COOLDOWN_MS=1000;")

# If an older build source still contains the candle/range gate, remove it.
if "function marketQuality(){" in s:
    start=s.index('function marketQuality(){')
    end=s.index('\nfunction updateBias()',start)
    s=s[:start]+s[end+1:]

# Remove the old quality gate from evaluateMarket while preserving reversal,
# direction bias, pullback handling and velocity entry logic.
start=s.index('function evaluateMarket(mid,previous){')
end=s.index('\nfunction dynamicTrailPips',start)
evaluate="""function evaluateMarket(mid,previous){updateBias();if(!marketBias)return {action:'WAIT',reason:'building candle bias'};if(reversalConfirmed(marketBias,mid)){const old=marketBias;marketBias=old==='BUY'?'SELL':'BUY';pullbackActive=false;addLog(`DIRECTION CHANGE CONFIRMED — ${old} → ${marketBias}`);return {action:'BIAS_CHANGED',reason:'market structure broken'};}const move=(mid-previous)/brokerPipSize();const against=marketBias==='BUY'?move<0:move>0;if(against){pullbackActive=true;return {action:'PULLBACK',reason:`${marketBias} bias retained`};}if(pullbackActive&&directionalVelocity(marketBias,mid,previous)){pullbackActive=false;return {action:'ENTRY',side:marketBias,reason:'pullback resumed with velocity'};}if(!pullbackActive&&directionalVelocity(marketBias,mid,previous))return {action:'ENTRY',side:marketBias,reason:'velocity expansion'};return {action:'WAIT',reason:`${marketBias} bias`};}"""
s=s[:start]+evaluate+s[end:]

required=[
    "const MIN_VELOCITY_PIPS=0.10;",
    "const ENTRY_COOLDOWN_MS=1000;",
    "function evaluateMarket(mid,previous)",
    "function dynamicTrailPips(position,bid,ask)",
    "async function enter(side,spot)",
    "async function setInitialStop(position)",
    "async function trailPosition(position,bid,ask)",
    "async function closeOnMomentumReversal(position,bid,ask)",
    "async function manageOpenPositions(bid,ask)",
    "const previous=lastMid;",
    "const decision=evaluateMarket(mid,previous);",
]
missing=[x for x in required if x not in s]
if missing: raise SystemExit('Pips-life execution validation failed: '+', '.join(missing))
if 'market noise filter' in s or 'MIN_CANDLE_RANGE_PIPS' in s or 'MIN_DIRECTIONAL_EFFICIENCY' in s:
    raise SystemExit('Noise-filter code is still present in canonical execution source')

p.write_text(s,encoding='utf-8')
print('Noise filter removed; 0.10-pip velocity response and 1-second entry cooldown preserved for release builds.')