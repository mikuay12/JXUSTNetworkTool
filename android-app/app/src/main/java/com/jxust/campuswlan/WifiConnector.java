package com.jxust.campuswlan;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.wifi.WifiConfiguration;
import android.net.wifi.WifiManager;
import android.net.wifi.WifiNetworkSpecifier;
import android.os.Build;
import android.provider.Settings;

import java.util.List;

final class WifiConnector {
    interface StatusListener {
        void onStatus(String message);
    }

    static final String SSID = "JXUST-WLAN";

    private final Activity activity;
    private final ConnectivityManager connectivityManager;
    private ConnectivityManager.NetworkCallback networkCallback;

    WifiConnector(Activity activity) {
        this.activity = activity;
        connectivityManager = (ConnectivityManager) activity.getSystemService(Context.CONNECTIVITY_SERVICE);
    }

    void connect(StatusListener listener) {
        WifiManager wifiManager = (WifiManager) activity.getApplicationContext()
                .getSystemService(Context.WIFI_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            if (!wifiManager.isWifiEnabled()) {
                activity.startActivity(new Intent(Settings.Panel.ACTION_WIFI));
                listener.onStatus("请先在弹出的系统面板中打开 Wi-Fi，然后再次点击连接。");
                return;
            }
            connectWithSpecifier(listener);
        } else {
            connectOnAndroid9(wifiManager, listener);
        }
    }

    private void connectWithSpecifier(StatusListener listener) {
        close();
        WifiNetworkSpecifier specifier = new WifiNetworkSpecifier.Builder()
                .setSsid(SSID)
                .build();
        NetworkRequest request = new NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .setNetworkSpecifier(specifier)
                .build();

        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override
            public void onAvailable(Network network) {
                connectivityManager.bindProcessToNetwork(network);
                listener.onStatus("已连接 " + SSID + "，现在可以点击认证。");
            }

            @Override
            public void onUnavailable() {
                listener.onStatus("未能连接 " + SSID + "，请确认已进入校园 Wi-Fi 覆盖范围。");
            }

            @Override
            public void onLost(Network network) {
                listener.onStatus(SSID + " 连接已断开。");
            }
        };
        listener.onStatus("请在系统提示中确认连接 " + SSID + "…");
        connectivityManager.requestNetwork(request, networkCallback);
    }

    @SuppressWarnings("deprecation")
    private void connectOnAndroid9(WifiManager wifiManager, StatusListener listener) {
        if (!wifiManager.isWifiEnabled() && !wifiManager.setWifiEnabled(true)) {
            listener.onStatus("无法打开 Wi-Fi，请先在系统设置中打开。");
            return;
        }

        int networkId = -1;
        List<WifiConfiguration> configured = wifiManager.getConfiguredNetworks();
        if (configured != null) {
            for (WifiConfiguration item : configured) {
                if (("\"" + SSID + "\"").equals(item.SSID)) {
                    networkId = item.networkId;
                    break;
                }
            }
        }

        if (networkId < 0) {
            WifiConfiguration configuration = new WifiConfiguration();
            configuration.SSID = "\"" + SSID + "\"";
            configuration.allowedKeyManagement.set(WifiConfiguration.KeyMgmt.NONE);
            networkId = wifiManager.addNetwork(configuration);
        }

        if (networkId < 0 || !wifiManager.enableNetwork(networkId, true)) {
            listener.onStatus("无法添加校园 Wi-Fi，请检查位置权限或通过系统设置连接。");
            return;
        }
        wifiManager.reconnect();
        listener.onStatus("已发起连接 " + SSID + "，连接完成后即可认证。");
    }

    void close() {
        if (networkCallback != null) {
            try {
                connectivityManager.unregisterNetworkCallback(networkCallback);
            } catch (IllegalArgumentException ignored) {
                // The callback may already have been released by Android.
            }
            networkCallback = null;
        }
        connectivityManager.bindProcessToNetwork(null);
    }
}
