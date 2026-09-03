package com.pipslife.multibot;

import android.app.*;
import android.content.*;
import android.os.IBinder;
import android.os.Build;
import android.content.pm.ServiceInfo;
import org.json.*;
import java.util.*;
import io.socket.client.IO;
import io.socket.client.Socket;

public class TradingService extends Service {
    public static final String ACTION_START="START", ACTION_STOP="STOP", ACTION_STATUS="STATUS";
    private static final String URL="https://mt-client-api-v1.agiliumtrade.agiliumtrade.ai";
    private static final String CHANNEL="multibot";
    private static final int MAGIC=260903;
    private Socket socket; private String accountId, token;
    private volatile boolean running=false, trading=false;
    private double lastMid=Double.NaN, balance=0, pipSize=0.01, pipValue=0, volume=0;
    private double minVolume=0.01, maxVolume=100, volumeStep=0.01;
    private String positionId="", positionSide="", sourcePositionId="";
    private double positionPrice=0, positionVolume=0;
    private String stopId="", stopSide=""; private double stopPrice=0;
    private boolean waitingForStopFill=false;
    private String synchronizeRequestId="", waitRequestId="";

    @Override public void onCreate(){ super.onCreate(); createChannel(); }
    private void createChannel(){ if(Build.VERSION.SDK_INT>=26){ NotificationChannel c=new NotificationChannel(CHANNEL,"Multi-bot",NotificationManager.IMPORTANCE_LOW); getSystemService(NotificationManager.class).createNotificationChannel(c); } }
    private void notifyState(String text){ Intent i=new Intent(ACTION_STATUS); i.setPackage(getPackageName()); i.putExtra("text",text); i.putExtra("bid",lastMid); i.putExtra("balance",balance); i.putExtra("side",positionSide); i.putExtra("stop",stopPrice); sendBroadcast(i); }
    private void foreground(String text){ Notification.Builder b=Build.VERSION.SDK_INT>=26?new Notification.Builder(this,CHANNEL):new Notification.Builder(this); b.setContentTitle("Multi-bot").setContentText(text).setSmallIcon(android.R.drawable.ic_menu_compass).setOngoing(true); if(Build.VERSION.SDK_INT>=29)startForeground(7,b.build(),ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC); else startForeground(7,b.build()); }

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
            SecureStore s=new SecureStore(this); accountId=s.accountId(); token=s.token();
            if(accountId.isEmpty()||token.isEmpty())throw new Exception("MetaAPI credentials are not saved");
            connect();
        } catch(Exception e){
            running=false; notifyState("Setup required: "+safe(e)); stopForeground(STOP_FOREGROUND_REMOVE);
        }
    }

    private void connect()throws Exception{
        IO.Options o=new IO.Options();
        o.path="/ws";
        o.query="auth-token="+token;
        o.reconnection=true;
        o.timeout=15000;
        socket=IO.socket(URL,o);

        socket.on(Socket.EVENT_CONNECT,args->{
            notifyState("MetaApi socket connected — authenticating account…");
            JSONObject req=base("subscribe");
            emit(req);
        });
        socket.on(Socket.EVENT_CONNECT_ERROR,args->{
            notifyState("MetaApi connection error: "+(args.length>0?safe(args[0]):"unknown error"));
        });
        socket.on(Socket.EVENT_ERROR,args->{
            notifyState("MetaApi socket error: "+(args.length>0?safe(args[0]):"unknown error"));
        });
        socket.on(Socket.EVENT_DISCONNECT,args->{
            if(running)notifyState("MetaApi disconnected — reconnecting…");
        });
        socket.on("response",args->{
            if(args.length>0)try{handleResponse((JSONObject)args[0]);}catch(Exception e){notifyState("MetaApi response error: "+safe(e));}
        });
        socket.on("synchronization",args->{
            if(args.length>0)try{handleSync((JSONObject)args[0]);}catch(Exception e){notifyState("MetaApi sync error: "+safe(e));}
        });
        socket.on("processingError",args->{
            notifyState("MetaApi rejected request: "+(args.length>0?safe(args[0]):"unknown error"));
        });
        socket.connect();
    }

    private JSONObject base(String type){
        JSONObject j=new JSONObject();
        try{j.put("accountId",accountId).put("type",type).put("requestId",UUID.randomUUID().toString());}catch(Exception ignored){}
        return j;
    }
    private void emit(JSONObject payload){if(socket!=null&&socket.connected())socket.emit("request",payload);}

    private void handleResponse(JSONObject d)throws Exception{
        String type=d.optString("type");
        String requestId=d.optString("requestId");
        if("response".equals(type) && requestId.equals(synchronizeRequestId)){
            JSONObject req=base("waitSynchronized"); waitRequestId=req.optString("requestId"); emit(req);
            notifyState("MetaApi authenticated — synchronizing terminal…");
        } else if("response".equals(type) && requestId.equals(waitRequestId)){
            subscribeMarketData();
            notifyState("Terminal synchronized — XAUUSD live stream active");
        } else if("tradeResult".equals(type)){
            JSONObject r=d.optJSONObject("response");
            if(r!=null && r.optInt("numericCode",0)!=10009 && r.optInt("numericCode",0)!=0){
                notifyState("Trade error: "+r.optString("stringCode",r.optString("message","unknown")));
            }
        }
    }

    private void handleSync(JSONObject d)throws Exception{
        String type=d.optString("type");
        if("authenticated".equals(type)){
            JSONObject req=base("synchronize");
            synchronizeRequestId=req.optString("requestId");
            emit(req);
            notifyState("MetaApi account authenticated — requesting terminal synchronization…");
        }
        else if("accountInformation".equals(type)){
            JSONObject a=d.optJSONObject("accountInformation");
            if(a!=null)balance=a.optDouble("balance",balance);
            recalcVolume();
        }
        else if("specifications".equals(type)){
            JSONArray a=d.optJSONArray("specifications");
            if(a!=null)for(int i=0;i<a.length();i++){
                JSONObject x=a.getJSONObject(i);
                if("XAUUSD".equals(x.optString("symbol"))){
                    double ps=x.optDouble("pipSize",0);
                    if(ps>0)pipSize=ps; else pipSize=x.optDouble("point",x.optDouble("tickSize",pipSize));
                    minVolume=x.optDouble("minVolume",minVolume);
                    maxVolume=x.optDouble("maxVolume",maxVolume);
                    volumeStep=x.optDouble("volumeStep",volumeStep);
                }
            }
            recalcVolume();
        }
        else if("positions".equals(type)){
            JSONArray a=d.optJSONArray("positions");if(a!=null)syncPositions(a);
        }
        else if("orders".equals(type)){
            JSONArray a=d.optJSONArray("orders");if(a!=null)syncOrders(a);
        }
        else if("prices".equals(type)){
            JSONArray a=d.optJSONArray("prices");
            if(a!=null)for(int i=0;i<a.length();i++){
                JSONObject p=a.getJSONObject(i);
                if("XAUUSD".equals(p.optString("symbol")))onPrice(p);
            }
        }
        else if("status".equals(type))handleStatus(d);
        else if("update".equals(type))handleStatus(d);
    }

    private void subscribeMarketData()throws Exception{
        JSONObject sub=base("subscribeToMarketData");
        sub.put("symbol","XAUUSD");
        sub.put("subscriptions",new JSONArray()
            .put(new JSONObject().put("type","ticks"))
            .put(new JSONObject().put("type","quotes")));
        emit(sub);
    }

    private void syncPositions(JSONArray a){
        String previous=positionId;
        positionId="";positionSide="";
        for(int i=0;i<a.length();i++)try{JSONObject p=a.getJSONObject(i);if(isOurs(p))upsertPosition(p);}catch(Exception ignored){}
        if(!previous.isEmpty() && positionId.isEmpty()) waitingForStopFill=false;
    }
    private void syncOrders(JSONArray a){
        stopId="";
        for(int i=0;i<a.length();i++)try{JSONObject o=a.getJSONObject(i);if(isOurs(o)&&o.optString("type").contains("STOP"))upsertOrder(o);}catch(Exception ignored){}
    }
    private boolean isOurs(JSONObject x){return "XAUUSD".equals(x.optString("symbol"))&&x.optInt("magic",-1)==MAGIC;}
    private void upsertPosition(JSONObject p){
        positionId=p.optString("id",p.optString("positionId",positionId));
        positionSide=p.optString("type").contains("BUY")?"BUY":"SELL";
        positionPrice=p.optDouble("openPrice",positionPrice);
        positionVolume=p.optDouble("volume",positionVolume);
    }
    private void upsertOrder(JSONObject o){
        stopId=o.optString("id",o.optString("orderId",stopId));
        stopSide=o.optString("type").contains("BUY")?"BUY":"SELL";
        stopPrice=o.optDouble("openPrice",stopPrice);
    }

    private void handleStatus(JSONObject d)throws Exception{
        JSONArray done=d.optJSONArray("completedOrderIds");
        if(done!=null)for(int i=0;i<done.length();i++)if(stopId.equals(done.optString(i))){waitingForStopFill=true;stopId="";}
        JSONArray up=d.optJSONArray("updatedPositions");
        if(waitingForStopFill&&up!=null){
            for(int i=0;i<up.length();i++){
                JSONObject p=up.getJSONObject(i);
                if(isOurs(p)){
                    String newId=p.optString("id",p.optString("positionId"));
                    String newSide=p.optString("type").contains("BUY")?"BUY":"SELL";
                    if(!newId.equals(sourcePositionId) && !newId.isEmpty()){
                        String oldId=sourcePositionId.isEmpty()?positionId:sourcePositionId;
                        if(!oldId.isEmpty()&&!oldId.equals(newId))closePosition(oldId);
                        positionId=newId; positionSide=newSide; positionPrice=p.optDouble("openPrice",0); positionVolume=p.optDouble("volume",volume);
                        waitingForStopFill=false; sourcePositionId=positionId; placeStopForCurrent();
                        break;
                    }
                }
            }
        }
        if(up!=null)for(int i=0;i<up.length();i++)try{JSONObject p=up.getJSONObject(i);if(isOurs(p))upsertPosition(p);}catch(Exception ignored){}
        JSONArray rem=d.optJSONArray("removedPositionIds");
        if(rem!=null)for(int i=0;i<rem.length();i++)if(positionId.equals(rem.optString(i)))positionId="";
        JSONArray ord=d.optJSONArray("updatedOrders");
        if(ord!=null)for(int i=0;i<ord.length();i++)try{JSONObject o=ord.getJSONObject(i);if(isOurs(o)&&o.optString("type").contains("STOP"))upsertOrder(o);}catch(Exception ignored){}
    }

    private void onPrice(JSONObject p)throws Exception{
        double bid=p.optDouble("bid",Double.NaN),ask=p.optDouble("ask",Double.NaN);
        if(Double.isNaN(bid)||Double.isNaN(ask))return;
        double mid=(bid+ask)/2;
        double tv=p.optDouble("profitTickValue",0); if(tv>0){pipValue=tv;recalcVolume();}
        double prev=lastMid;lastMid=mid;
        if(!trading){notifyState("Live XAUUSD: "+fmt(mid));return;}
        if(Double.isNaN(prev)){notifyState("Streaming XAUUSD — waiting for first movement");return;}
        if(positionId.isEmpty()){
            if(prev<mid)enter("BUY",ask); else if(prev>mid)enter("SELL",bid);
        } else trail(mid);
        notifyState(positionSide.isEmpty()?"Waiting for entry":"Running "+positionSide+" | STOP "+fmt(stopPrice));
    }

    private void recalcVolume(){
        if(balance>0&&pipValue>0){double raw=(balance*0.01)/(100.0*pipValue);volume=normalize(raw);}
    }
    private double normalize(double v){
        v=Math.max(minVolume,Math.min(maxVolume,v));
        if(volumeStep>0)v=Math.floor(v/volumeStep)*volumeStep;
        return Math.max(minVolume,Math.round(v*1000000.0)/1000000.0);
    }
    private void enter(String side,double price)throws Exception{
        if(volume<=0)return;
        JSONObject t=base("trade");
        t.put("trade",new JSONObject()
            .put("actionType","BUY".equals(side)?"ORDER_TYPE_BUY":"ORDER_TYPE_SELL")
            .put("symbol","XAUUSD").put("volume",volume).put("magic",MAGIC)
            .put("clientId","MBENTRY"));
        emit(t);
    }
    private void trail(double mid)throws Exception{
        double candidate="BUY".equals(positionSide)?mid-100*pipSize:mid+100*pipSize;
        boolean improve="BUY".equals(positionSide)?candidate>stopPrice:candidate<stopPrice;
        if(stopId.isEmpty()){
            if(improve||stopPrice==0)placeStop(candidate);
            return;
        }
        if(improve){
            JSONObject t=base("trade");
            t.put("trade",new JSONObject().put("actionType","ORDER_MODIFY").put("orderId",stopId).put("openPrice",candidate).put("magic",MAGIC));
            emit(t); stopPrice=candidate;
        }
    }
    private void placeStopForCurrent()throws Exception{if(positionId.isEmpty())return;double price="BUY".equals(positionSide)?positionPrice-100*pipSize:positionPrice+100*pipSize;placeStop(price);}
    private void placeStop(double price)throws Exception{
        String side="BUY".equals(positionSide)?"SELL":"BUY";
        JSONObject t=base("trade");
        t.put("trade",new JSONObject()
            .put("actionType","BUY".equals(side)?"ORDER_TYPE_BUY_STOP":"ORDER_TYPE_SELL_STOP")
            .put("symbol","XAUUSD").put("volume",positionVolume>0?positionVolume:volume)
            .put("openPrice",price).put("magic",MAGIC).put("clientId","MBSTOP"));
        emit(t); stopSide=side; stopPrice=price; sourcePositionId=positionId;
    }
    private void closePosition(String id)throws Exception{
        if(id==null||id.isEmpty())return;
        JSONObject t=base("trade");
        t.put("trade",new JSONObject().put("actionType","POSITION_CLOSE_ID").put("positionId",id).put("magic",MAGIC));
        emit(t);
    }
    public void setTrading(boolean on){trading=on;getSharedPreferences("runtime",0).edit().putBoolean("trading",on).apply();notifyState(on?"BOT RUNNING — live trading":"BOT STOPPED");}
    private void stopEngine(){running=false;trading=false;getSharedPreferences("runtime",0).edit().putBoolean("trading",false).apply();if(socket!=null){socket.disconnect();socket.close();}stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();notifyState("Stopped");}
    private String fmt(double x){return Double.isNaN(x)?"—":String.format(Locale.US,"%.2f",x);}
    private String safe(Object x){String s=String.valueOf(x);return s.length()>180?s.substring(0,180):s;}
    @Override public void onDestroy(){if(socket!=null){socket.disconnect();socket.close();}super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
}
