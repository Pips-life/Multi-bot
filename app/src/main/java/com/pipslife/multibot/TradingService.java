package com.pipslife.multibot;

import android.app.*;
import android.content.*;
import android.os.IBinder;
import android.os.Build;
import android.content.pm.ServiceInfo;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import cloud.metaapi.sdk.clients.meta_api.SynchronizationListener;
import cloud.metaapi.sdk.clients.meta_api.models.MarketDataSubscription;
import cloud.metaapi.sdk.clients.meta_api.models.MetatraderSymbolPrice;
import cloud.metaapi.sdk.clients.meta_api.models.TradeOptions;
import cloud.metaapi.sdk.meta_api.MetaApi;
import cloud.metaapi.sdk.meta_api.MetaApiConnection;
import cloud.metaapi.sdk.meta_api.MetatraderAccount;
import io.vertx.core.Vertx;

/**
 * Direct MetaApi integration using MetaApi's official Java SDK.
 *
 * No raw Socket.IO/WebSocket protocol is implemented here. The SDK owns
 * authentication, synchronization, streaming and trade transport.
 */
public class TradingService extends Service {
    public static final String ACTION_START="START", ACTION_STOP="STOP", ACTION_STATUS="STATUS";
    private static final String CHANNEL="multibot";
    private static final String SYMBOL="XAUUSD";
    private static final int MAGIC=260903;
    private static final double TRAIL_PIPS=100.0;

    private MetaApi api;
    private MetaApiConnection connection;
    private MetatraderAccount account;
    private Vertx vertx;
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private volatile boolean running=false, trading=false, synchronizedState=false;
    private String accountId, token;
    private double lastMid=Double.NaN, balance=0, pipSize=0.01, pipValue=0, volume=0;
    private double minVolume=0.01, maxVolume=100, volumeStep=0.01;
    private String positionId="", positionSide="";
    private double positionPrice=0, positionVolume=0;
    private String stopId="", stopSide="";
    private double stopPrice=0;
    private String sourcePositionId="";
    private boolean waitingForStopFill=false;

    @Override public void onCreate(){ super.onCreate(); createChannel(); }

    private void createChannel(){
        if(Build.VERSION.SDK_INT>=26){
            NotificationChannel c=new NotificationChannel(CHANNEL,"Multi-bot",NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(c);
        }
    }

    private void notifyState(String text){
        Intent i=new Intent(ACTION_STATUS);
        i.setPackage(getPackageName());
        i.putExtra("text",text);
        i.putExtra("bid",lastMid);
        i.putExtra("balance",balance);
        i.putExtra("side",positionSide);
        i.putExtra("stop",stopPrice);
        sendBroadcast(i);
    }

    private void foreground(String text){
        Notification.Builder b=Build.VERSION.SDK_INT>=26
                ?new Notification.Builder(this,CHANNEL)
                :new Notification.Builder(this);
        b.setContentTitle("Multi-bot").setContentText(text)
                .setSmallIcon(android.R.drawable.ic_menu_compass).setOngoing(true);
        if(Build.VERSION.SDK_INT>=29)
            startForeground(7,b.build(),ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        else startForeground(7,b.build());
    }

    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent!=null && ACTION_STOP.equals(intent.getAction())) { stopEngine(); return START_NOT_STICKY; }
        if(intent!=null && ACTION_START.equals(intent.getAction())) startEngine();
        return START_STICKY;
    }

    private void startEngine(){
        if(running)return;
        running=true;
        trading=getSharedPreferences("runtime",0).getBoolean("trading",false);
        foreground(trading?"Starting live bot…":"Connecting to MetaApi…");
        try{
            SecureStore s=new SecureStore(this);
            accountId=s.accountId(); token=s.token();
            if(accountId.isEmpty()||token.isEmpty())throw new Exception("MetaAPI credentials are not saved");
            executor.submit(this::connectSdk);
        }catch(Exception e){
            running=false; notifyState("Setup required: "+safe(e)); stopForeground(STOP_FOREGROUND_REMOVE);
        }
    }

