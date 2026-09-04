from pathlib import Path

p = Path('web/main.js')
s = p.read_text(encoding='utf-8')

# Starting the bot must never tear down a connection that is already
# synchronized. The previous force-reconnect path caused the UI to fall back
# to "Synchronizing MetaApi terminal" immediately after a successful connect.
old = "  if(connection&&!force)return;\n"
new = "  if(connection&&synchronized)return;\n  if(connection&&!force)return;\n"
if old not in s:
    raise SystemExit('Could not locate connectSdk connection guard')
s = s.replace(old, new, 1)

# If startBot is called after a successful connection, preserve the live
# synchronized stream and simply enable trading.
check = "  if(connection&&synchronized)return;\n"
if check not in s:
    raise SystemExit('Start connection guard validation failed')

p.write_text(s, encoding='utf-8')
print('Fixed Start Bot connection guard: synchronized MetaApi connections are preserved.')
