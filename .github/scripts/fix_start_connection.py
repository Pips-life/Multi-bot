from pathlib import Path

js = Path('web/main.js')
h = Path('web/index.html')
s = js.read_text(encoding='utf-8')
html = h.read_text(encoding='utf-8')

# Starting the bot must never tear down a connection that is already
# synchronized. Preserve a healthy streaming connection instead.
old = "  if(connection&&!force)return;\n"
new = "  if(connection&&synchronized)return;\n  if(connection&&!force)return;\n"
if old not in s:
    raise SystemExit('Could not locate connectSdk connection guard')
s = s.replace(old, new, 1)

# MetaApi can perform an internal resynchronization while an established
# stream remains connected. Do not falsely drop the local synchronized state
# during that refresh; a real socket disconnect is still handled separately.
old = "  async onSynchronizationStarted(){synchronized=false;setStatus('Synchronizing MetaApi terminal…');}"
new = "  async onSynchronizationStarted(){if(synchronized){setStatus('MetaApi terminal refresh in progress…');return;}synchronized=false;setStatus('Synchronizing MetaApi terminal…');}"
if old not in s:
    raise SystemExit('Could not locate synchronization-start handler')
s = s.replace(old, new, 1)

# Add a home-screen win-rate binding.
old = "const ui={token:$('token'),account:$('account'),price:$('price'),balance:$('balance'),position:$('position'),stop:$('stop'),status:$('status'),save:$('save'),change:$('change'),start:$('start'),stopBot:$('stop')};"
new = "const ui={token:$('token'),account:$('account'),price:$('price'),balance:$('balance'),winRate:$('winRate'),position:$('position'),stop:$('stop'),status:$('status'),save:$('save'),change:$('change'),start:$('start'),stopBot:$('stop')};"
if old not in s:
    raise SystemExit('Could not locate UI bindings')
s = s.replace(old, new, 1)

anchor = "const eventLog=[],sessionHistory=[];\nlet lastStatus='';"
replacement = "const eventLog=[],sessionHistory=[];\nlet lastStatus='';\nlet winRate=NaN,winCount=0,lossCount=0,winRateRefreshInFlight=false,winRateTimer=null;\n\nfunction dealBelongsToBot(deal){\n  if(!deal||deal.symbol!==SYMBOL)return false;\n  return Number(deal.magic)===MAGIC||String(deal.clientId??'').startsWith('MB_')||String(deal.comment??'').startsWith('MB_');\n}\nfunction isClosingDeal(deal){\n  const entry=String(deal?.entryType??deal?.entry??deal?.entry_type??'').toUpperCase();\n  return entry.includes('OUT')||entry.includes('INOUT');\n}\nfunction dealNet(deal){\n  return Number(deal?.profit??0)+Number(deal?.commission??0)+Number(deal?.swap??0);\n}\nasync function refreshWinRate(){\n  if(winRateRefreshInFlight||!connection)return;\n  const storage=connection.historyStorage;\n  if(!storage)return;\n  winRateRefreshInFlight=true;\n  try{\n    let deals=Array.isArray(storage.deals)?storage.deals.slice():[];\n    if(!deals.length&&typeof connection.getDealsByTimeRange==='function'){\n      try{deals=await connection.getDealsByTimeRange(new Date(Date.now()-90*24*60*60*1000),new Date());}catch(_){}\n    }\n    const grouped=new Map();\n    for(const deal of deals){\n      if(!dealBelongsToBot(deal)||!isClosingDeal(deal))continue;\n      const positionId=String(deal.positionId??deal.positionID??deal.position??deal.id??'');\n      if(!positionId)continue;\n      grouped.set(positionId,(grouped.get(positionId)||0)+dealNet(deal));\n    }\n    let wins=0,losses=0;\n    for(const net of grouped.values()){if(net>0)wins++;else if(net<0)losses++;}\n    winCount=wins;lossCount=losses;const total=wins+losses;winRate=total?wins/total*100:NaN;\n    if(ui.winRate)ui.winRate.textContent=Number.isFinite(winRate)?`${winRate.toFixed(1)}%`:'—';\n    renderPageData();\n  }finally{winRateRefreshInFlight=false;}\n}\nfunction startWinRateMonitor(){\n  clearInterval(winRateTimer);\n  void refreshWinRate();\n  winRateTimer=setInterval(()=>void refreshWinRate(),5000);\n}\nfunction stopWinRateMonitor(){clearInterval(winRateTimer);winRateTimer=null;}"
if anchor not in s:
    raise SystemExit('Could not locate state declarations')
s = s.replace(anchor, replacement, 1)

# Refresh win rate after synchronization and after a position closes.
s = s.replace("async onSynchronizationFinished(){synchronized=true;reconnectAttempt=0;clearTimeout(reconnectTimer);reconnectTimer=null;setStatus(`CONNECTED — ${SYMBOL} live stream active — bias ${marketBias||'CALCULATING'}`);void reconcile();}", "async onSynchronizationFinished(){synchronized=true;reconnectAttempt=0;clearTimeout(reconnectTimer);reconnectTimer=null;setStatus(`CONNECTED — ${SYMBOL} live stream active — bias ${marketBias||'CALCULATING'}`);void reconcile();startWinRateMonitor();}", 1)
s = s.replace("async onPositionRemoved(instanceIndex,positionId){void reconcile();}", "async onPositionRemoved(instanceIndex,positionId){void reconcile();void refreshWinRate();}", 1)
s = s.replace("async onOrderCompleted(instanceIndex,order){if(order?.symbol===SYMBOL)void reconcile();}", "async onOrderCompleted(instanceIndex,order){if(order?.symbol===SYMBOL){void reconcile();void refreshWinRate();}}", 1)
s = s.replace("void reconcile();setStatus(`CONNECTED — ${SYMBOL} live tick/candle stream active — bias ${marketBias||'CALCULATING'}`);", "void reconcile();startWinRateMonitor();setStatus(`CONNECTED — ${SYMBOL} live tick/candle stream active — bias ${marketBias||'CALCULATING'}`);", 1)

# Add the win-rate metric to the dashboard.
old = '<div class="metric"><small>Balance</small><strong id="balance">—</strong></div><div class="metric"><small>Position</small>'
new = '<div class="metric"><small>Balance</small><strong id="balance">—</strong></div><div class="metric"><small>Win Rate</small><strong class="green" id="winRate">—</strong></div><div class="metric"><small>Position</small>'
if old not in html:
    raise SystemExit('Could not locate dashboard metric block')
html = html.replace(old, new, 1)

js.write_text(s, encoding='utf-8')
h.write_text(html, encoding='utf-8')
print('Applied Start Bot connection stability, MetaApi resynchronization stability, and dashboard win-rate fixes.')
