import MetaApi, { SynchronizationListener } from 'metaapi.cloud-sdk';

const SYMBOL = 'XAUUSD';
const MAGIC = 260903;
const TRAIL_PIPS = 100;
const RISK_FRACTION = 0.01;

const $ = id => document.getElementById(id);
const ui = {
  token: $('token'), account: $('account'), price: $('price'), balance: $('balance'),
  position: $('position'), stop: $('stop'), status: $('status'), save: $('save'),
  change: $('change'), start: $('start'), stopBot: $('stop')
};

let api = null, account = null, connection = null, listener = null;
let trading = false, connecting = false, synchronized = false;
let lastMid = NaN, currentPosition = null, currentStop = null;
let entryInFlight = false, stopActionInFlight = false, lastStatus = '';

function setStatus(text) { if (text !== lastStatus) { lastStatus = text; ui.status.textContent = text; } }
function fmt(n) { return Number.isFinite(n) ? Number(n).toFixed(2) : '—'; }
function sideOf(x) {
  const t = String(x?.type ?? '').toUpperCase();
  return t.includes('BUY') ? 'BUY' : t.includes('SELL') ? 'SELL' : '';
}
function isOurs(x) { return x && x.symbol === SYMBOL && Number(x.magic ?? MAGIC) === MAGIC; }
function idOf(x) { return String(x?.id ?? x?.positionId ?? x?.orderId ?? ''); }
function volumeOf(x) { return Number(x?.volume ?? 0); }
function pipValueFromSpec(s) {
  if (!s) return 0;
  if (Number(s.pipValue) > 0) return Number(s.pipValue);
  if (Number(s.tickValue) > 0 && Number(s.tickSize) > 0 && Number(s.pipSize) > 0)
    return Number(s.tickValue) * Number(s.pipSize) / Number(s.tickSize);
  if (Number(s.tradeTickValue) > 0 && Number(s.tradeTickSize) > 0 && Number(s.pipSize) > 0)
    return Number(s.tradeTickValue) * Number(s.pipSize) / Number(s.tradeTickSize);
  return 0;
}
function normalizeVolume(raw, spec) {
  const min = Number(spec?.minVolume ?? 0.01);
  const max = Number(spec?.maxVolume ?? 100);
  const step = Number(spec?.volumeStep ?? 0.01);
  let v = Math.max(min, Math.min(max, raw));
  if (step > 0) v = Math.floor(v / step + 1e-10) * step;
  v = Math.max(min, v);
  return Number(v.toFixed(6));
}
function currentVolume() {
  const spec = connection?.terminalState?.specification(SYMBOL);
  const info = connection?.terminalState?.accountInformation;
  const balance = Number(info?.balance ?? 0);
  const pv = pipValueFromSpec(spec);
  if (!spec || balance <= 0 || pv <= 0) return 0;
  return normalizeVolume((balance * RISK_FRACTION) / (TRAIL_PIPS * pv), spec);
}
function opposite(side) { return side === 'BUY' ? 'SELL' : 'BUY'; }
function stopCandidate(side, mid, pipSize) {
  return side === 'BUY' ? mid - TRAIL_PIPS * pipSize : mid + TRAIL_PIPS * pipSize;
}
function cleanToken(value) {
  return String(value ?? '').trim().replace(/^Bearer\s+/i, '');
}
function validAccountId(value) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}
function sdkConstructor() {
  const Ctor = MetaApi?.default ?? MetaApi;
  if (typeof Ctor !== 'function') throw new Error('MetaApi browser SDK constructor is unavailable');
  return Ctor;
}

class BotListener extends SynchronizationListener {
  onConnected() { setStatus('MetaApi connected — synchronizing…'); }
  onDisconnected() { synchronized = false; setStatus('MetaApi disconnected — waiting to reconnect…'); }
  onSynchronizationStarted() { synchronized = false; setStatus('Synchronizing MetaApi terminal…'); }
  onSynchronizationFinished() {
    synchronized = true;
    setStatus('CONNECTED — XAUUSD live stream active');
    reconcile();
  }
  onSymbolPricesUpdated(instanceIndex, prices) {
    const p = Array.isArray(prices) ? prices.find(x => x?.symbol === SYMBOL) : (prices?.symbol === SYMBOL ? prices : null);
    if (!p) return;
    const bid = Number(p.bid), ask = Number(p.ask);
    if (!Number.isFinite(bid) || !Number.isFinite(ask)) return;
    const mid = (bid + ask) / 2;
    const previous = lastMid;
    lastMid = mid;
    ui.price.textContent = fmt(mid);
    const info = connection?.terminalState?.accountInformation;
    if (info?.balance != null) ui.balance.textContent = fmt(Number(info.balance));
    if (!trading || !synchronized) return;
    void onTick(mid, bid, ask, previous);
  }
  onPositionUpdated(instanceIndex, position) { if (position?.symbol === SYMBOL) reconcile(); }
  onPositionRemoved() { reconcile(); }
  onOrderUpdated(instanceIndex, order) { if (order?.symbol === SYMBOL) reconcile(); }
  onOrderCompleted() { reconcile(); }
  onOrderFailed(instanceIndex, orderId, error) { setStatus(`Order failed: ${error?.message || error}`); reconcile(); }
}

