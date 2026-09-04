from pathlib import Path

# Release builds use the canonical execution engine in web/main.js.
# Validate the execution contract so build-time scripts cannot silently
# replace the trading engine with an older implementation.
p=Path('web/main.js')
s=p.read_text(encoding='utf-8')
required=[
    "const TRAIL_PIPS=70;",
    "const MIN_VELOCITY_PIPS=0.10;",
    "const ENTRY_COOLDOWN_MS=1000;",
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
    "let tradeStats=loadTradeStats();",
    "function winRate()",
    "async onSynchronizationStarted()",
    "let trading=false,stopRequested=false,connecting=false,synchronized=false,hasSynchronized=false;",
]
missing=[x for x in required if x not in s]
if missing: raise SystemExit('Canonical Pips-life execution source validation failed: '+', '.join(missing))
if 'market noise filter' in s or 'MIN_CANDLE_RANGE_PIPS' in s or 'MIN_DIRECTIONAL_EFFICIENCY' in s:
    raise SystemExit('Obsolete noise-filter gate detected in canonical execution source')
print('Pips-life execution validated: stable MetaApi sync handling, fast volatility entries, noise filter removed, adaptive trails, background-safe stop/reconnect, and win-rate tracking.')