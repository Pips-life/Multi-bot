from pathlib import Path

# Remove candle/range/efficiency noise filtering from the canonical Pips-life
# execution engine. Direction bias and the broker spread guard remain.
p = Path('web/main.js')
s = p.read_text(encoding='utf-8')

s = s.replace("const MIN_VELOCITY_PIPS=0.35;", "const MIN_VELOCITY_PIPS=1;")
s = s.replace("const ENTRY_COOLDOWN_MS=3000;", "const ENTRY_COOLDOWN_MS=1000;")
s = s.replace("const MIN_CANDLE_RANGE_PIPS=4;", "const MIN_CANDLE_RANGE_PIPS=0;")
s = s.replace("const MIN_DIRECTIONAL_EFFICIENCY=0.22;", "const MIN_DIRECTIONAL_EFFICIENCY=0;")
s = s.replace("const MAX_SPREAD_PIPS=8;", "const MAX_SPREAD_PIPS=12;")

start = s.index('function marketQuality(){')
end = s.index('\nfunction updateBias()', start)
s = s[:start] + "function marketQuality(){const pip=brokerPipSize();const cs=closedCandles().slice(-8);const ranges=cs.map(c=>(Number(c.high)-Number(c.low))/pip);const avgRange=ranges.length?ranges.reduce((a,b)=>a+b,0)/ranges.length:0;const net=cs.length?Math.abs(Number(cs.at(-1).close)-Number(cs[0].open))/pip:0;const path=cs.reduce((v,c)=>v+Math.abs(Number(c.close)-Number(c.open)),0)/pip;const efficiency=path>0?net/path:0;const spread=(lastAsk-lastBid)/pip;return {ok:!Number.isFinite(spread)||spread<=MAX_SPREAD_PIPS,avgRange,efficiency,spread};}" + s[end:]

start = s.index('function evaluateMarket(mid,previous){')
end = s.index('\nfunction dynamicTrailPips', start)
s = s[:start] + "function evaluateMarket(mid,previous){updateBias();if(!marketBias)return {action:'WAIT',reason:'building candle bias'};const quality=marketQuality();if(!quality.ok)return {action:'WAIT',reason:`spread filter — ${fmt(quality.spread)}p`};if(reversalConfirmed(marketBias,mid)){const old=marketBias;marketBias=old==='BUY'?'SELL':'BUY';pullbackActive=false;addLog(`DIRECTION CHANGE CONFIRMED — ${old} → ${marketBias}`);return {action:'BIAS_CHANGED',reason:'market structure broken'};}const pip=brokerPipSize();const counterMove=(mid-previous)/pip;const against=marketBias==='BUY'?counterMove<=-3:counterMove>=3;if(against){pullbackActive=true;return {action:'PULLBACK',reason:`${marketBias} bias retained after ${fmt(Math.abs(counterMove))}p pullback`};}if(pullbackActive&&directionalVelocity(marketBias,mid,previous)){pullbackActive=false;return {action:'ENTRY',side:marketBias,reason:'pullback resumed with 1-pip velocity'};}if(!pullbackActive&&directionalVelocity(marketBias,mid,previous))return {action:'ENTRY',side:marketBias,reason:'micro velocity aligned with bias'};return {action:'WAIT',reason:`${marketBias} bias`};}" + s[end:]

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
print('Noise filter removed: no candle-range or directional-efficiency entry gate; 1-pip aligned movement executes, spread guard retained, direction bias and reversal logic preserved.')
