from pathlib import Path

# Release builds use the canonical execution engine in web/main.js.
# This script is validation-only. The previous implementation rewrote the
# engine using obsolete single-position symbols and could undo working
# execution logic during every APK build.
p = Path('web/main.js')
s = p.read_text(encoding='utf-8')
required = [
    "async function connectSdk(force=false)",
    "async onConnected()",
    "async onDisconnected()",
    "async onSynchronizationStarted()",
    "async onSynchronizationFinished()",
    "await connection.connect();await connection.waitSynchronized();",
    "await connection.subscribeToMarketData(SYMBOL",
    "async function enter(side,spot)",
    "async function manageOpenPositions(bid,ask)",
    "async function stopAllTrading()",
]
missing=[x for x in required if x not in s]
if missing:
    raise SystemExit('Start/connection execution validation failed: '+', '.join(missing))

for stale in ('currentPosition','await trail(bid,ask)'):
    if stale in s:
        raise SystemExit('Stale execution implementation detected: '+stale)

print('Pips-life connection/execution source validated; no build-time rewrite applied.')
