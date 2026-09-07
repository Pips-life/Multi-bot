package com.pipslife.multibot;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
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

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Android shell for the browser-capable MetaApi JavaScript SDK. */
public class MainActivity extends Activity {
    private static final String RELEASE_API = "https://api.github.com/repos/Pips-life/Multi-bot/releases/latest";
    private static final String APK_PREFIX = "Pips-life-Multi-bot-update-";
    private WebView webView;
    private long downloadId = -1L;
    private String pendingApkUrl;
    private long pendingVersion = -1L;
    private BroadcastReceiver downloadReceiver;
    private boolean updateCheckInProgress = false;

    public class BotBridge {
        @JavascriptInterface public void startForegroundBot() {
            Intent intent = new Intent(MainActivity.this, BotForegroundService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent); else startService(intent);
        }
        @JavascriptInterface public void stopForegroundBot() {
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
        checkForUpdate(false);
    }

    @Override protected void onResume() {
        super.onResume();
        if (pendingApkUrl != null && canInstallPackages()) {
            String url = pendingApkUrl;
            long version = pendingVersion;
            pendingApkUrl = null;
            pendingVersion = -1L;
            downloadAndInstall(url, version);
        }
    }

    private boolean canInstallPackages() {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.O || getPackageManager().canRequestPackageInstalls();
    }

    private void checkForUpdate(boolean manual) {
        if (updateCheckInProgress) return;
        updateCheckInProgress = true;
        new Thread(() -> {
            HttpURLConnection c = null;
            try {
                URL endpoint = new URL(RELEASE_API + "?t=" + System.currentTimeMillis());
                c = (HttpURLConnection) endpoint.openConnection();
                c.setRequestMethod("GET");
                c.setConnectTimeout(10000);
                c.setReadTimeout(10000);
                c.setUseCaches(false);
                c.setDefaultUseCaches(false);
                c.setRequestProperty("Cache-Control", "no-cache");
                c.setRequestProperty("Accept", "application/vnd.github+json");
                c.setRequestProperty("X-GitHub-Api-Version", "2022-11-28");
                c.setRequestProperty("User-Agent", "Pips-life-Multi-bot-Updater/1.0");
                int response = c.getResponseCode();
                if (response != HttpURLConnection.HTTP_OK) {
                    if (manual) showUpdateStatus("Update check failed (GitHub HTTP " + response + ").");
                    return;
                }
                BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream()));
                StringBuilder b = new StringBuilder();
                String line;
                while ((line = r.readLine()) != null) b.append(line);
                r.close();
                String json = b.toString();

                Matcher tag = Pattern.compile("\\\"tag_name\\\"\\s*:\\s*\\\"v(\\d+)\\\"").matcher(json);
                Matcher asset = Pattern.compile("\\\"name\\\"\\s*:\\s*\\\"Pips-life-Multi-bot\\.apk\\\".*?\\\"browser_download_url\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"", Pattern.DOTALL).matcher(json);
                if (!asset.find()) asset = Pattern.compile("\\\"browser_download_url\\\"\\s*:\\s*\\\"([^\\\"]*Pips-life-Multi-bot\\.apk)\\\"").matcher(json);
                if (!tag.find() || !asset.find()) {
                    if (manual) showUpdateStatus("No valid Pips-life APK release was found.");
                    return;
                }

                long remote = Long.parseLong(tag.group(1));
                PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), 0);
                long local = Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
                String apkUrl = asset.group(1).replace("\\u0026", "&");

                if (remote <= local) {
                    if (manual) showUpdateStatus("You are up to date (build " + local + ").");
                    return;
                }
                runOnUiThread(() -> showUpdateDialog(remote, local, apkUrl));
            } catch (Exception e) {
                if (manual) showUpdateStatus("Update check failed. Check your internet connection and try again.");
            } finally {
                updateCheckInProgress = false;
                if (c != null) c.disconnect();
            }
        }).start();
    }

    private void showUpdateStatus(String message) {
        runOnUiThread(() -> new AlertDialog.Builder(this)
                .setTitle("Pips-life updater")
                .setMessage(message)
                .setPositiveButton("OK", null)
                .show());
    }

    private void showUpdateDialog(long remoteVersion, long localVersion, String apkUrl) {
        new AlertDialog.Builder(this)
                .setTitle("Pips-life update available")
                .setMessage("Installed build: " + localVersion + "\nLatest build: " + remoteVersion + "\n\nUpdate now? Your saved MetaApi credentials stay in app storage.")
                .setNegativeButton("Later", null)
                .setPositiveButton("Update now", (d, w) -> {
                    if (!canInstallPackages()) {
                        pendingApkUrl = apkUrl;
                        pendingVersion = remoteVersion;
                        try {
                            startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                    Uri.parse("package:" + getPackageName())));
                        } catch (Exception ignored) { }
                    } else {
                        downloadAndInstall(apkUrl, remoteVersion);
                    }
                })
                .show();
    }

    private void downloadAndInstall(String apkUrl, long remoteVersion) {
        DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
        String fileName = APK_PREFIX + remoteVersion + ".apk";
        try { dm.remove(downloadId); } catch (Exception ignored) { }
        DownloadManager.Request req = new DownloadManager.Request(Uri.parse(apkUrl));
        req.setTitle("Pips-life update");
        req.setDescription("Downloading Pips-life Multi-bot " + remoteVersion);
        req.setMimeType("application/vnd.android.package-archive");
        req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        req.setAllowedOverMetered(true);
        req.setAllowedOverRoaming(true);
        req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);
        downloadId = dm.enqueue(req);

        if (downloadReceiver != null) {
            try { unregisterReceiver(downloadReceiver); } catch (Exception ignored) { }
        }
        downloadReceiver = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                if (!DownloadManager.ACTION_DOWNLOAD_COMPLETE.equals(intent.getAction())) return;
                long id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L);
                if (id != downloadId) return;
                int status = DownloadManager.STATUS_FAILED;
                try {
                    android.database.Cursor cursor = dm.query(new DownloadManager.Query().setFilterById(id));
                    if (cursor != null) {
                        if (cursor.moveToFirst()) status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
                        cursor.close();
                    }
                } catch (Exception ignored) { }
                if (status == DownloadManager.STATUS_SUCCESSFUL) {
                    Uri uri = dm.getUriForDownloadedFile(id);
                    if (uri != null) {
                        Intent install = new Intent(Intent.ACTION_VIEW);
                        install.setDataAndType(uri, "application/vnd.android.package-archive");
                        install.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                        try { startActivity(install); } catch (Exception e) { showUpdateStatus("Could not open the downloaded update. Please open Downloads and install " + fileName + "."); }
                    } else {
                        showUpdateStatus("Update download completed but Android could not access the APK.");
                    }
                } else {
                    showUpdateStatus("Update download failed. Please try again.");
                }
                try { unregisterReceiver(this); } catch (Exception ignored) { }
                downloadReceiver = null;
            }
        };
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(downloadReceiver, new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE), Context.RECEIVER_NOT_EXPORTED);
        else registerReceiver(downloadReceiver, new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE));
    }

    @Override protected void onDestroy() {
        if (downloadReceiver != null) {
            try { unregisterReceiver(downloadReceiver); } catch (Exception ignored) { }
            downloadReceiver = null;
        }
        if (webView != null) {
            webView.loadUrl("about:blank"); webView.stopLoading(); webView.destroy(); webView = null;
        }
        super.onDestroy();
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack(); else super.onBackPressed();
    }
}
