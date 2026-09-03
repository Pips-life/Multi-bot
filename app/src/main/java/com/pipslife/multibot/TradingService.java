package com.pipslife.multibot;

import android.app.*;
import android.content.*;
import android.os.Build;
import android.content.pm.ServiceInfo;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import cloud.metaapi.sdk.clients.meta_api.SynchronizationListener;
import cloud.metaapi.sdk.clients.meta_api.models.MarketDataSubscription;
import cloud.metaapi.sdk.clients.meta_api.models.MetatraderSymbolPrice;
import cloud.metaapi.sdk.meta_api.MetaApi;
import cloud.metaapi.sdk.meta_api.MetaApiConnection;
import cloud.metaapi.sdk.meta_api.MetatraderAccount;
import io.vertx.core.Future;
import io.vertx.core.Vertx;

/**
 * Multi-bot Android trading engine.
 *
 * The MetaApi Java SDK owns authentication, terminal synchronization and the
 * real-time websocket transport. The app does not implement a custom socket
 * protocol. XAUUSD quotes are subscribed as quotes + ticks and processed from
 * SynchronizationListener callbacks.
 */
public class TradingService extends Service {
    public static final String ACTION_START = "START";
    public static final String ACTION_STOP = "STOP";
    public static final String ACTION_STATUS = "STATUS";

    private static final String CHANNEL = "multibot";
    private static final String SYMBOL = "XAUUSD";
    private static final int MAGIC = 260903;
    private static final double TRAIL_PIPS = 100.0;
    private static final double RISK_FRACTION = 0.01;

    private MetaApi api;
    private MetaApiConnection connection;
    private MetatraderAccount account;
    private Vertx vertx;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    private volatile boolean running;
    private volatile boolean trading;
    private volatile boolean synchronizedState;

    private String accountId = "";
    private String token = "";
    private double lastMid = Double.NaN;
    private double balance;
    private double pipSize = 0.01;
    private double pipValue;
    private double volume;
    private double minVolume = 0.01;
    private double maxVolume = 100;
    private double volumeStep = 0.01;

    private String positionId = "";
    private String positionSide = "";
    private double positionPrice;
    private double positionVolume;

    private String stopId = "";
    private String stopSide = "";
    private double stopPrice;

    @Override public void onCreate() {
        super.onCreate();
        createChannel();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel c = new NotificationChannel(
                    CHANNEL, "Multi-bot", NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(c);
        }
    }

    private void notifyState(String text) {
        Intent i = new Intent(ACTION_STATUS);
        i.setPackage(getPackageName());
        i.putExtra("text", text);
        i.putExtra("bid", lastMid);
        i.putExtra("balance", balance);
        i.putExtra("side", positionSide);
        i.putExtra("stop", stopPrice);
        sendBroadcast(i);
    }

