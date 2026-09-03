package com.pipslife.multibot;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import android.util.Base64;

public final class SecureStore {
    private static final String PREFS="multibot_secure"; private static final String KEY_ALIAS="multibot_token_key";
    private final SharedPreferences prefs;
    public SecureStore(Context context){prefs=context.getSharedPreferences(PREFS,Context.MODE_PRIVATE);}
    private SecretKey key()throws Exception{
        java.security.KeyStore ks=java.security.KeyStore.getInstance("AndroidKeyStore");ks.load(null);
        if(!ks.containsAlias(KEY_ALIAS)){KeyGenerator kg=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");kg.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());kg.generateKey();}
        return ((java.security.KeyStore.SecretKeyEntry)ks.getEntry(KEY_ALIAS,null)).getSecretKey();
    }
    public void save(String accountId,String token)throws Exception{Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,key());byte[] iv=c.getIV();byte[] enc=c.doFinal(token.getBytes(java.nio.charset.StandardCharsets.UTF_8));prefs.edit().putString("account",accountId).putString("token",Base64.encodeToString(iv,Base64.NO_WRAP)+"."+Base64.encodeToString(enc,Base64.NO_WRAP)).apply();}
    public String accountId(){return prefs.getString("account","");}
    public String token()throws Exception{String packed=prefs.getString("token","");if(packed.isEmpty())return "";String[] p=packed.split("\\.",2);Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(p[0],Base64.NO_WRAP)));return new String(c.doFinal(Base64.decode(p[1],Base64.NO_WRAP)),java.nio.charset.StandardCharsets.UTF_8);}
    public void clear(){prefs.edit().clear().apply();}
}
