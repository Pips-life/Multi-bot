from pathlib import Path
import re

# Tune the canonical Pips-life engine for XAUUSD micro-movement capture.
# This deliberately relaxes the previous candle-quality gate while keeping
# direction bias, spread protection, independent position management and the
# existing MetaApi execution functions intact.
p = Path('web/main.js')
s = p.read_text(encoding='utf-8')

# XAUUSD on HFM uses a 0.01 minimum price increment. Treat one real pip/point
# as the smallest actionable movement instead of requiring a larger expansion.
s = s.replace("const MIN_VELOCITY_PIPS=0.35;", "const MIN_VELOCITY_PIPS=1;")
s = s.replace("const ENTRY_COOLDOWN_MS=3000;", "const ENTRY_COOLDOWN_MS=1000;")
s = s.replace("const MIN_CANDLE_RANGE_PIPS=4;", "const MIN_CANDLE_RANGE_PIPS=0;")
s = s.replace("const MIN_DIRECTIONAL_EFFICIENCY=0.22;", "const MIN_DIRECTIONAL_EFFICIENCY=0;")
s = s.replace("const MAX_SPREAD_PIPS=8;", "const MAX_SPREAD_PIPS=12;")

# Make market quality a soft context filter. Spread remains the hard execution
# guard; candle range/efficiency no longer prevent micro entries.
old_quality = "function marketQuality(){const cs=closedCandles().slice(-8),pip=brokerPipSize();if(cs.length<4)return {ok:false,reason:'building market context'};const ranges=cs.map(c=>(Number(c.high)-Number(c.low))/pip),avgRange=ranges.reduce((a,b)=>a+b,0)/ranges.length;const net=Math.abs(Number(cs.at(-1).close)-Number(cs[0].open))/pip;const path=cs.reduce((s,c)=>s+Math.abs(Number(c.close)-Number(c.open)),0)/pip;const efficiency=path>0?net/path:0;const spread=(lastAsk-lastBid)/pip;return {ok:avgRange>=MIN_CANDLE_RANGE_PIPS&&efficiency>=MIN_DIRECTIONAL_EFFICIENCY&&(!Number.isFinite(spread)||spread<=MAX_SPREAD_PIPS),avgRange,efficiency,spread};}"
new_quality = "function marketQuality(){const cs=closedCandles().slice(-8),pip=brokerPipSize();const ranges=cs.map(c=>(Number(c.high)-Number(c.low))/pip),avgRange=ranges.length?ranges.reduce((a,b)=>a+b,0)/ranges.length:0;const net=cs.length?Math.abs(Number(cs.at(-1).close)-Number(cs[0].open))/pip:0;const path=cs.reduce((s,c)=>s+Math.abs(Number(c.close)-Number(c.open)),0)/pip;const efficiency=path>0?net/path:0;const spread=(lastAsk-lastBid)/pip;return {ok:!Number.isFinite(spread)||spread<=MAX_SPREAD_PIPS,avgRange,efficiency,spread};}"
if old_quality not in s:
    raise SystemExit('Expected marketQuality implementation not found; refusing to patch unknown execution source')
s = s.replace(old_quality, new_quality, 1)

# Do not treat a one-pip counter-tick as a full pullback. A pullback must be
# at least 3 pips against the established bias; this leaves small oscillations
# available for micro continuation entries.
old_eval = "function evaluateMarket(mid,previous){updateBias();if(!marketBias)return {action:'WAIT',reason:'building candle bias'};const quality=marketQuality();if(!quality.ok)return {action:'WAIT',reason:`market noise filter — range ${fmt(quality.avgRange)}p efficiency ${fmt(quality.efficiency)}`};if(reversalConfirmed(marketBias,mid)){const old=marketBias;marketBias=old==='BUY'?'SELL':'BUY';pullbackActive=false;addLog(`DIRECTION CHANGE CONFIRMED — ${old} → ${marketBias}`);return {action:'BIAS_CHANGED',reason:'market structure broken'};}const against=marketBias==='BUY'?mid<previous:mid>previous;if(against){pullbackActive=true;return {action:'PULLBACK',reason:`${marketBias} bias retained`};}if(pullbackActive&&directionalVelocity(marketBias,mid,previous)){pullbackActive=false;return {action:'ENTRY',side:marketBias,reason:'pullback resumed with velocity'};}if(!pullbackActive&&directionalVelocity(marketBias,mid,previous))return {action:'ENTRY',side:marketBias,reason:'bias-aligned expansion'};return {action:'WAIT',reason:`${marketBias} bias`};}"
new_eval = "function evaluateMarket(mid,previous){updateBias();if(!marketBias)return {action:'WAIT',reason:'building candle bias'};const quality=marketQuality();if(!quality.ok)return {action:'WAIT',reason:`spread filter — ${fmt(quality.spread)}p`};if(reversalConfirmed(marketBias,mid)){const old=marketBias;marketBias=old==='BUY'?'SELL':'BUY';pullbackActive=false;addLog(`DIRECTION CHANGE CONFIRMED — ${old} → ${marketBias}`);return {action:'BIAS_CHANGED',reason:'market structure broken'};}const pip=brokerPipSize();const counterMove=(mid-previous)/pip;const against=marketBias==='BUY'?counterMove<=-3:counterMove>=3;if(against){pullbackActive=true;return {action:'PULLBACK',reason:`${marketBias} bias retained after ${fmt(Math.abs(counterMove))}p pullback`};}if(pullbackActive&&directionalVelocity(marketBias,mid,previous)){pullbackActive=false;return {action:'ENTRY',side:marketBias,reason:'pullback resumed with 1-pip velocity'};}if(!pullbackActive&&directionalVelocity(marketBias,mid,previous))return {action:'ENTRY',side:marketBias,reason:'micro velocity aligned with bias'};return {action:'WAIT',reason:`${marketBias} bias`};}"
if old_eval not in s:
    raise SystemExit('Expected evaluateMarket implementation not found; refusing to patch unknown execution source')
s = s.replace(old_eval, new_eval, 1)

required = [
    "function marketQuality()",
    "function evaluateMarket(mid,previous)",
    "function dynamicTrailPips(position,bid,ask)",
    "async function enter(side,spot)",
    "createMarketBuyOrder(SYMBOL,volume,undefined,undefined,options)",
    "createMarketSellOrder(SYMBOL,volume,undefined,undefined,options)",
    "async function setInitialStop(position)",
    "async function trailPosition(position,bid,ask)",
    "async function closeOnMomentumReversal(position,bid,ask)",
    "async function manageOpenPositions(bid,ask)",
    "const previous=lastMid;",
    "const decision=evaluateMarket(mid,previous);",
]
missing = [x for x in required if x not in s]
if missing:
    raise SystemExit('Pullback execution source validation failed: ' + ', '.join(missing))

for stale in ('currentPosition','await trail(bid,ask)'):
    if stale in s:
        raise SystemExit('Stale execution implementation detected: ' + stale)

p.write_text(s, encoding='utf-8')
print('Pips-life XAUUSD micro-movement execution tuned: 1-pip aligned entries, 1s cooldown, soft candle filter, spread guard retained, independent execution preserved.')
