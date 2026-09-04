from pathlib import Path

# Build-time validation only. The canonical Multi-bot web engine now contains
# the favorable-only 70-pip trailing implementation directly. Do not rewrite
# it during builds, because older patch scripts could reintroduce incompatible
# entry/reversal behavior.
path = Path('web/main.js')
s = path.read_text(encoding='utf-8')
required = [
    "const TRAIL_PIPS=70;",
    "async function trail(bid,ask)",
    "async function onTick(mid,bid,ask)",
    "function tradeOptions(side)",
    "function stopAllTrading()",
    "stopRequested=true;trading=false;",
    "await Promise.all(positions.map(p=>closePositionSafe(p)))",
]
missing=[x for x in required if x not in s]
if missing:
    raise SystemExit('Canonical Pips-life trailing source validation failed: ' + ', '.join(missing))
print('Canonical 70-pip favorable-only trailing and STOP BOT logic verified; no rewrite applied.')
