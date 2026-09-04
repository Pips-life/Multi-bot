from pathlib import Path

# Repair the Android/WebView credential flow before every release build.
path = Path('web/main.js')
s = path.read_text(encoding='utf-8')

old_save = "localStorage.setItem('metaapi.token',token);localStorage.setItem('metaapi.accountId',accountId);ui.token.value='SAVED TOKEN';ui.token.disabled=true;addLog('Credentials saved locally');connectSdk();"
new_save = "localStorage.setItem('metaapi.token',token);localStorage.setItem('metaapi.accountId',accountId);addLog('Credentials saved locally');connectSdk().then(()=>{if(connection){ui.token.value='SAVED TOKEN';ui.token.disabled=true;}});"
if old_save in s:
    s = s.replace(old_save, new_save, 1)
elif new_save not in s:
    raise SystemExit('Credential save flow not found')

# STOP BOT is owned by the app's current main.js implementation. Do not require
# one exact minified binding string here: the build must remain idempotent when
# that handler has already been updated in the source.
path.write_text(s, encoding='utf-8')
print('Pips-life credential/startup fix applied (idempotent).')
