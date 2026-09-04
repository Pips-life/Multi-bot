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

/**
 * Android shell for the browser-capable MetaApi JavaScript SDK.
 * The trading WebView is deliberately kept alive while the foreground
 * trading service is running. Leaving the screen must not stop live trading.
 */
public class MainActivity extends Activity {
    private WebView webView;

    public class BotBridge {
        @JavascriptInterface
        public void startForegroundBot() {
            Intent intent = new Intent(MainActivity.this, BotForegroundService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent);
            } else {
                startService(intent);
            }
        }

        @JavascriptInterface
        public void stopForegroundBot() {
            stopService(new Intent(MainActivity.this, BotForegroundService.class));
        }
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
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
        // Do NOT destroy the trading WebView here. The foreground service keeps
        // the app process alive and the MetaApi JS stream must continue after
        // the user leaves the screen/task. The explicit STOP BOT action is the
        // only normal path that stops trading and its foreground service.
        super.onDestroy();
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            // Minimize instead of finishing the activity so the live MetaApi
            // JavaScript connection remains active in the background.
            moveTaskToBack(true);
        }
    }
}