async function connectSdk() {
  if (connecting || connection) return;
  const token = cleanToken(ui.token.value);
  const accountId = ui.account.value.trim();
  if (!token || token === 'SAVED TOKEN') { setStatus('MetaAPI token is missing'); return; }
  if (!accountId) { setStatus('MetaAPI account ID is missing'); return; }
  if (!validAccountId(accountId)) { setStatus('MetaAPI account ID format is invalid'); return; }
  connecting = true;
  setStatus('Connecting directly to MetaApi…');
  try {
    const MetaApiClass = sdkConstructor();
    api = new MetaApiClass(token);
    account = await api.metatraderAccountApi.getAccount(accountId);
    if (!account?.id) throw new Error('MetaApi account not found');
    setStatus('MetaApi account found — checking deployment…');
    if (typeof account.waitConnected === 'function') await account.waitConnected();
    connection = account.getStreamingConnection();
    listener = new BotListener();
    connection.addSynchronizationListener(listener);
    await connection.connect();
    await connection.waitSynchronized();
    synchronized = true;
    await connection.subscribeToMarketData(SYMBOL);
    reconcile();
    setStatus('CONNECTED — XAUUSD live stream active');
  } catch (e) {
    const msg = e?.message || String(e);
    try { if (connection) await connection.close(); } catch (_) {}
    try { if (api) await api.close(); } catch (_) {}
    connection = null; account = null; api = null; synchronized = false;
    setStatus(`MetaApi connection failed: ${msg}`);
  } finally { connecting = false; }
}

function reconcile() {
  if (!connection?.terminalState) return;
  const state = connection.terminalState;
  const positions = (state.positions || []).filter(isOurs);
  const orders = (state.orders || []).filter(isOurs);
  const next = positions[0] || null;
  const old = currentPosition;
  if (old && next && idOf(old) !== idOf(next) && sideOf(old) !== sideOf(next)) void handleReversal(old, next);
  currentPosition = next;
  const stops = orders.filter(o => String(o.type ?? '').toUpperCase().includes('STOP'));
  const expected = next ? opposite(sideOf(next)) : '';
  const matching = stops.find(o => sideOf(o) === expected);
  currentStop = matching || null;
  ui.position.textContent = next ? sideOf(next) : '—';
  const stopPrice = Number(currentStop?.openPrice ?? currentStop?.currentPrice ?? 0);
  ui.stop.textContent = stopPrice > 0 ? fmt(stopPrice) : '—';
  if (next && !currentStop && !stopActionInFlight) void placeOppositeStop(next);
  if (!next && stops.length) for (const o of stops) void cancelOrder(idOf(o));
}

async function handleReversal(oldPosition, newPosition) {
  if (idOf(oldPosition) === idOf(newPosition)) return;
  try {
    if (connection && connection.terminalState.positions.some(p => idOf(p) === idOf(oldPosition)))
      await connection.closePosition(idOf(oldPosition));
  } catch (e) {
    const msg = String(e?.message || e);
    if (!/not found|does not exist|position.*closed/i.test(msg)) setStatus(`Closing previous position failed: ${msg}`);
  }
  currentPosition = newPosition;
  currentStop = null;
  await placeOppositeStop(newPosition);
}

async function enter(side) {
  if (entryInFlight || currentPosition) return;
  const volume = currentVolume();
  if (volume <= 0) { setStatus('Cannot size trade: broker pip value/specification unavailable'); return; }
  entryInFlight = true;
  try {
    const options = { comment: 'Multi-bot Velocity Expansion', clientId: `MBENTRY-${Date.now()}` };
    if (side === 'BUY') await connection.createMarketBuyOrder(SYMBOL, volume, null, null, options);
    else await connection.createMarketSellOrder(SYMBOL, volume, null, null, options);
    setStatus(`OPEN ${side} ${volume} — installing opposite STOP…`);
    await waitForPosition(side, 5000);
    reconcile();
    if (currentPosition) await placeOppositeStop(currentPosition);
  } catch (e) { setStatus(`Entry failed: ${e?.message || e}`); }
  finally { entryInFlight = false; }
}

