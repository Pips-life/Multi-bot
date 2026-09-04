from pathlib import Path

# Release builds use the canonical execution engine in web/main.js.
# This validator must never rewrite the trading engine. Previous versions
# searched for an obsolete single-position implementation and then failed
# or attempted to inject stale symbols such as currentPosition/trail.
p = Path('web/main.js')
s = p.read_text(encoding='utf-8')
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

# Explicitly reject the obsolete execution names that caused the previous
# build-time patch to target the wrong engine.
for stale in ('currentPosition','await trail(bid,ask)'):
    if stale in s:
        raise SystemExit('Stale execution implementation detected: ' + stale)

print('Pips-life pullback execution validated; canonical direction-first engine preserved with no build-time rewrite.')
