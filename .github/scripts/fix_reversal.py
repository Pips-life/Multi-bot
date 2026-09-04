from pathlib import Path

# Compatibility validation for the current Pips-life trading engine.
# The reversal/trailing logic is committed directly to web/main.js.
# This step must never modify the source; it only verifies that the current
# engine contains the expected entry/trailing/stop-control implementation.
path = Path('web/main.js')
s = path.read_text(encoding='utf-8')
required = [
    "const TRAIL_PIPS = 70;",
    "function updateBiasState(mid)",
    "function entrySignal(mid)",
    "async function stopAllTrading()",
    "stopRequested=true;trading=false;",
    "await Promise.all(positions.map(p=>closePositionSafe(p)))",
]
missing = [item for item in required if item not in s]
if missing:
    raise SystemExit('Current Pips-life trading source validation failed: ' + ', '.join(missing))
print('Current Pips-life trading source validated: direction-bias, retracement-aware entry, 70-pip trailing SL and Stop Bot controls present.')