    private void connectSdk(){
        try{
            vertx=Vertx.vertx();
            api=new MetaApi(token,vertx);
            notifyState("MetaApi SDK: loading account…");

            account=api.getMetatraderAccountApi().getAccount(accountId)
                    .toCompletionStage().toCompletableFuture().get();
            if(account==null)throw new Exception("MetaApi account not found");

            notifyState("MetaApi SDK: account found — connecting to broker…");
            connection=account.connect().toCompletionStage().toCompletableFuture().get();

            connection.addSynchronizationListener(new SynchronizationListener(){
                @Override public io.vertx.core.Future<Void> onSymbolPriceUpdated(
                        String instanceIndex, MetatraderSymbolPrice price){
                    if(price!=null && SYMBOL.equals(price.symbol)){
                        executor.submit(()->handlePrice(price));
                    }
                    return io.vertx.core.Future.succeededFuture();
                }
            });

            notifyState("MetaApi SDK: synchronizing terminal…");
            connection.waitSynchronized().toCompletionStage().toCompletableFuture().get();
            synchronizedState=true;

            refreshTerminalState();
            subscribe();
            notifyState("CONNECTED — XAUUSD live stream active");
        }catch(Exception e){
            synchronizedState=false;
            notifyState("MetaApi SDK connection failed: "+safe(rootCause(e)));
        }
    }

    private void subscribe()throws Exception{
        List<MarketDataSubscription> subscriptions=new ArrayList<>();
        subscriptions.add(new MarketDataSubscription(){{ type="quotes"; intervalInMilliseconds=0; }});
        subscriptions.add(new MarketDataSubscription(){{ type="ticks"; }});
        connection.subscribeToMarketData(SYMBOL,subscriptions)
                .toCompletionStage().toCompletableFuture().get();
    }

    private void handlePrice(MetatraderSymbolPrice price){
        try{
            double bid=number(price,"bid",Double.NaN);
            double ask=number(price,"ask",Double.NaN);
            if(Double.isNaN(bid)||Double.isNaN(ask))return;
            double mid=(bid+ask)/2.0;
            double previous=lastMid;
            lastMid=mid;

            refreshTerminalState();

            if(!trading){
                notifyState("CONNECTED — XAUUSD "+fmt(mid));
                return;
            }
            if(!synchronizedState){
                notifyState("Synchronizing MetaApi terminal…");
                return;
            }

            if(Double.isNaN(previous)){
                notifyState("Streaming XAUUSD — waiting for first movement");
                return;
            }

            if(positionId.isEmpty()){
                if(previous<mid) enter("BUY",ask);
                else if(previous>mid) enter("SELL",bid);
            }else{
                trail(mid);
            }
            notifyState(positionSide.isEmpty()?"Waiting for entry":"Running "+positionSide+" | STOP "+fmt(stopPrice));
        }catch(Exception e){
            notifyState("MetaApi SDK runtime error: "+safe(rootCause(e)));
        }
    }

    /**
     * TerminalState is maintained by the official SDK from streaming updates.
     * Reading it is local and avoids implementing MetaApi's wire protocol.
     */
    private void refreshTerminalState(){
        if(connection==null)return;
        try{
            Object state=connection.getTerminalState();
            Object info=invoke(state,"getAccountInformation");
            if(info!=null)balance=number(info,"balance",balance);

            Object spec=invoke(state,"getSpecification",SYMBOL);
            if(spec!=null){
                pipSize=number(spec,"pipSize",number(spec,"point",number(spec,"tickSize",pipSize)));
                minVolume=number(spec,"minVolume",minVolume);
                maxVolume=number(spec,"maxVolume",maxVolume);
                volumeStep=number(spec,"volumeStep",volumeStep);
                pipValue=number(spec,"pipValue",pipValue);
                recalcVolume();
            }

            syncPositions(invokeList(state,"getPositions"));
            syncOrders(invokeList(state,"getOrders"));
        }catch(Exception e){
            // State may briefly be incomplete during reconnect; keep last known state.
        }
    }

