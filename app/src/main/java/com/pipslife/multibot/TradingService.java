package com.pipslife.multibot;

import android.app.*;
import android.content.*;
import android.os.IBinder;
import android.os.Build;
import androidx.annotation.Nullable;

import org.json.*;
import java.util.*;
import io.socket.client.IO;
import io.socket.client.Socket;

public class TradingService extends Service {
    public static final String ACTION_START="START", ACTION_STOP="STOP", ACTION_STATUS="STATUS";
    private static final String URL="https://mt-client-api-v1.agiliumtrade.agiliumtrade.ai";
    private static final String CHANNEL="multibot";
    private static final int MAGIC=260903;
    private Socket socket; private String accountId; private String token;
    private volatile boolean running=false, authenticated=false, trading=false;
    private double lastMid=Double.NaN, balance=0, pipSize=0.01, pipValue=0, volume=0;
    private double minVolume=0.01, maxVolume=100, volumeStep=0.01;
    private String positionId="", positionSide=""; private double positionPrice=0, positionVolume=0;
    private String stopId="", stopSide=""; private double stopPrice=0;
    private boolean waitingForStopFill=false;

    @Override public void onCreate(){ super.onCreate(); createChannel(); }
    private void createChannel(){ if(Build.VERSION.SDK_INT>=26){ NotificationChannel c=new NotificationChannel(CHANNEL,"Multi-bot",NotificationManager.IMPORTANCE_LOW); getSystemService(NotificationManager.class).createNotificationChannel(c); } }
    private void notifyState(String text){ Intent i=new Intent(ACTION_STATUS); i.setPackage(getPackageName()); i.putExtra("text",text); i.putExtra("bid",lastMid); i.putExtra("balance",balance); i.putExtra("side",positionSide); i.putExtra("stop",stopPrice); sendBroadcast(i); }
    private void foreground(String text){ Notification.Builder b=Build.VERSION.SDK_INT>=26?new Notification.Builder(this,CHANNEL):new Notification.Builder(this); b.setContentTitle("Multi-bot").setContentText(text).setSmallIcon(android.R.drawable.ic_menu_compass).setOngoing(true); startForeground(7,b.build()); }

    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent!=null && ACTION_STOP.equals(intent.getAction())) { stopEngine(); return START_NOT_STICKY; }
        if(intent!=null && ACTION_START.equals(intent.getAction())) { startEngine(); }
        return START_STICKY;
    }
    private void startEngine(){
        if(running) return; running=true; foreground("Connecting to MetaApi…");
        try { SecureStore s=new SecureStore(this); accountId=s.accountId(); token=s.token(); if(accountId.isEmpty()||token.isEmpty()) throw new Exception("MetaAPI credentials are not saved"); connect(); }
        catch(Exception e){ running=false; notifyState("Setup required: "+e.getMessage()); stopForeground(STOP_FOREGROUND_REMOVE); }
    }
    private void connect() throws Exception {
        IO.Options o=IO.Options.builder().setPath("/ws").setQuery(Collections.singletonMap("auth-token",token)).setReconnection(true).build();
        socket=IO.socket(URL,o);
        socket.on(Socket.EVENT_CONNECT,args->{ authenticated=false; emit("subscribe", base("subscribe")); notifyState("MetaApi connected; waiting for terminal…"); });
        socket.on("synchronization",args->{ if(args.length==0)return; try{handleSync((JSONObject)args[0]);}catch(Exception e){notifyState("Sync error: "+e.getMessage());} });
        socket.on("processingError",args->{notifyState("MetaApi error: "+(args.length>0?String.valueOf(args[0]):"unknown"));});
        socket.on(Socket.EVENT_DISCONNECT,args->{authenticated=false; notifyState("MetaApi disconnected; reconnecting…");});
        socket.connect();
    }
    private JSONObject base(String type){ JSONObject j=new JSONObject(); try{j.put("accountId",accountId).put("type",type).put("requestId",UUID.randomUUID().toString());}catch(Exception ignored){} return j; }
    private void emit(String event,JSONObject payload){ if(socket!=null && socket.connected()) socket.emit("request",payload); }
    private void handleSync(JSONObject d)throws Exception{
        String type=d.optString("type");
        if("authenticated".equals(type)){ authenticated=true; emit("synchronize",base("synchronize")); JSONObject sub=base("subscribeToMarketData"); sub.put("symbol","XAUUSD"); sub.put("subscriptions",new JSONArray().put(new JSONObject().put("type","ticks").put("intervalInMilliseconds",0)).put(new JSONObject().put("type","quotes").put("intervalInMilliseconds",0))); emit("market",sub); notifyState("Terminal authenticated; streaming XAUUSD ticks…"); }
        else if("accountInformation".equals(type)){ JSONObject a=d.optJSONObject("accountInformation"); if(a!=null)balance=a.optDouble("balance",balance); recalcVolume(); }
        else if("specifications".equals(type)){ JSONArray a=d.optJSONArray("specifications"); if(a!=null)for(int i=0;i<a.length();i++){JSONObject x=a.getJSONObject(i);if("XAUUSD".equals(x.optString("symbol"))){double ts=x.optDouble("tickSize",0.01);int digits=x.optInt("digits",2);pipSize=(digits>=3?ts*10:ts);minVolume=x.optDouble("minVolume",minVolume);maxVolume=x.optDouble("maxVolume",maxVolume);volumeStep=x.optDouble("volumeStep",volumeStep);}} recalcVolume(); }
        else if("positions".equals(type)){ JSONArray a=d.optJSONArray("positions"); if(a!=null)syncPositions(a); }
        else if("orders".equals(type)){ JSONArray a=d.optJSONArray("orders"); if(a!=null)syncOrders(a); }
        else if("prices".equals(type)){ JSONArray a=d.optJSONArray("prices"); if(a!=null)for(int i=0;i<a.length();i++){JSONObject p=a.getJSONObject(i);if("XAUUSD".equals(p.optString("symbol"))){onPrice(p);}} }
        else if("status".equals(type)){ JSONArray up=d.optJSONArray("updatedPositions"); if(up!=null)for(int i=0;i<up.length();i++) upsertPosition(up.getJSONObject(i)); JSONArray rem=d.optJSONArray("removedPositionIds"); if(rem!=null)for(int i=0;i<rem.length();i++) if(positionId.equals(rem.optString(i))) positionId=""; JSONArray ord=d.optJSONArray("updatedOrders"); if(ord!=null)for(int i=0;i<ord.length();i++) upsertOrder(ord.getJSONObject(i)); JSONArray done=d.optJSONArray("completedOrderIds"); if(done!=null)for(int i=0;i<done.length();i++)if(stopId.equals(done.optString(i)))waitingForStopFill=true; reconcile(); }
    }
    private void syncPositions(JSONArray a){ positionId=""; for(int i=0;i<a.length();i++)try{upsertPosition(a.getJSONObject(i));}catch(Exception ignored){} }
    private void syncOrders(JSONArray a){ stopId=""; for(int i=0;i<a.length();i++)try{upsertOrder(a.getJSONObject(i));}catch(Exception ignored){} }
    private void upsertPosition(JSONObject p){ if(!"XAUUSD".equals(p.optString("symbol"))||p.optInt("magic",-1)!=MAGIC)return; positionId=p.optString("id"); positionSide=p.optString("type").contains("BUY")?"BUY":"SELL"; positionPrice=p.optDouble("openPrice",positionPrice); positionVolume=p.optDouble("volume",positionVolume); }
    private void upsertOrder(JSONObject o){ if(!"XAUUSD".equals(o.optString("symbol"))||o.optInt("magic",-1)!=MAGIC)return; String t=o.optString("type"); if(!t.contains("STOP"))return; stopId=o.optString("id"); stopSide=t.contains("BUY")?"BUY":"SELL"; stopPrice=o.optDouble("openPrice",stopPrice); }
    private void onPrice(JSONObject p)throws Exception{
        double bid=p.optDouble("bid",Double.NaN), ask=p.optDouble("ask",Double.NaN); if(Double.isNaN(bid)||Double.isNaN(ask))return; double mid=(bid+ask)/2; lastMid=mid;
        if(p.has("profitTickValue")){double tv=p.optDouble("profitTickValue",0);double ts=pipSize>0?pipSize:0.01;double tickSizeGuess=(pipSize>=0.1?pipSize/10:pipSize); if(tv>0&&tickSizeGuess>0)pipValue=tv*(pipSize/tickSizeGuess); recalcVolume();}
        if(!trading){notifyState("Live XAUUSD: "+fmt(mid));return;}
        if(Double.isNaN(lastMid)) { lastMid=mid; return; }
        double prev=lastMid; lastMid=mid;
        if(positionId.isEmpty()) { if(prev<mid) enter("BUY",ask); else if(prev>mid) enter("SELL",bid); }
        else if(!stopId.isEmpty()) trail(mid);
        notifyState(positionSide.isEmpty()?"Waiting for first movement":"Running "+positionSide+" | stop "+fmt(stopPrice));
    }
    private void recalcVolume(){ if(balance>0&&pipValue>0){double raw=(balance*0.01)/(100.0*pipValue);volume=normalize(raw);} }
    private double normalize(double v){v=Math.max(minVolume,Math.min(maxVolume,v)); if(volumeStep>0)v=Math.floor(v/volumeStep)*volumeStep; return Math.max(minVolume,Math.round(v*1000000.0)/1000000.0);}
    private void enter(String side,double price)throws Exception{ if(volume<=0)return; JSONObject t=base("trade"); t.put("trade",new JSONObject().put("actionType","BUY".equals(side)?"ORDER_TYPE_BUY":"ORDER_TYPE_SELL").put("symbol","XAUUSD").put("volume",volume).put("magic",MAGIC).put("clientId","MBENTRY")); emit("trade",t); notifyState("Entry sent: "+side+" "+volume); }
    private void trail(double mid)throws Exception{
        double candidate="BUY".equals(positionSide)?mid-100*pipSize:mid+100*pipSize; boolean improve="BUY".equals(positionSide)?candidate>stopPrice:candidate<stopPrice; if(!improve)return;
        if(stopId.isEmpty()){placeStop(candidate);return;} JSONObject t=base("trade"); t.put("trade",new JSONObject().put("actionType","ORDER_MODIFY").put("orderId",stopId).put("openPrice",candidate).put("magic",MAGIC)); emit("trade",t); stopPrice=candidate;
    }
    private void placeStop(double price)throws Exception{ String side="BUY".equals(positionSide)?"SELL":"BUY"; JSONObject t=base("trade"); t.put("trade",new JSONObject().put("actionType","BUY".equals(side)?"ORDER_TYPE_BUY_STOP":"ORDER_TYPE_SELL_STOP").put("symbol","XAUUSD").put("volume",positionVolume>0?positionVolume:volume).put("openPrice",price).put("magic",MAGIC).put("clientId","MBSTOP")); emit("trade",t); stopSide=side; stopPrice=price; }
    private void reconcile(){
        if(!waitingForStopFill)return; waitingForStopFill=false;
        // The filled stop is expected to create the new opposite market position. Once observed,
        // the old source position is closed and the new position becomes the managed position.
        // A subsequent position/status event will establish the new positionId.
        if(!positionId.isEmpty() && !positionSide.isEmpty()){ try{closeIfStaleSource(); placeStop("BUY".equals(positionSide)?lastMid-100*pipSize:lastMid+100*pipSize);}catch(Exception ignored){} }
    }
    private void closeIfStaleSource()throws Exception{
        // If MetaApi has already replaced the old position, it will carry the same magic and a new id.
        // We deliberately do not close the only current managed position here.
    }
    public void setTrading(boolean on){trading=on;notifyState(on?"BOT RUNNING — live trading":"BOT STOPPED");}
    private void stopEngine(){running=false;trading=false;if(socket!=null){socket.disconnect();socket.close();}stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();notifyState("Stopped");}
    private String fmt(double x){return Double.isNaN(x)?"—":String.format(java.util.Locale.US,"%.2f",x);}
    @Override public void onDestroy(){if(socket!=null){socket.disconnect();socket.close();}super.onDestroy();}
    @Nullable @Override public IBinder onBind(Intent intent){return null;}
}
