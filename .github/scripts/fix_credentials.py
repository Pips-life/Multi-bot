from pathlib import Path

# Repair the Android/WebView credential flow before every release build.
path = Path('web/main.js')
s = path.read_text(encoding='utf-8')
old_save = "localStorage.setItem('metaapi.token',token);localStorage.setItem('metaapi.accountId',accountId);ui.token.value='SAVED TOKEN';ui.token.disabled=true;addLog('Credentials saved locally');connectSdk();"
new_save = "localStorage.setItem('metaapi.token',token);localStorage.setItem('metaapi.accountId',accountId);addLog('Credentials saved locally');connectSdk().then(()=>{if(connection){ui.token.value='SAVED TOKEN';ui.token.disabled=true;}});"
if old_save not in s:
    raise SystemExit('Credential save flow not found')
s = s.replace(old_save, new_save, 1)
old_stop = "ui.save.onclick=saveCredentials;ui.change.onclick=changeCredentials;ui.start.onclick=startBot;ui.stopBot.onclick=stopBot;"
new_stop = "ui.save.onclick=saveCredentials;ui.change.onclick=changeCredentials;ui.start.onclick=startBot;ui.stopBot.onclick=stopAllTrading;"
if old_stop not in s:
    raise SystemExit('STOP BOT handler binding not found')
s = s.replace(old_stop, new_stop, 1)
path.write_text(s, encoding='utf-8')
print('Pips-life credential/startup fix applied.')
