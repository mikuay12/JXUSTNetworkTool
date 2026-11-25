package com.jxust.campuswlan;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.widget.Button;
import android.widget.EditText;
import android.widget.AdapterView;
import android.widget.Spinner;
import android.widget.TextView;

import java.security.GeneralSecurityException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int WIFI_PERMISSION_REQUEST = 1001;
    private static final String[] CARRIER_SUFFIXES = {"@telecom", "@cmcc", "@unicom"};

    private EditText accountInput;
    private EditText passwordInput;
    private Spinner carrierInput;
    private Button loginButton;
    private Button logoutButton;
    private Button wifiButton;
    private TextView statusText;
    private CredentialStore credentialStore;
    private WifiConnector wifiConnector;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        accountInput = findViewById(R.id.input_account);
        passwordInput = findViewById(R.id.input_password);
        carrierInput = findViewById(R.id.input_carrier);
        loginButton = findViewById(R.id.button_login);
        logoutButton = findViewById(R.id.button_logout);
        wifiButton = findViewById(R.id.button_wifi);
        statusText = findViewById(R.id.text_status);

        credentialStore = new CredentialStore(this);
        wifiConnector = new WifiConnector(this);
        accountInput.setText(credentialStore.getAccount());
        passwordInput.setText(credentialStore.getPassword());
        carrierInput.setSelection(carrierIndexOf(credentialStore.getCarrierSuffix()));
        carrierInput.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                credentialStore.saveCarrierSuffix(CARRIER_SUFFIXES[position]);
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
                // A carrier is always selected.
            }
        });

        wifiButton.setOnClickListener(view -> requestWifiConnection());
        loginButton.setOnClickListener(view -> runPortalAction(true));
        logoutButton.setOnClickListener(view -> runPortalAction(false));
    }

    private void requestWifiConnection() {
        String permission = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                ? Manifest.permission.NEARBY_WIFI_DEVICES
                : Manifest.permission.ACCESS_FINE_LOCATION;
        if (checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{permission}, WIFI_PERMISSION_REQUEST);
            return;
        }
        connectWifi();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != WIFI_PERMISSION_REQUEST) {
            return;
        }
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            connectWifi();
        } else {
            setStatus("需要附近设备或位置权限才能由应用连接校园 Wi-Fi。", true);
        }
    }

    private void connectWifi() {
        try {
            wifiConnector.connect(message -> runOnUiThread(() -> setStatus(message, false)));
        } catch (SecurityException exception) {
            setStatus("系统拒绝了 Wi-Fi 连接请求，请检查应用权限。", true);
        }
    }

    private void runPortalAction(boolean login) {
        String account = accountInput.getText().toString().trim();
        String password = passwordInput.getText().toString();
        String carrierSuffix = CARRIER_SUFFIXES[carrierInput.getSelectedItemPosition()];
        if (account.isEmpty() || password.isEmpty()) {
            setStatus("请填写账号和密码。", true);
            return;
        }

        try {
            credentialStore.save(account, password, carrierSuffix);
        } catch (GeneralSecurityException exception) {
            setStatus("无法加密保存凭据，请重新打开应用后再试。", true);
            return;
        }

        hideKeyboard();
        setBusy(true);
        setStatus(login ? "正在认证…" : "正在注销本手机…", false);
        executor.submit(() -> {
            String message;
            boolean error = false;
            try {
                CampusNetworkClient client = new CampusNetworkClient(getApplicationContext());
                message = login
                        ? client.login(account, password, carrierSuffix)
                        : client.logout(account, password);
                error = message.contains("失败") || message.contains("认证结果：");
            } catch (Exception exception) {
                error = true;
                message = exception.getMessage();
                if (message == null || message.trim().isEmpty()) {
                    message = exception.getClass().getSimpleName();
                }
            }
            String finalMessage = message;
            boolean finalError = error;
            runOnUiThread(() -> {
                setBusy(false);
                setStatus(finalMessage, finalError);
            });
        });
    }

    private static int carrierIndexOf(String suffix) {
        for (int index = 0; index < CARRIER_SUFFIXES.length; index++) {
            if (CARRIER_SUFFIXES[index].equals(suffix)) {
                return index;
            }
        }
        return 2;
    }

    private void setBusy(boolean busy) {
        loginButton.setEnabled(!busy);
        logoutButton.setEnabled(!busy);
        wifiButton.setEnabled(!busy);
    }

    private void setStatus(String message, boolean error) {
        statusText.setText(message);
        statusText.setTextColor(error ? Color.rgb(179, 38, 30) : Color.rgb(36, 87, 197));
    }

    private void hideKeyboard() {
        View focused = getCurrentFocus();
        if (focused != null) {
            InputMethodManager manager = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
            manager.hideSoftInputFromWindow(focused.getWindowToken(), 0);
        }
    }

    @Override
    protected void onDestroy() {
        wifiConnector.close();
        executor.shutdownNow();
        super.onDestroy();
    }
}
