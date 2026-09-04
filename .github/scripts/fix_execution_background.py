from pathlib import Path

# Release builds use the canonical execution engine in web/main.js.
# Validate the source rather than rewriting it, so the APK matches the committed code.
p = Path('web/main.js')
s = p.read_text(encoding='utf-8')
required = [
    "const TRAIL_PIPS=70;",
    "function evaluateMarket(mid)",
    "function scheduleReconnect()",
    "async function enter(side,spot)",
    "createMarketBuyOrder(SYMBOL,volume,undefined,undefined,options)",
    "createMarketSellOrder(SYMBOL,volume,undefined,undefined,options)",
    "async function setInitialStop(position)",
    "function stopAllTrading()",
    "stopRequested=true;trading=false;",
    "await Promise.all(positions.map(p=>closePositionSafe(p)))",
]
missing = [x for x in required if x not in s]
if missing:
    raise SystemExit('Canonical Pips-life execution source validation failed: ' + ', '.join(missing))
print('Pips-life execution source validated; no build-time source rewrite required.')
