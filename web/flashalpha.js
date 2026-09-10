/* FlashAlpha options-data connector.
 * Keeps the API key on-device and never sends it to our server.
 * Free tier can validate the account; CME/GC=F options analytics are plan-gated by FlashAlpha.
 */
(() => {
  const BASE = 'https://lab.flashalpha.com';
  const KEY_STORAGE = 'flashalphaApiKey';
  const $ = id => document.getElementById(id);

  function setText(id, text) { const el = $(id); if (el) el.textContent = text; }
  function esc(v) { return String(v ?? '').replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c])); }

  async function request(path, key) {
    const r = await fetch(BASE + path, { headers: { 'X-Api-Key': key, 'Accept': 'application/json' } });
    let body = null; try { body = await r.json(); } catch (_) {}
    if (!r.ok) {
      const msg = body?.detail || body?.message || body?.error || `HTTP ${r.status}`;
      const e = new Error(String(msg)); e.status = r.status; e.body = body; throw e;
    }
    return body;
  }

  function ensureCard() {
    if ($('flashalphaCard')) return;
    const account = $('accountSection');
    if (!account) return;
    const card = document.createElement('section');
    card.className = 'card account'; card.id = 'flashalphaCard';
    card.innerHTML = `
      <div class="pad">
        <div class="title">FlashAlpha Connection <small>Options Intelligence</small></div>
        <div class="accountGrid">
          <label><span class="label">FlashAlpha API key</span><input class="input" id="flashalphaKey" type="password" autocomplete="off" placeholder="Paste FlashAlpha API key"></label>
          <div><span class="label">Connection</span><div class="input" id="flashalphaStatus" style="min-height:43px">Not connected</div></div>
        </div>
        <div class="accountActions">
          <button class="btn save" id="flashalphaConnect">CONNECT FLASHALPHA</button>
          <button class="btn change" id="flashalphaClear">CLEAR KEY</button>
        </div>
        <div class="notice" id="flashalphaQuota">Your key is stored locally on this Android device. It is sent directly to FlashAlpha as the <b>X-Api-Key</b> header.</div>
        <div class="notice" id="flashalphaData">GC=F options data: not tested yet.</div>
      </div>`;
    account.insertAdjacentElement('afterend', card);

    const key = localStorage.getItem(KEY_STORAGE) || '';
    $('flashalphaKey').value = key;
    $('flashalphaConnect').onclick = connect;
    $('flashalphaClear').onclick = () => {
      localStorage.removeItem(KEY_STORAGE);
      $('flashalphaKey').value = '';
      setText('flashalphaStatus', 'Not connected');
      setText('flashalphaQuota', 'API key cleared from this device.');
      setText('flashalphaData', 'GC=F options data: not tested yet.');
    };
  }

  async function connect() {
    const key = String($('flashalphaKey')?.value || '').trim().replace(/^Bearer\s+/i, '');
    if (!key) { setText('flashalphaStatus', 'API key required'); return; }
    localStorage.setItem(KEY_STORAGE, key);
    setText('flashalphaStatus', 'Connecting…');
    setText('flashalphaQuota', 'Checking FlashAlpha account and quota…');
    setText('flashalphaData', 'Checking GC=F options access…');
    try {
      const acct = await request('/v1/account', key);
      const plan = acct?.plan || 'unknown';
      const remaining = acct?.remaining ?? '—';
      setText('flashalphaStatus', `Connected • ${plan}`);
      setText('flashalphaQuota', `Plan: ${plan} • ${remaining} requests remaining today`);

      // This is deliberately one GC=F test call. It tells us whether the current
      // plan can access CME gold options before the app starts using analytics.
      try {
        const data = await request('/v1/exposure/gex/GC%3DF', key);
        const strikes = Array.isArray(data?.strikes) ? data.strikes.length : 0;
        setText('flashalphaData', `GC=F options: LIVE • GEX ${data?.net_gex_label || 'available'} • ${strikes} strikes`);
        window.dispatchEvent(new CustomEvent('flashalpha:ready', { detail: data }));
      } catch (e) {
        if (e.status === 403) {
          setText('flashalphaData', 'GC=F options: connected, but this plan does not include CME futures options analytics. Growth is required.');
        } else {
          setText('flashalphaData', `GC=F options test failed: ${e.message}`);
        }
        window.dispatchEvent(new CustomEvent('flashalpha:error', { detail: e }));
      }
    } catch (e) {
      setText('flashalphaStatus', e.status === 401 ? 'Invalid API key' : `Connection failed (${e.status || 'network'})`);
      setText('flashalphaQuota', e.status === 401 ? 'FlashAlpha rejected this key. Check the Profile page and paste the active key.' : `FlashAlpha error: ${e.message}`);
      setText('flashalphaData', 'GC=F options: not available until the API connection succeeds.');
    }
  }

  window.FlashAlphaConnector = {
    getApiKey: () => localStorage.getItem(KEY_STORAGE) || '',
    connect,
    request
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensureCard); else ensureCard();
})();
