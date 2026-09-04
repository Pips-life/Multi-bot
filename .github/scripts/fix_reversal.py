from pathlib import Path
import re

# Build-time guard for the current Pips-life trading engine.
# The broker stop may ONLY move in the profitable direction.  This patch adds
# a second, in-memory monotonic guard so a stale MetaApi position snapshot or
# overlapping tick cannot ever request a worse stop than the best stop already
# protected for that position.
path = Path('web/main.js')
s = path.read_text(encoding='utf-8')

required = [
    "const TRAIL_PIPS=70;",
    "function updateBiasState(mid)",
    "function entrySignal(mid)",
    "async function stopAllTrading()",
    "stopRequested=true;trading=false;",
    "await Promise.all(positions.map(p=>closePositionSafe(p)))",
]
missing = [item for item in required if item not in s]
if missing:
    raise SystemExit('Current Pips-life trading source validation failed: ' + ', '.join(missing))

# Add a monotonic per-position protection ledger once.
needle = "let entryInFlight=false,stopActionInFlight=false,reconcileInFlight=false;"
replacement = needle + "\nconst protectedStops=new Map();"
if "const protectedStops=new Map();" not in s:
    if needle not in s:
        raise SystemExit('Could not locate trading state declaration for protectedStops')
    s = s.replace(needle, replacement, 1)

# Replace the existing trail implementation with a monotonic version.
pattern = r"async function trail\(bid,ask\)\{.*?\n\}"
new_trail = r'''async function trail(bid,ask){
  if(!currentPosition||stopActionInFlight||stopRequested)return;
  const side=sideOf(currentPosition),positionId=idOf(currentPosition);
  if(!positionId||!side)return;
  const spot=side==='BUY'?bid:ask,candidate=stopCandidate(side,spot,brokerPipSize());
  if(!Number.isFinite(candidate)||candidate<=0)return;
  const brokerExisting=Number(currentPosition.stopLoss??0);
  const remembered=Number(protectedStops.get(positionId)??currentStop?.openPrice??0);
  const existing=Math.max(brokerExisting>0?brokerExisting:0,remembered>0?remembered:0);
  // Capital-protection invariant: BUY SL can only increase; SELL SL can only decrease.
  const improve=side==='BUY'?candidate>existing:candidate<existing;
  if(existing>0&&!improve)return;
  // Record the best protection BEFORE the async broker request. This prevents
  // overlapping ticks from racing and submitting a backwards stop.
  protectedStops.set(positionId,candidate);
  stopActionInFlight=true;
  try{
    const latest=Number(currentPosition?.stopLoss??0);
    const rememberedLatest=Number(protectedStops.get(positionId)??0);
    const floor= Math.max(latest>0?latest:0, rememberedLatest>0?rememberedLatest:0);
    const stillImproves=side==='BUY'?candidate>floor:candidate<floor;
    if(floor>0&&!stillImproves)return;
    await connection.modifyPosition(positionId,candidate,undefined);
    currentPosition.stopLoss=candidate;
    currentStop={id:positionId,openPrice:candidate};
    protectedStops.set(positionId,candidate);
    ui.stop.textContent=fmt(candidate);
  }catch(e){
    // Keep the remembered best stop even if a transient request fails.
    if(!stopRequested)setStatus(`SL trail failed: ${e?.message||e}`);
  }finally{stopActionInFlight=false;}
}'''
patched, count = re.subn(pattern, new_trail, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('Could not locate existing trail() implementation')
s = patched

# Keep the initial stop strictly initial: it must never overwrite an existing broker stop.
old = "const candidate=stopCandidate(side,spot,brokerPipSize());if(!Number.isFinite(candidate)||candidate<=0)return;stopActionInFlight=true;"
new = "const candidate=stopCandidate(side,spot,brokerPipSize());const existing=Number(position.stopLoss??currentStop?.openPrice??0);if(existing>0)return;if(!Number.isFinite(candidate)||candidate<=0)return;protectedStops.set(idOf(position),candidate);stopActionInFlight=true;"
if old in s:
    s = s.replace(old, new, 1)

path.write_text(s, encoding='utf-8')
print('Capital-protection trailing stop guard applied: SL may only improve and can never move backwards.')
