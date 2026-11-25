package com.jxust.campuswlan;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.URI;
import java.net.URL;
import java.net.URLEncoder;
import java.io.UnsupportedEncodingException;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class CampusNetworkClient {
    private static final String LOGIN_URL = "http://10.17.8.18:801/eportal/portal/login";
    private static final String LOGIN_REFERER = "http://10.17.8.18/";
    private static final String LOGOUT_BASE_URL = "http://drcom.jxust.edu.cn:60001";
    private static final String[] CARRIER_SUFFIXES = {"@telecom", "@cmcc", "@unicom"};
    private static final int TIMEOUT_MS = 10_000;
    private static final Pattern CHECK_CODE = Pattern.compile(
            "name=[\\\"']checkcode[\\\"']\\s+value=[\\\"']([^\\\"']+)[\\\"']",
            Pattern.CASE_INSENSITIVE
    );

    private final ConnectivityManager connectivityManager;
    private final Network wifiNetwork;
    private final String localIp;

    CampusNetworkClient(Context context) throws IOException {
        connectivityManager = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        wifiNetwork = findWifiNetwork();
        if (wifiNetwork == null) {
            throw new IOException("未检测到 Wi-Fi 连接，请先连接 " + WifiConnector.SSID + "。");
        }
        localIp = findIpv4Address(wifiNetwork);
        if (localIp.isEmpty()) {
            throw new IOException("Wi-Fi 尚未获得 IP 地址，请稍后重试。");
        }
    }

    String login(String account, String password, String carrierSuffix) throws IOException, JSONException {
        Map<String, String> parameters = new LinkedHashMap<>();
        parameters.put("callback", "dr1003");
        parameters.put("login_method", "1");
        parameters.put("user_account", appendSuffix(account, carrierSuffix));
        parameters.put("user_password", password);
        parameters.put("wlan_user_ip", localIp);
        parameters.put("wlan_user_ipv6", "");
        parameters.put("wlan_user_mac", "");
        parameters.put("wlan_ac_ip", "");
        parameters.put("wlan_ac_name", "");
        parameters.put("jsVersion", "4.1.3");
        parameters.put("terminal_type", "1");
        parameters.put("lang", "zh-cn");
        parameters.put("v", String.valueOf(ThreadLocalRandom.current().nextInt(1000, 10000)));

        HttpURLConnection connection = open(LOGIN_URL + "?" + encode(parameters));
        connection.setRequestProperty("Referer", LOGIN_REFERER);
        Response response = execute(connection);
        if (response.code < 200 || response.code >= 300) {
            throw new IOException("认证服务器返回 HTTP " + response.code + "。");
        }
        return describePortalResponse(response.body, "认证");
    }

    String logout(String account, String password) throws IOException, JSONException {
        Session session = new Session();
        Response page = session.get(LOGOUT_BASE_URL + "/Self/login/", true);
        Matcher matcher = CHECK_CODE.matcher(page.body);
        if (!matcher.find()) {
            throw new IOException("无法读取注销页面，请确认校园网服务可访问。");
        }
        String checkCode = matcher.group(1);

        session.get(LOGOUT_BASE_URL + "/Self/login/randomCode?t=" + Math.random(), true);
        Map<String, String> loginForm = new LinkedHashMap<>();
        loginForm.put("checkcode", checkCode);
        loginForm.put("account", account);
        loginForm.put("password", password);
        loginForm.put("code", "");
        session.post(
                LOGOUT_BASE_URL + "/Self/login/verify",
                encode(loginForm),
                LOGOUT_BASE_URL + "/Self/login/?302=LI"
        );

        waitForServer();

        Response online = session.get(
                LOGOUT_BASE_URL + "/Self/dashboard/getOnlineList?t=" + Math.random()
                        + "&_=" + System.currentTimeMillis(),
                true
        );
        requireSuccess(online, "读取在线设备");
        JSONArray devices = parseDeviceList(online.body);
        if (devices.length() == 0) {
            return "当前账号没有设备在线。";
        }

        JSONObject device = devices.getJSONObject(0);
        String sessionId = device.optString("sessionId");
        if (sessionId.isEmpty()) {
            throw new IOException("在线记录缺少会话编号，无法注销。");
        }

        waitForServer();
        Response offline = session.get(
                LOGOUT_BASE_URL + "/Self/dashboard/tooffline?t=" + Math.random()
                        + "&sessionid=" + urlEncode(sessionId),
                true
        );
        requireSuccess(offline, "注销设备");
        JSONObject result = new JSONObject(offline.body);
        if (result.optBoolean("success")) {
            return "注销成功，设备 " + device.optString("ip") + " 已断网。";
        }
        return "注销失败：" + result.optString("message", offline.body);
    }

    private static void waitForServer() throws IOException {
        try {
            Thread.sleep(500);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IOException("操作已取消。", exception);
        }
    }

    private static void requireSuccess(Response response, String operation) throws IOException {
        if (response.code < 200 || response.code >= 300) {
            throw new IOException(operation + "失败，HTTP " + response.code + "。");
        }
    }

    private Network findWifiNetwork() {
        for (Network network : connectivityManager.getAllNetworks()) {
            NetworkCapabilities capabilities = connectivityManager.getNetworkCapabilities(network);
            if (capabilities != null
                    && capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
                return network;
            }
        }
        return null;
    }

    private String findIpv4Address(Network network) {
        LinkProperties properties = connectivityManager.getLinkProperties(network);
        if (properties == null) {
            return "";
        }
        for (LinkAddress address : properties.getLinkAddresses()) {
            if (address.getAddress() instanceof Inet4Address
                    && !address.getAddress().isLoopbackAddress()) {
                return address.getAddress().getHostAddress();
            }
        }
        return "";
    }

    private HttpURLConnection open(String address) throws IOException {
        return (HttpURLConnection) wifiNetwork.openConnection(new URL(address));
    }

    private Response execute(HttpURLConnection connection) throws IOException {
        connection.setConnectTimeout(TIMEOUT_MS);
        connection.setReadTimeout(TIMEOUT_MS);
        connection.setUseCaches(false);
        connection.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android) CampusWlanTool/1.0");
        int code = connection.getResponseCode();
        InputStream stream = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
        String body = stream == null ? "" : readAll(stream);
        connection.disconnect();
        return new Response(code, body);
    }

    private static String appendSuffix(String account, String carrierSuffix) {
        String trimmed = account.trim();
        String lower = trimmed.toLowerCase(Locale.ROOT);
        for (String knownSuffix : CARRIER_SUFFIXES) {
            if (lower.endsWith(knownSuffix)) {
                trimmed = trimmed.substring(0, trimmed.length() - knownSuffix.length());
                break;
            }
        }
        return trimmed + carrierSuffix;
    }

    private static String encode(Map<String, String> values) {
        StringBuilder result = new StringBuilder();
        for (Map.Entry<String, String> entry : values.entrySet()) {
            if (result.length() > 0) {
                result.append('&');
            }
            result.append(urlEncode(entry.getKey())).append('=').append(urlEncode(entry.getValue()));
        }
        return result.toString();
    }

    private static String urlEncode(String value) {
        try {
            return URLEncoder.encode(value, "UTF-8");
        } catch (UnsupportedEncodingException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static String readAll(InputStream stream) throws IOException {
        StringBuilder result = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                result.append(line);
            }
        }
        return result.toString();
    }

    private static String describePortalResponse(String body, String operation) throws JSONException {
        int start = body.indexOf('{');
        int end = body.lastIndexOf('}');
        if (start < 0 || end <= start) {
            return operation + "服务器响应：" + body;
        }
        JSONObject result = new JSONObject(body.substring(start, end + 1));
        String message = result.optString("msg", result.optString("message", ""));
        Object status = result.opt("result");
        boolean success = status instanceof Number && ((Number) status).intValue() == 1;
        if (!success && status != null) {
            success = "1".equals(String.valueOf(status)) || "success".equalsIgnoreCase(String.valueOf(status));
        }
        if (message.isEmpty()) {
            message = result.toString();
        }
        return success ? operation + "成功：" + message : operation + "结果：" + message;
    }

    private static JSONArray parseDeviceList(String body) throws JSONException {
        String trimmed = body.trim();
        if (trimmed.startsWith("[")) {
            return new JSONArray(trimmed);
        }
        JSONObject object = new JSONObject(trimmed);
        JSONArray list = object.optJSONArray("data");
        if (list == null) {
            list = object.optJSONArray("rows");
        }
        return list == null ? new JSONArray() : list;
    }

    private final class Session {
        private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);

        Response get(String address, boolean ajaxWhenDashboard) throws IOException {
            HttpURLConnection connection = open(address);
            connection.setInstanceFollowRedirects(true);
            prepare(connection);
            if (ajaxWhenDashboard && address.contains("/dashboard/")) {
                connection.setRequestProperty("X-Requested-With", "XMLHttpRequest");
                connection.setRequestProperty("Referer", LOGOUT_BASE_URL + "/Self/dashboard");
            }
            attachCookies(connection);
            Response response = executeAndSaveCookies(connection);
            return response;
        }

        Response post(String address, String body, String referer) throws IOException {
            HttpURLConnection connection = open(address);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            prepare(connection);
            connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8");
            connection.setRequestProperty("Referer", referer);
            attachCookies(connection);
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }
            return executeAndSaveCookies(connection);
        }

        private void attachCookies(HttpURLConnection connection) throws IOException {
            Map<String, List<String>> headers = cookies.get(
                    URI.create(connection.getURL().toString()),
                    Collections.emptyMap()
            );
            for (Map.Entry<String, List<String>> header : headers.entrySet()) {
                if (!header.getValue().isEmpty()) {
                    connection.setRequestProperty(header.getKey(), String.join("; ", header.getValue()));
                }
            }
        }

        private Response executeAndSaveCookies(HttpURLConnection connection) throws IOException {
            int code = connection.getResponseCode();
            cookies.put(URI.create(connection.getURL().toString()), connection.getHeaderFields());
            InputStream stream = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
            String body = stream == null ? "" : readAll(stream);
            connection.disconnect();
            return new Response(code, body);
        }

        private void prepare(HttpURLConnection connection) {
            connection.setConnectTimeout(TIMEOUT_MS);
            connection.setReadTimeout(TIMEOUT_MS);
            connection.setUseCaches(false);
            connection.setRequestProperty("User-Agent", "Mozilla/5.0");
            connection.setRequestProperty("Accept-Language", "zh-CN,zh;q=0.9");
        }
    }

    private static final class Response {
        final int code;
        final String body;

        Response(int code, String body) {
            this.code = code;
            this.body = body;
        }
    }
}
