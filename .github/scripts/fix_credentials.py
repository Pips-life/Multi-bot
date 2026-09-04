from pathlib import Path

# Release builds use the canonical credential flow in web/main.js.
# Validate it here without rewriting source during the build.
p = Path('web/main.js')
s = p.read_text(encoding='utf-8')
required = [
    "function saveCredentials()",
    "localStorage.setItem('metaapi.token'",
    "localStorage.setItem('metaapi.accountId'",
    "saveCredentials?.",
    "getSavedToken",
]
missing = [x for x in required if x not in s]
if missing:
    raise SystemExit('Credential source validation failed: ' + ', '.join(missing))
print('Pips-life credential flow validated; no build-time source rewrite required.')
