from pathlib import Path
import re

p = Path('web/main.js')
s = p.read_text()

# Use the official MetaApi streaming connection sequence. In particular, do not
# block on account.waitConnected() before creating the streaming connection;
# the streaming API itself is responsible for connection/synchronization.
new_connect = r'''async function connectSdk(){
  if(connecting||connection)return;
  const token=cleanToken(ui.token.value),accountId=ui.account.value.trim();
  if(!token||token==='SAVED TOKEN'){setStatus('MetaAPI token is missing');return;}
  if(!accountId){setStatus('MetaAPI account ID is missing');return;}
  if(!validAccountId(accountId)){setStatus('MetaAPI account ID format is invalid');return;}

  connecting=true;
  setStatus('Connecting directly to MetaApi…');
  let localApi=null,localAccount=null,localConnection=null;
  try{
    const MetaApiClass=sdkConstructor();
    localApi=new MetaApiClass(token);
    api=localApi;

    localAccount=await localApi.metatraderAccountApi.getAccount(accountId);
    if(!localAccount?.id)throw new Error('MetaApi account not found');
    account=localAccount;

    localConnection=localAccount.getStreamingConnection();
    connection=localConnection;
    listener=new BotListener();
    localConnection.addSynchronizationListener(listener);

    // Official MetaApi sequence: open the streaming connection, then wait for
    // terminal synchronization, then subscribe to the requested symbol.
    await localConnection.connect();
    setStatus('MetaApi connected — synchronizing terminal…');
    await localConnection.waitSynchronized();
    synchronized=true;

    await localConnection.subscribeToMarketData(SYMBOL);
    reconcile();
    setStatus('CONNECTED — XAUUSD live stream active');
  }catch(e){
    const msg=e?.message||String(e);
    synchronized=false;
    try{await localConnection?.close();}catch(_){}
    try{await localApi?.close();}catch(_){}
    connection=null;
    account=null;
    api=null;
    setStatus(`MetaAPI connection failed: ${msg}`);
  }finally{
    connecting=false;
  }
}
'''

pattern=r'async function connectSdk\(\).*?\nfunction ownedPositions\(\)'
updated,count=re.subn(pattern,new_connect+'function ownedPositions()',s,count=1,flags=re.S)
if count!=1:
    raise SystemExit('connectSdk block not found after build-time transforms')
p.write_text(updated)
print('Restored official MetaApi streaming connection startup sequence')