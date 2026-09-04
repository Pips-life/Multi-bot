package com.pipslife.multibot;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    private WebView webView;
    private SecureStore secureStore;

    public class BotBridge {
        @JavascriptInterface
        public void startForegroundBot() {
            Intent intent = new Intent(MainActivity.this, BotForegroundService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent);
            else startService(intent);
        }

        @JavascriptInterface
        public void stopForegroundBot() {
            stopService(new Intent(MainActivity.this, BotForegroundService.class));
        }

        @JavascriptInterface
        public boolean saveCredentials(String accountId, String token) {
            try {
                secureStore.save(accountId, token);
                return true;
            } catch (Exception e) {
                return false;
            }
        }

        @JavascriptInterface
        public String getSavedToken() {
            try { return secureStore.token(); }
            catch (Exception e) { return ""; }
        }

        @JavascriptInterface
        public String getSavedAccountId() {
            try { return secureStore.accountId(); }
            catch (Exception e) { return ""; }
        }

        @JavascriptInterface
        public void clearCredentials() {
            secureStore.clear();
        }
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        secureStore = new SecureStore(this);
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setLoadsImagesAutomatically(true);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        webView.addJavascriptInterface(new BotBridge(), "AndroidBot");
        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());
        setContentView(webView);
        webView.loadUrl("file:///android_asset/index.html");
    }

    @Override protected void onDestroy() {
        // Keep the foreground service independent from the Activity lifecycle.
        // The bot is stopped only by the explicit STOP BOT action.
        super.onDestroy();
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else moveTaskToBack(true);
    }
}
