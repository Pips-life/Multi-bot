from pathlib import Path

# The 70-pip trailing-SL implementation is now committed directly to web/main.js.
# Keep this legacy build step harmless for older workflow revisions.
path = Path('web/main.js')
s = path.read_text()
if 'const TRAIL_PIPS = 70;' in s and 'function scheduleReentry' in s:
    print('Direct 70-pip trailing-SL logic already present; no patch needed.')
else:
    raise SystemExit('Expected current Pips-life trailing-SL source was not found')