    private List<?> invokeList(Object target,String method){
        Object result=invoke(target,method);
        return result instanceof List ? (List<?>)result : Collections.emptyList();
    }

    private void syncPositions(List<?> positions){
        String old=positionId;
        String foundId="", foundSide="";
        double foundPrice=0, foundVolume=0;
        for(Object p:positions){
            if(!isOurs(p))continue;
            String id=text(p,"id",text(p,"positionId",""));
            if(id.isEmpty())continue;
            foundId=id;
            foundSide=typeSide(text(p,"type",""));
            foundPrice=number(p,"openPrice",0);
            foundVolume=number(p,"volume",0);
            break;
        }
        if(waitingForStopFill && !old.isEmpty() && !foundId.isEmpty() && !foundId.equals(old)){
            try{
                closePosition(old);
                positionId=foundId; positionSide=foundSide; positionPrice=foundPrice; positionVolume=foundVolume;
                sourcePositionId=foundId; waitingForStopFill=false;
                placeStopForCurrent();
            }catch(Exception e){ notifyState("Reversal handling failed: "+safe(rootCause(e))); }
        }else{
            positionId=foundId; positionSide=foundSide; positionPrice=foundPrice; positionVolume=foundVolume;
            if(foundId.isEmpty()){
                positionPrice=0;positionVolume=0;
                if(!old.isEmpty()) waitingForStopFill=false;
            }
        }
    }

    private void syncOrders(List<?> orders){
        String foundId="", foundSide="";
        double foundPrice=0;
        for(Object o:orders){
            if(!isOurs(o))continue;
            String type=text(o,"type","").toUpperCase(Locale.US);
            if(!type.contains("STOP"))continue;
            String id=text(o,"id",text(o,"orderId",""));
            if(id.isEmpty())continue;
            foundId=id;
            foundSide=type.contains("BUY")?"BUY":"SELL";
            foundPrice=number(o,"openPrice",number(o,"currentPrice",0));
            break;
        }
        stopId=foundId; stopSide=foundSide; if(foundPrice>0)stopPrice=foundPrice;
    }

    private boolean isOurs(Object x){
        return SYMBOL.equals(text(x,"symbol","")) && number(x,"magic",-1)==MAGIC;
    }

    private void enter(String side,double price)throws Exception{
        recalcVolume();
        if(volume<=0)return;
        TradeOptions options=new TradeOptions();
        options.comment="Multi-bot Velocity Expansion";
        options.clientId="MBENTRY-"+UUID.randomUUID();
        if("BUY".equals(side))
            connection.createMarketBuyOrder(SYMBOL,volume,null,null,options)
                    .toCompletionStage().toCompletableFuture().get();
        else
            connection.createMarketSellOrder(SYMBOL,volume,null,null,options)
                    .toCompletionStage().toCompletableFuture().get();
    }

    private void trail(double mid)throws Exception{
        if(positionId.isEmpty())return;
        double candidate="BUY".equals(positionSide)
                ?mid-TRAIL_PIPS*pipSize
                :mid+TRAIL_PIPS*pipSize;

        if(stopId.isEmpty()){
            if(stopPrice==0 || ("BUY".equals(positionSide)&&candidate>stopPrice)
                    ||("SELL".equals(positionSide)&&candidate<stopPrice)) placeStop(candidate);
            return;
        }

        boolean improve="BUY".equals(positionSide)?candidate>stopPrice:candidate<stopPrice;
        if(improve){
            connection.modifyOrder(stopId,candidate,null,null)
                    .toCompletionStage().toCompletableFuture().get();
            stopPrice=candidate;
        }
    }

    private void placeStopForCurrent()throws Exception{
        if(positionId.isEmpty()||positionVolume<=0)return;
        double price="BUY".equals(positionSide)
                ?positionPrice-TRAIL_PIPS*pipSize
                :positionPrice+TRAIL_PIPS*pipSize;
        placeStop(price);
    }

