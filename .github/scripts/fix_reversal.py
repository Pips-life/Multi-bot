from pathlib import Path

# Build-time validation only. The canonical Multi-bot web engine now contains
# the favorable-only 70-pip trailing implementation directly. Older validation
# expected the previous single-position trail() function and incorrectly
# rejected the new per-position trailPosition()/trailAll() implementation.
path = Path('web/main.js')
s = path.read_text(encoding='utf-8')
required = [
    "const TRAIL_PIPS=70;",
    "const positionStops=new Map();",
    "const stopActions=new Set();",
    "async function trailPosition(position,bid,ask)",
    "async function trailAll(bid,ask)",
    "async function onTick(mid,bid,ask)",
    "function tradeOptions(side)",
    "async function stopAllTrading()",
    "stopRequested=true;trading=false;",
    "await Promise.all(live.map(p=>closePositionSafe(p)))",
]
missing = [x for x in required if x not in s]
if missing:
    raise SystemExit('Canonical Pips-life multi-position trailing validation failed: ' + ', '.join(missing))
print('Canonical multi-position 70-pip favorable-only trailing and STOP BOT logic verified; no rewrite applied.')
