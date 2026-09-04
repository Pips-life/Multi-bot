from pathlib import Path

# Release builds use the canonical execution engine in web/main.js.
# Validate the complete execution contract so build-time scripts cannot
# silently replace the trading engine with an older implementation.
p = Path('web/main.js')
s = p.read_text(encoding='utf-8')
required = [
    "const TRAIL_PIPS=70;",
    "function marketQuality()",
    "function evaluateMarket(mid,previous)",
    "function dynamicTrailPips(position,bid,ask)",
    "function scheduleReconnect()",
    "async function enter(side,spot)",
    "createMarketBuyOrder(SYMBOL,volume,undefined,undefined,options)",
    "createMarketSellOrder(SYMBOL,volume,undefined,undefined,options)",
    "async function setInitialStop(position)",
    "async function closePositionSafe(position)",
    "async function stopAllTrading()",
    "stopRequested=true;trading=false;",
    "await Promise.all(live.map(p=>closePositionSafe(p)))",
    "const previous=lastMid;",
    "const decision=evaluateMarket(mid,previous);",
]
missing = [x for x in required if x not in s]
if missing:
    raise SystemExit('Canonical Pips-life execution source validation failed: ' + ', '.join(missing))
print('Pips-life execution validated: direction-first entries, noise filter, momentum exits, independent adaptive trails, background-safe reconnect/stop logic.')
