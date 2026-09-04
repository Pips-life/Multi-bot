from pathlib import Path

# Build-time guard for the canonical Pips-life Multi-bot engine.
# The actual source now owns instant tick-velocity execution. This script must
# NOT rewrite entry logic during an APK build, because doing so would restore
# the older candle/bias/retracement gate.
p = Path('web/main.js')
s = p.read_text(encoding='utf-8')
required = [
    "const TRAIL_PIPS=70;",
    "INSTANT VELOCITY EXPANSION",
    "async function onTick(mid,bid,ask)",
    "async function enter(side,spot)",
    "function stopAllTrading()",
    "stopRequested=true;trading=false;",
    "await Promise.all(positions.map(p=>closePositionSafe(p)))",
]
missing=[x for x in required if x not in s]
if missing:
    raise SystemExit('Canonical Pips-life execution source validation failed: ' + ', '.join(missing))
print('Canonical instant velocity expansion execution verified; no rewrite applied.')
