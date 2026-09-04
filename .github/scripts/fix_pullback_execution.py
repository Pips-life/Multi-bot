from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text(encoding='utf-8')

# The prior tick was being overwritten before evaluateMarket() ran, which
# made directional velocity/pullback detection effectively see zero movement.
# This patch passes the true previous tick into the decision engine and makes
# candle pullbacks into the latest closed impulse candle executable immediately.
old = re.search(r"function directionalVelocity\(side,mid\)\{.*?\n\nclass BotListener", s, re.S)
if not old:
    raise SystemExit('Could not locate directional decision block')

new = r'''function directionalVelocity(side,mid,previousMid){
  if(!Number.isFinite(previousMid)||!Number.isFinite(mid))return false;
  const delta=(mid-previousMid)/brokerPipSize();
  return side==='BUY'?delta>=MIN_VELOCITY_PIPS:delta<=-MIN_VELOCITY_PIPS;
}
function pullbackEntry(side,mid,previousMid){
  const cs=closedCandles();
  if(cs.length<2||!Number.isFinite(mid)||!Number.isFinite(previousMid))return false;
  const impulse=cs[cs.length-1];
  const o=Number(impulse.open),c=Number(impulse.close);
  if(!Number.isFinite(o)||!Number.isFinite(c))return false;
  // BUY bias: the next candle retraces downward into the prior bullish
  // candle's body. Enter on that touch; do not wait for the bounce.
  if(side==='BUY'&&c>o)return previousMid>mid&&mid<=c&&mid>=o;
  // SELL bias: the next candle retraces upward into the prior bearish body.
  if(side==='SELL'&&c<o)return previousMid<mid&&mid>=c&&mid<=o;
  return false;
}
function evaluateMarket(mid,previousMid){
  updateBias();
  if(!marketBias)return {action:'WAIT',reason:'building candle bias'};

  // A structural break has priority. Ordinary counter-direction candles are
  // treated as pullbacks while the bias remains intact.
  if(reversalConfirmed(marketBias,mid)){
    const old=marketBias;
    marketBias=old==='BUY'?'SELL':'BUY';
    pullbackActive=false;
    addLog(`DIRECTION CHANGE CONFIRMED — ${old} → ${marketBias}`);
    return {action:'BIAS_CHANGED',reason:'market structure broken'};
  }

  // Core Pips-life entry rule: trade the pullback in the existing bias.
  if(pullbackEntry(marketBias,mid,previousMid)){
    pullbackActive=true;
    return {action:'ENTRY',side:marketBias,reason:`${marketBias} pullback into prior impulse candle`};
  }

  const against=marketBias==='BUY'?mid<previousMid:mid>previousMid;
  if(against){
    pullbackActive=true;
    return {action:'PULLBACK',reason:`${marketBias} bias — retracement monitored for entry`};
  }

  if(pullbackActive&&directionalVelocity(marketBias,mid,previousMid)){
    pullbackActive=false;
    return {action:'ENTRY',side:marketBias,reason:'pullback resumed with velocity'};
  }
  if(!pullbackActive&&directionalVelocity(marketBias,mid,previousMid))return {action:'ENTRY',side:marketBias,reason:'bias-aligned velocity'};
  return {action:'WAIT',reason:`${marketBias} bias`};
}

class BotListener'''
s = s[:old.start()] + new + s[old.end():]

old_tick = re.search(r"async function onTick\(mid,bid,ask\)\{.*?\n\}\nasync function cancelOrder", s, re.S)
if not old_tick:
    raise SystemExit('Could not locate onTick block')
new_tick = r'''async function onTick(mid,bid,ask){
  if(!trading||stopRequested||!synchronized)return;
  const previous=lastMid;
  if(currentPosition){lastMid=mid;await trail(bid,ask);return;}
  if(!Number.isFinite(previous)||mid===previous){lastMid=mid;return;}
  const decision=evaluateMarket(mid,previous);
  lastMid=mid;
  if(decision.action==='PULLBACK'){
    lastDirection=marketBias;
    setStatus(`PULLBACK — ${marketBias} bias retained — watching impulse zone`);
    return;
  }
  if(decision.action==='BIAS_CHANGED'){
    lastDirection=marketBias;
    setStatus(`BIAS CHANGED — now ${marketBias} — watching for aligned entry`);
    return;
  }
  if(decision.action==='ENTRY'){
    lastDirection=decision.side;
    setStatus(`${decision.side} ENTRY — ${decision.reason} — executing immediately`);
    await enter(decision.side,decision.side==='BUY'?ask:bid);
  }
}
async function cancelOrder'''
s = s[:old_tick.start()] + new_tick + s[old_tick.end():]

# Keep the release validator honest about the new executable decision path.
checks = [
    "function pullbackEntry(side,mid,previousMid)",
    "function evaluateMarket(mid,previousMid)",
    "const previous=lastMid;",
    "evaluateMarket(mid,previous)",
    "PULLBACK — ${marketBias} bias retained — watching impulse zone",
]
missing=[x for x in checks if x not in s]
if missing:
    raise SystemExit('Pullback execution patch validation failed: '+', '.join(missing))

p.write_text(s,encoding='utf-8')
print('Applied executable bias-aligned candle pullback entry and fixed previous-tick handling.')