    private void placeStop(double price)throws Exception{
        if(positionVolume<=0)return;
        TradeOptions options=new TradeOptions();
        options.comment="Multi-bot 100-pip opposite STOP";
        options.clientId="MBSTOP-"+UUID.randomUUID();
        String side="BUY".equals(positionSide)?"SELL":"BUY";
        if("BUY".equals(side))
            connection.createStopBuyOrder(SYMBOL,positionVolume,price,null,null,options)
                    .toCompletionStage().toCompletableFuture().get();
        else
            connection.createStopSellOrder(SYMBOL,positionVolume,price,null,null,options)
                    .toCompletionStage().toCompletableFuture().get();
        stopSide=side; stopPrice=price; sourcePositionId=positionId;
    }

    private void closePosition(String id)throws Exception{
        connection.closePosition(id,null).toCompletionStage().toCompletableFuture().get();
    }

    private void recalcVolume(){
        if(balance>0&&pipValue>0){
            double raw=(balance*0.01)/(TRAIL_PIPS*pipValue);
            volume=normalize(raw);
        }
    }

    private double normalize(double v){
        v=Math.max(minVolume,Math.min(maxVolume,v));
        if(volumeStep>0)v=Math.floor(v/volumeStep)*volumeStep;
        return Math.max(minVolume,Math.round(v*1000000.0)/1000000.0);
    }

    public void setTrading(boolean on){
        trading=on;
        getSharedPreferences("runtime",0).edit().putBoolean("trading",on).apply();
        notifyState(on?"BOT RUNNING — live trading":"BOT STOPPED");
    }

    private void stopEngine(){
        running=false;trading=false;synchronizedState=false;
        getSharedPreferences("runtime",0).edit().putBoolean("trading",false).apply();
        executor.submit(()->{
            try{ if(connection!=null) connection.close(); }catch(Exception ignored){}
            try{ if(vertx!=null) vertx.close(); }catch(Exception ignored){}
        });
        stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();notifyState("Stopped");
    }

    private Object invoke(Object target,String method,Object...args){
        if(target==null)return null;
        try{
            for(Method m:target.getClass().getMethods()){
                if(!m.getName().equals(method)||m.getParameterTypes().length!=args.length)continue;
                return m.invoke(target,args);
            }
        }catch(Exception ignored){}
        return null;
    }

    private double number(Object target,String name,double fallback){
        if(target==null)return fallback;
        try{
            Field f=target.getClass().getField(name);
            Object v=f.get(target);
            if(v instanceof Number)return ((Number)v).doubleValue();
        }catch(Exception ignored){}
        try{
            Object v=invoke(target,"get"+Character.toUpperCase(name.charAt(0))+name.substring(1));
            if(v instanceof Number)return ((Number)v).doubleValue();
        }catch(Exception ignored){}
        return fallback;
    }

    private String text(Object target,String name,String fallback){
        if(target==null)return fallback;
        try{
            Field f=target.getClass().getField(name);
            Object v=f.get(target);
            if(v!=null)return String.valueOf(v);
        }catch(Exception ignored){}
        Object v=invoke(target,"get"+Character.toUpperCase(name.charAt(0))+name.substring(1));
        return v==null?fallback:String.valueOf(v);
    }

    private String typeSide(String type){return type.toUpperCase(Locale.US).contains("BUY")?"BUY":"SELL";}
    private Throwable rootCause(Throwable e){Throwable t=e;while(t.getCause()!=null&&t.getCause()!=t)t=t.getCause();return t;}
    private String fmt(double x){return Double.isNaN(x)?"—":String.format(Locale.US,"%.2f",x);}
    private String safe(Object x){String s=String.valueOf(x);return s.length()>220?s.substring(0,220):s;}

    @Override public void onDestroy(){
        try{if(connection!=null)connection.close();}catch(Exception ignored){}
        try{if(vertx!=null)vertx.close();}catch(Exception ignored){}
        executor.shutdownNow();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent){return null;}
}