async function waitForPosition(side, timeoutMs) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    reconcile();
    if (currentPosition && sideOf(currentPosition) === side) return currentPosition;
    await new Promise(r => setTimeout(r, 100));
  }
  return currentPosition;
}

async function placeOppositeStop(position) {
  if (!position || stopActionInFlight) return;
  stopActionInFlight = true;
  try {
    const spec = connection.terminalState.specification(SYMBOL);
    const pipSize = Number(spec?.pipSize ?? spec?.point ?? 0.01);
    const price = stopCandidate(sideOf(position), Number(position.openPrice), pipSize);
    const volume = volumeOf(position) || currentVolume();
    if (!volume || !Number.isFinite(price)) return;
    const options = { comment: 'Multi-bot 100-pip opposite STOP', clientId: `MBSTOP-${Date.now()}` };
    if (sideOf(position) === 'BUY') await connection.createStopSellOrder(SYMBOL, volume, price, null, null, options);
    else await connection.createStopBuyOrder(SYMBOL, volume, price, null, null, options);
    reconcile();
  } catch (e) { setStatus(`STOP placement failed: ${e?.message || e}`); }
  finally { stopActionInFlight = false; }
}

async function trail(mid) {
  if (!currentPosition || !currentStop || stopActionInFlight) return;
  const spec = connection.terminalState.specification(SYMBOL);
  const pipSize = Number(spec?.pipSize ?? spec?.point ?? 0.01);
  const candidate = stopCandidate(sideOf(currentPosition), mid, pipSize);
  const existing = Number(currentStop.openPrice ?? currentStop.currentPrice ?? 0);
  const improve = sideOf(currentPosition) === 'BUY' ? candidate > existing : candidate < existing;
  if (!improve) return;
  stopActionInFlight = true;
  try {
    await connection.modifyOrder(idOf(currentStop), candidate, null, null);
    if (currentStop) currentStop.openPrice = candidate;
  } catch (e) { setStatus(`STOP trail failed: ${e?.message || e}`); }
  finally { stopActionInFlight = false; }
}

async function onTick(mid, bid, ask, previous) {
  reconcile();
  if (!currentPosition) {
    if (entryInFlight || Number.isNaN(previous)) {
      if (Number.isNaN(previous)) setStatus('Streaming XAUUSD — waiting for first movement');
      return;
    }
    if (previous < mid) await enter('BUY');
    else if (previous > mid) await enter('SELL');
    return;
  }
  await trail(mid);
  setStatus(`Running ${sideOf(currentPosition)} | STOP ${fmt(Number(currentStop?.openPrice ?? currentStop?.currentPrice ?? 0))}`);
}

async function cancelOrder(id) { if (id && connection) { try { await connection.cancelOrder(id); } catch (_) {} } }

function saveCredentials() {
  const token = cleanToken(ui.token.value);
  const accountId = ui.account.value.trim();
  if (!token || token === 'SAVED TOKEN') { setStatus('Enter a valid MetaAPI token'); return; }
  if (!validAccountId(accountId)) { setStatus('Enter a valid MetaAPI account ID'); return; }
  localStorage.setItem('metaapi.token', token);
  localStorage.setItem('metaapi.accountId', accountId);
  ui.token.value = 'SAVED TOKEN'; ui.token.disabled = true; ui.account.value = accountId;
  const original = token;
  ui.token.value = original;
  connectSdk().finally(() => { ui.token.value = 'SAVED TOKEN'; ui.token.disabled = true; });
}

function changeCredentials() {
  trading = false;
  localStorage.removeItem('metaapi.token'); localStorage.removeItem('metaapi.accountId');
  if (connection) connection.close().catch(() => {});
  if (api) api.close().catch(() => {});
  connection = null; account = null; api = null; synchronized = false; currentPosition = null; currentStop = null;
  ui.token.disabled = false; ui.token.value = ''; ui.account.value = '';
  setStatus('Enter new MetaAPI credentials');
}

function startBot() {
  if (!connection || !synchronized) { setStatus('Connect MetaApi first'); return; }
  trading = true; setStatus('BOT RUNNING — waiting for tick movement');
}
function stopBot() { trading = false; setStatus('BOT STOPPED'); }

ui.save.onclick = saveCredentials;
ui.change.onclick = changeCredentials;
ui.start.onclick = startBot;
ui.stopBot.onclick = stopBot;

const savedToken = cleanToken(localStorage.getItem('metaapi.token'));
const savedAccount = String(localStorage.getItem('metaapi.accountId') || '').trim();
if (savedToken && savedAccount) {
  ui.token.value = savedToken;
  ui.account.value = savedAccount;
  connectSdk().finally(() => { ui.token.value = 'SAVED TOKEN'; ui.token.disabled = true; });
}
