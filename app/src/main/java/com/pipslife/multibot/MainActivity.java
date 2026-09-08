package com.pipslife.multibot;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends Activity {
    private static final String RELEASE_API = "https://api.github.com/repos/Pips-life/Multi-bot/releases/latest";
    private static final String APK_ASSET = "Pips-life-Multi-bot.apk";
    private WebView webView;

    public class BotBridge {
        @JavascriptInterface public void startForegroundBot() {
            Intent intent = new Intent(MainActivity.this, BotForegroundService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent); else startService(intent);
        }
        @JavascriptInterface public void stopForegroundBot() { stopService(new Intent(MainActivity.this, BotForegroundService.class)); }
        @JavascriptInterface public void checkForUpdate() { MainActivity.this.checkForUpdate(true); }
        @JavascriptInterface public void installLatestUpdate() { MainActivity.this.checkForUpdateAndDownload(); }
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true); s.setDomStorageEnabled(true); s.setDatabaseEnabled(true);
        s.setAllowFileAccess(true); s.setAllowContentAccess(true); s.setLoadsImagesAutomatically(true);
        s.setBuiltInZoomControls(false); s.setDisplayZoomControls(false);
        webView.addJavascriptInterface(new BotBridge(), "AndroidBot");
        webView.setWebViewClient(new WebViewClient()); webView.setWebChromeClient(new WebChromeClient());
        setContentView(webView); webView.loadUrl("file:///android_asset/index.html");
        new android.os.Handler(getMainLooper()).postDelayed(() -> checkForUpdate(false), 1800);
    }

    private String installedVersion() {
        try { PackageInfo p = getPackageManager().getPackageInfo(getPackageName(), 0); return p.versionName == null ? "0.0" : p.versionName; }
        catch (Exception e) { return "0.0"; }
    }

    private void checkForUpdate(boolean showCurrent) {
        new Thread(() -> {
            try {
                JSONObject release = fetchRelease(); String remote = release.optString("tag_name", "").replaceFirst("^v", "");
                String url = findApkUrl(release);
                if (compareVersions(remote, installedVersion()) > 0 && !url.isEmpty()) runOnUiThread(() -> showUpdateDialog(remote));
                else if (showCurrent) runOnUiThread(() -> notifyJs("CURRENT", installedVersion()));
            } catch (Exception e) { if (showCurrent) runOnUiThread(() -> notifyJs("ERROR", "Update check unavailable")); }
        }).start();
    }

    private void checkForUpdateAndDownload() {
        new Thread(() -> {
            try {
                JSONObject release = fetchRelease(); String remote = release.optString("tag_name", "").replaceFirst("^v", "");
                String url = findApkUrl(release);
                if (compareVersions(remote, installedVersion()) <= 0 || url.isEmpty()) { runOnUiThread(() -> notifyJs("CURRENT", installedVersion())); return; }
                runOnUiThread(() -> beginDownload(remote, url));
            } catch (Exception e) { runOnUiThread(() -> new AlertDialog.Builder(this).setTitle("Update unavailable").setMessage("Could not reach the Pips-life release server. Try again when internet is available.").setPositiveButton("OK", null).show()); }
        }).start();
    }

    private JSONObject fetchRelease() throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(RELEASE_API).openConnection();
        c.setConnectTimeout(10000); c.setReadTimeout(15000); c.setRequestProperty("Accept", "application/vnd.github+json"); c.setRequestProperty("User-Agent", "Pips-life-Multi-bot-Updater");
        InputStream in = c.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] b = new byte[8192]; int n;
        while ((n = in.read(b)) != -1) out.write(b, 0, n); in.close(); c.disconnect(); return new JSONObject(out.toString("UTF-8"));
    }

    private String findApkUrl(JSONObject release) {
        JSONArray assets = release.optJSONArray("assets"); if (assets == null) return "";
        for (int i = 0; i < assets.length(); i++) { JSONObject a = assets.optJSONObject(i); if (a != null && APK_ASSET.equals(a.optString("name"))) return a.optString("browser_download_url", ""); }
        return "";
    }

    private void showUpdateDialog(String version) {
        notifyJs("AVAILABLE", version);
        new AlertDialog.Builder(this).setTitle("Pips-life update available")
                .setMessage("Version " + version + " is ready. Stop the bot before updating so no live position is interrupted.")
                .setNegativeButton("Later", null).setPositiveButton("UPDATE", (d,w) -> checkForUpdateAndDownload()).show();
    }

    private void beginDownload(String version, String url) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !getPackageManager().canRequestPackageInstalls()) {
            new AlertDialog.Builder(this).setTitle("Allow Pips-life updates")
                    .setMessage("Android must allow Pips-life to install its signed updates. Enable this once, then press UPDATE again.")
                    .setPositiveButton("Open Settings", (d,w) -> startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName()))))
                    .setNegativeButton("Cancel", null).show(); return;
        }
        try {
            DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
            r.setTitle("Pips-life Multi-bot " + version); r.setDescription("Downloading signed release update");
            r.setMimeType("application/vnd.android.package-archive"); r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            r.setAllowedOverMetered(true); r.setAllowedOverRoaming(false);
            r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "Pips-life-Multi-bot-v" + version + ".apk");
            dm.enqueue(r); notifyJs("DOWNLOADING", version);
            new AlertDialog.Builder(this).setTitle("Downloading update").setMessage("Version " + version + " is downloading to Downloads. Android will open the installer when it finishes.").setPositiveButton("OK", null).show();
        } catch (Exception e) { new AlertDialog.Builder(this).setTitle("Download failed").setMessage("Could not start the APK download. Check storage and internet access.").setPositiveButton("OK", null).show(); }
    }

    private void notifyJs(String type, String value) {
        if (webView == null) return; webView.evaluateJavascript("window.onPipslifeUpdater&&window.onPipslifeUpdater(" + JSONObject.quote(type) + "," + JSONObject.quote(value) + ")", null);
    }

    private static int compareVersions(String a, String b) {
        try { String[] x=a.split("\\."), y=b.split("\\."); for(int i=0;i<Math.max(x.length,y.length);i++){int xv=i<x.length?Integer.parseInt(x[i].replaceAll("[^0-9].*","")):0;int yv=i<y.length?Integer.parseInt(y[i].replaceAll("[^0-9].*","")):0;if(xv!=yv)return Integer.compare(xv,yv);} } catch(Exception ignored){} return 0;
    }

    @Override protected void onDestroy() { if(webView!=null){webView.loadUrl("about:blank");webView.stopLoading();webView.destroy();webView=null;} super.onDestroy(); }
    @Override public void onBackPressed() { if(webView!=null&&webView.canGoBack())webView.goBack();else super.onBackPressed(); }
}
