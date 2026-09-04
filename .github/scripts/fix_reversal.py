from pathlib import Path
import re

# Build-time guard for the current Pips-life trading engine.
# The broker stop may ONLY move in the profitable direction. This patch adds
# a per-position monotonic guard so stale snapshots and overlapping ticks
# cannot request a less-protective stop.
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

needle = "let entryInFlight=false,stopActionInFlight=false,reconcileInFlight=false;"
if "const protectedStops=new Map();" not in s:
    if needle not in s:
        raise SystemExit('Could not locate trading state declaration for protectedStops')
    s = s.replace(needle, needle + "\nconst protectedStops=new Map();", 1)

# trail() is minified onto one physical line in the current source.
# Match the function from its signature through the stable onTick boundary.
trail_pattern = r"async function trail\(bid,ask\)\{.*?\}\nasync function onTick"
new_trail = '''async function trail(bid,ask){
  if(!currentPosition||stopActionInFlight||stopRequested)return;
  const side=sideOf(currentPosition),positionId=idOf(currentPosition);
  if(!positionId||!side)return;
  const spot=side==='BUY'?bid:ask,candidate=stopCandidate(side,spot,brokerPipSize());
  if(!Number.isFinite(candidate)||candidate<=0)return;
  const brokerExisting=Number(currentPosition.stopLoss??0);
  const remembered=Number(protectedStops.get(positionId)??currentStop?.openPrice??0);
  const existing=side==='BUY'
    ? Math.max(brokerExisting>0?brokerExisting:0,remembered>0?remembered:0)
    : (brokerExisting>0&&remembered>0?Math.min(brokerExisting,remembered):(brokerExisting>0?brokerExisting:remembered));
  const improve=side==='BUY'?candidate>existing:candidate<existing;
  if(existing>0&&!improve)return;
  protectedStops.set(positionId,candidate);
  stopActionInFlight=true;
  try{
    const latest=Number(currentPosition?.stopLoss??0);
    const rememberedLatest=Number(protectedStops.get(positionId)??0);
    const floor=side==='BUY'
      ? Math.max(latest>0?latest:0,rememberedLatest>0?rememberedLatest:0)
      : (latest>0&&rememberedLatest>0?Math.min(latest,rememberedLatest):(latest>0?latest:rememberedLatest));
    const stillImproves=side==='BUY'?candidate>floor:candidate<floor;
    if(floor>0&&!stillImproves)return;
    await connection.modifyPosition(positionId,candidate,undefined);
    currentPosition.stopLoss=candidate;
    currentStop={id:positionId,openPrice:candidate};
    protectedStops.set(positionId,candidate);
    ui.stop.textContent=fmt(candidate);
  }catch(e){
    if(!stopRequested)setStatus(`SL trail failed: ${e?.message||e}`);
  }finally{stopActionInFlight=false;}
}
async function onTick'''
s, count = re.subn(trail_pattern, new_trail, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('Could not locate existing trail() implementation at its onTick boundary')

# Never overwrite a broker-provided initial stop.
initial_old = "const candidate=stopCandidate(side,spot,brokerPipSize());if(!Number.isFinite(candidate)||candidate<=0)return;stopActionInFlight=true;"
initial_new = "const candidate=stopCandidate(side,spot,brokerPipSize());const existing=Number(position.stopLoss??currentStop?.openPrice??0);if(existing>0)return;if(!Number.isFinite(candidate)||candidate<=0)return;protectedStops.set(idOf(position),candidate);stopActionInFlight=true;"
if initial_old in s:
    s = s.replace(initial_old, initial_new, 1)

path.write_text(s, encoding='utf-8')
print('Pips-life capital-protection guard applied: trailing SL can only improve and can never move backwards.')
