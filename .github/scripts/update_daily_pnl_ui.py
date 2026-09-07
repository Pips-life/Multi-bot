from pathlib import Path
import re

main = Path('web/main.js')
s = main.read_text()
old = re.search(r"function updateProfitLossUI\(\)\{.*?\}\n\nclass BotListener", s, re.S)
if not old:
    raise SystemExit('updateProfitLossUI block not found')
new = r'''function localDayKey(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
function dayStartBalance(rawBal){if(!Number.isFinite(rawBal))return NaN;const key=`pipslife.dayStartBalance.${localDayKey()}`;try{const saved=Number(localStorage.getItem(key));if(Number.isFinite(saved)&&saved>0)return saved;localStorage.setItem(key,String(rawBal));return rawBal;}catch(_){return rawBal;}}
function updateProfitLossUI(){const info=connection?.terminalState?.accountInformation;const positions=ownedPositions();const rawBal=Number(info?.balance),rawEq=Number(info?.equity),rawMargin=Number(info?.margin);const floating=positions.reduce((s,x)=>s+(Number(x.profit)||0),0);const startBal=dayStartBalance(rawBal);const dailyGain=Number.isFinite(rawEq)&&Number.isFinite(startBal)?rawEq-startBal:(Number.isFinite(rawBal)&&Number.isFinite(startBal)?rawBal-startBal:floating);const dailyPct=Number.isFinite(startBal)&&startBal!==0?(dailyGain/startBal)*100:0;const realizedToday=Number.isFinite(rawBal)&&Number.isFinite(startBal)?rawBal-startBal:0;if(Number.isFinite(rawBal)){ui.balance.textContent=moneyKsh(rawBal);$('pnlBalance').textContent=moneyKsh(startBal);$('livePnl').textContent=moneyKsh(dailyGain);$('floatingPnl').textContent=moneyKsh(floating);$('pnlPercent').textContent=`${dailyGain>=0?'+':''}${dailyPct.toFixed(2)}%`;$('dailyRealized').textContent=moneyKsh(realizedToday);}else{ui.balance.textContent='KSh —';$('pnlBalance').textContent='KSh —';$('livePnl').textContent='KSh 0.00';$('floatingPnl').textContent='KSh 0.00';$('pnlPercent').textContent='+0.00%';$('dailyRealized').textContent='KSh 0.00';}if(Number.isFinite(rawEq)){$('equity').textContent=moneyKsh(rawEq);$('pnlEquity').textContent=moneyKsh(rawEq);}else{$('equity').textContent='KSh —';$('pnlEquity').textContent='KSh —';}if(Number.isFinite(rawMargin))$('margin').textContent=moneyKsh(rawMargin);else $('margin').textContent='KSh —';}

class BotListener'''
s = s[:old.start()] + new + s[old.end():]
main.write_text(s)

html = Path('web/index.html')
h = html.read_text()
old_box = re.search(r'<div class="pnlbox">.*?</div></div></section>', h, re.S)
if not old_box:
    raise SystemExit('pnlbox markup not found')
new_box = '''<div class="pnlbox"><div class="pnlhead"><div><div class="section-title" style="margin:0 0 5px">Today's Gain</div><div class="pnlvalue" id="livePnl">KSh 0.00</div><div class="subline">ACCOUNT EQUITY CHANGE SINCE DAY START</div></div><div style="text-align:right"><div class="pnlpct" id="pnlPercent">+0.00%</div><div class="subline">% OF DAY-START BALANCE</div></div></div><div class="pnlmeta"><div><small>Floating P/L</small><strong id="floatingPnl">KSh 0.00</strong></div><div><small>Day-start Balance</small><strong id="pnlBalance">KSh —</strong></div><div><small>Realized Today</small><strong id="dailyRealized">KSh 0.00</strong></div><div><small>Equity</small><strong id="pnlEquity">KSh —</strong></div><div><small>Margin</small><strong id="margin">KSh —</strong></div></div></div></section>'''
h = h[:old_box.start()] + new_box + h[old_box.end():]
h = h.replace('200-pip protective SL • momentum exits','200-pip protective SL • +100-pip momentum exits')
html.write_text(h)