    private void foreground(String text) {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this);
        b.setContentTitle("Multi-bot")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_menu_compass)
                .setOngoing(true);
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(7, b.build(), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(7, b.build());
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopEngine();
            return START_NOT_STICKY;
        }
        if (intent != null && ACTION_START.equals(intent.getAction())) startEngine();
        return START_STICKY;
    }

    private void startEngine() {
        if (running) return;
        running = true;
        trading = getSharedPreferences("runtime", 0).getBoolean("trading", false);
        foreground(trading ? "Starting live bot…" : "Connecting to MetaApi…");
        try {
            SecureStore s = new SecureStore(this);
            accountId = s.accountId();
            token = s.token();
            if (accountId.isEmpty() || token.isEmpty()) {
                throw new Exception("MetaAPI credentials are not saved");
            }
            executor.submit(this::connectSdk);
        } catch (Exception e) {
            running = false;
            notifyState("Setup required: " + safe(e));
            stopForeground(STOP_FOREGROUND_REMOVE);
        }
    }

    private void connectSdk() {
        try {
            // Official SDK websocket implementation; Vertx is the SDK runtime.
            vertx = Vertx.vertx();
            api = new MetaApi(token, vertx);
            notifyState("MetaApi: loading account…");

            account = api.getMetatraderAccountApi().getAccount(accountId).join();
            if (account == null) throw new Exception("MetaApi account not found");

            notifyState("MetaApi: account found — connecting to broker…");
            connection = account.connect().join();

            connection.addSynchronizationListener(new SynchronizationListener() {
                @Override public Future<Void> onSymbolPriceUpdated(
                        String instanceIndex, MetatraderSymbolPrice price) {
                    if (price != null && SYMBOL.equals(price.symbol)) {
                        executor.submit(() -> handlePrice(price));
                    }
                    return Future.succeededFuture();
                }
            });

            notifyState("MetaApi: synchronizing terminal…");
            connection.waitSynchronized().join();
            synchronizedState = true;

            refreshTerminalState();
            subscribeToXauusd();
            notifyState("CONNECTED — XAUUSD live websocket stream active");
        } catch (Exception e) {
            synchronizedState = false;
            notifyState("MetaApi connection failed: " + safe(rootCause(e)));
        }
    }

    private void subscribeToXauusd() throws Exception {
        // Quotes interval 0 requests the lowest-latency quote stream supported
        // by the SDK/account; ticks are also subscribed for tick-level events.
        List<MarketDataSubscription> subscriptions = new ArrayList<>();
        subscriptions.add(new MarketDataSubscription() {{
            type = "quotes";
            intervalInMilliseconds = 0;
        }});
        subscriptions.add(new MarketDataSubscription() {{
            type = "ticks";
        }});
        connection.subscribeToMarketData(SYMBOL, subscriptions).join();
    }

    private void handlePrice(MetatraderSymbolPrice price) {
        try {
            double bid = number(price, "bid", Double.NaN);
            double ask = number(price, "ask", Double.NaN);
            if (!Double.isFinite(bid) || !Double.isFinite(ask)) return;

            double mid = (bid + ask) / 2.0;
            double previous = lastMid;
            lastMid = mid;

            refreshTerminalState();

            if (!trading) {
                notifyState("CONNECTED — XAUUSD " + fmt(mid));
                return;
            }
            if (!synchronizedState) {
                notifyState("Synchronizing MetaApi terminal…");
                return;
            }
            if (Double.isNaN(previous)) {
                notifyState("Streaming XAUUSD — waiting for first movement");
                return;
            }

            if (positionId.isEmpty()) {
                if (previous < mid) enter("BUY", ask);
                else if (previous > mid) enter("SELL", bid);
            } else {
                trail(mid);
            }

            notifyState(positionSide.isEmpty()
                    ? "Waiting for entry"
                    : "Running " + positionSide + " | STOP " + fmt(stopPrice));
        } catch (Exception e) {
            notifyState("MetaApi runtime error: " + safe(rootCause(e)));
        }
    }

    /** TerminalState is the SDK-maintained local copy of streamed terminal data. */
    private void refreshTerminalState() {
        if (connection == null) return;
        try {
            Object state = connection.getTerminalState();
            Object info = invoke(state, "getAccountInformation");
            if (info != null) balance = number(info, "balance", balance);

            Object spec = invoke(state, "getSpecification", SYMBOL);
            if (spec != null) {
                pipSize = number(spec, "pipSize",
                        number(spec, "point", number(spec, "tickSize", pipSize)));
                minVolume = number(spec, "minVolume", minVolume);
                maxVolume = number(spec, "maxVolume", maxVolume);
                volumeStep = number(spec, "volumeStep", volumeStep);
                pipValue = number(spec, "pipValue", pipValue);
                recalcVolume();
            }

            syncPositions(invokeList(state, "getPositions"));
            syncOrders(invokeList(state, "getOrders"));
        } catch (Exception ignored) {
            // During websocket reconnect, terminal state can briefly be incomplete.
        }
    }

    private List<?> invokeList(Object target, String method) {
        Object result = invoke(target, method);
        return result instanceof List ? (List<?>) result : Collections.emptyList();
    }

    private void syncPositions(List<?> positions) {
        String oldId = positionId;
        String foundId = "";
        String foundSide = "";
        double foundPrice = 0;
        double foundVolume = 0;

        for (Object p : positions) {
            if (!isOurs(p)) continue;
            String id = text(p, "id", text(p, "positionId", ""));
            if (id.isEmpty()) continue;
            foundId = id;
            foundSide = typeSide(text(p, "type", ""));
            foundPrice = number(p, "openPrice", 0);
            foundVolume = number(p, "volume", 0);
            break;
        }

        // If the opposite pending stop filled on a hedging account, the new
        // position can coexist briefly with the old one. Close the old position
        // before installing the next opposite stop.
        if (!oldId.isEmpty() && !foundId.isEmpty() && !oldId.equals(foundId)
                && !positionSide.isEmpty() && !positionSide.equals(foundSide)) {
            try {
                closePosition(oldId);
            } catch (Exception e) {
                notifyState("Closing previous position failed: " + safe(rootCause(e)));
            }
        }

        positionId = foundId;
        positionSide = foundSide;
        positionPrice = foundPrice;
        positionVolume = foundVolume;

        if (foundId.isEmpty()) {
            positionPrice = 0;
            positionVolume = 0;
        }
    }

    private void syncOrders(List<?> orders) {
        String foundId = "";
        String foundSide = "";
        double foundPrice = 0;

        for (Object o : orders) {
            if (!isOurs(o)) continue;
            String type = text(o, "type", "").toUpperCase(Locale.US);
            if (!type.contains("STOP")) continue;
            String id = text(o, "id", text(o, "orderId", ""));
            if (id.isEmpty()) continue;
            foundId = id;
            foundSide = type.contains("BUY") ? "BUY" : "SELL";
            foundPrice = number(o, "openPrice", number(o, "currentPrice", 0));
            break;
        }

        stopId = foundId;
        stopSide = foundSide;
        if (foundPrice > 0) stopPrice = foundPrice;
        if (foundId.isEmpty()) stopPrice = 0;
    }

    private boolean isOurs(Object x) {
        return SYMBOL.equals(text(x, "symbol", ""))
                && Math.abs(number(x, "magic", -1) - MAGIC) < 0.000001;
    }

    private void enter(String side, double price) throws Exception {
        recalcVolume();
        if (volume <= 0) {
            notifyState("Cannot size trade: broker pip value/specification unavailable");
            return;
        }

        String clientId = "MBENTRY-" + UUID.randomUUID();
        // 14.0.9 exposes MarketTradeOptions, but the no-SL/no-TP overload can
        // be selected by passing typed nulls and a null options object.
        if ("BUY".equals(side)) {
            connection.createMarketBuyOrder(SYMBOL, volume,
                    (Double) null, (Double) null, null).join();
        } else {
            connection.createMarketSellOrder(SYMBOL, volume,
                    (Double) null, (Double) null, null).join();
        }
        notifyState("OPEN " + side + " " + fmt(volume) + " — installing opposite STOP…");

        // clientId is not available on the legacy overload above; the order is
        // isolated by symbol + magic in the terminal state.
        executor.submit(() -> waitForPosition(side, clientId));
    }

    private void waitForPosition(String side, String ignoredClientId) {
        long end = System.currentTimeMillis() + 5000;
        while (System.currentTimeMillis() < end) {
            refreshTerminalState();
            if (!positionId.isEmpty() && side.equals(positionSide)) {
                try { placeStopForCurrent(); } catch (Exception e) {
                    notifyState("STOP placement failed: " + safe(rootCause(e)));
                }
                return;
            }
            try { Thread.sleep(100); } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    private void trail(double mid) throws Exception {
        if (positionId.isEmpty()) return;

        double candidate = "BUY".equals(positionSide)
                ? mid - TRAIL_PIPS * pipSize
                : mid + TRAIL_PIPS * pipSize;

        if (stopId.isEmpty()) {
            if (stopPrice == 0
                    || ("BUY".equals(positionSide) && candidate > stopPrice)
                    || ("SELL".equals(positionSide) && candidate < stopPrice)) {
                placeStop(candidate);
            }
            return;
        }

        boolean improve = "BUY".equals(positionSide)
                ? candidate > stopPrice
                : candidate < stopPrice;
        if (improve) {
            connection.modifyOrder(stopId, candidate, (Double) null, (Double) null).join();
            stopPrice = candidate;
        }
    }

    private void placeStopForCurrent() throws Exception {
        if (positionId.isEmpty() || positionVolume <= 0) return;
        double price = "BUY".equals(positionSide)
                ? positionPrice - TRAIL_PIPS * pipSize
                : positionPrice + TRAIL_PIPS * pipSize;
        placeStop(price);
    }

    private void placeStop(double price) throws Exception {
        if (positionVolume <= 0) return;
        String side = "BUY".equals(positionSide) ? "SELL" : "BUY";

        if ("BUY".equals(side)) {
            connection.createStopBuyOrder(SYMBOL, positionVolume, price,
                    (Double) null, (Double) null, null).join();
        } else {
            connection.createStopSellOrder(SYMBOL, positionVolume, price,
                    (Double) null, (Double) null, null).join();
        }
        stopSide = side;
        stopPrice = price;
    }

    private void closePosition(String id) throws Exception {
        connection.closePosition(id, null).join();
    }

    private void recalcVolume() {
        if (balance > 0 && pipValue > 0) {
            double raw = (balance * RISK_FRACTION) / (TRAIL_PIPS * pipValue);
            volume = normalize(raw);
        }
    }

    private double normalize(double v) {
        v = Math.max(minVolume, Math.min(maxVolume, v));
        if (volumeStep > 0) v = Math.floor(v / volumeStep) * volumeStep;
        return Math.max(minVolume, Math.round(v * 1000000.0) / 1000000.0);
    }

    public void setTrading(boolean on) {
        trading = on;
        getSharedPreferences("runtime", 0).edit().putBoolean("trading", on).apply();
        notifyState(on ? "BOT RUNNING — live trading" : "BOT STOPPED");
    }

    private void stopEngine() {
        running = false;
        trading = false;
        synchronizedState = false;
        getSharedPreferences("runtime", 0).edit().putBoolean("trading", false).apply();

        executor.submit(() -> {
            try { if (connection != null) connection.close(); } catch (Exception ignored) {}
            try { if (api != null) api.close(); } catch (Exception ignored) {}
            try { if (vertx != null) vertx.close(); } catch (Exception ignored) {}
        });

        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
        notifyState("Stopped");
    }

    private Object invoke(Object target, String method, Object... args) {
        if (target == null) return null;
        try {
            for (Method m : target.getClass().getMethods()) {
                if (!m.getName().equals(method) || m.getParameterTypes().length != args.length) continue;
                return m.invoke(target, args);
            }
        } catch (Exception ignored) {}
        return null;
    }

    private double number(Object target, String name, double fallback) {
        if (target == null) return fallback;
        try {
            Field f = target.getClass().getField(name);
            Object v = f.get(target);
            if (v instanceof Number) return ((Number) v).doubleValue();
        } catch (Exception ignored) {}
        try {
            Object v = invoke(target, "get" + Character.toUpperCase(name.charAt(0)) + name.substring(1));
            if (v instanceof Number) return ((Number) v).doubleValue();
        } catch (Exception ignored) {}
        return fallback;
    }

    private String text(Object target, String name, String fallback) {
        if (target == null) return fallback;
        try {
            Field f = target.getClass().getField(name);
            Object v = f.get(target);
            if (v != null) return String.valueOf(v);
        } catch (Exception ignored) {}
        Object v = invoke(target, "get" + Character.toUpperCase(name.charAt(0)) + name.substring(1));
        return v == null ? fallback : String.valueOf(v);
    }

    private String typeSide(String type) {
        return type.toUpperCase(Locale.US).contains("BUY") ? "BUY" : "SELL";
    }

    private Throwable rootCause(Throwable e) {
        Throwable t = e;
        while (t.getCause() != null && t.getCause() != t) t = t.getCause();
        return t;
    }

    private String fmt(double x) {
        return Double.isNaN(x) ? "—" : String.format(Locale.US, "%.2f", x);
    }

    private String safe(Object x) {
        String s = String.valueOf(x);
        return s.length() > 220 ? s.substring(0, 220) : s;
    }

    @Override public android.os.IBinder onBind(Intent intent) { return null; }

    @Override public void onDestroy() {
        try { executor.shutdownNow(); } catch (Exception ignored) {}
        super.onDestroy();
    }
}
