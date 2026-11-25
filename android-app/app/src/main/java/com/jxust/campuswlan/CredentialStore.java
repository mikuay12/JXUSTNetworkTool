package com.jxust.campuswlan;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.io.IOException;
import java.security.GeneralSecurityException;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class CredentialStore {
    private static final String PREFS = "credentials";
    private static final String ACCOUNT = "account";
    private static final String PASSWORD = "password";
    private static final String CARRIER_SUFFIX = "carrier_suffix";
    private static final String KEY_ALIAS = "campus_wlan_credentials";
    private static final String TRANSFORMATION = "AES/GCM/NoPadding";

    private final SharedPreferences preferences;

    CredentialStore(Context context) {
        preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    String getAccount() {
        return preferences.getString(ACCOUNT, "");
    }

    String getPassword() {
        String saved = preferences.getString(PASSWORD, "");
        if (saved == null || saved.isEmpty()) {
            return "";
        }
        try {
            String[] parts = saved.split(":", 2);
            if (parts.length != 2) {
                return "";
            }
            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            byte[] iv = Base64.decode(parts[0], Base64.NO_WRAP);
            byte[] encrypted = Base64.decode(parts[1], Base64.NO_WRAP);
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), new GCMParameterSpec(128, iv));
            return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
        } catch (GeneralSecurityException | IllegalArgumentException exception) {
            preferences.edit().remove(PASSWORD).apply();
            return "";
        }
    }

    String getCarrierSuffix() {
        return preferences.getString(CARRIER_SUFFIX, "@unicom");
    }

    void saveCarrierSuffix(String suffix) {
        preferences.edit().putString(CARRIER_SUFFIX, suffix).apply();
    }

    void save(String account, String password, String carrierSuffix) throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance(TRANSFORMATION);
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());
        byte[] encrypted = cipher.doFinal(password.getBytes(StandardCharsets.UTF_8));
        String value = Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP)
                + ":"
                + Base64.encodeToString(encrypted, Base64.NO_WRAP);
        preferences.edit()
                .putString(ACCOUNT, account)
                .putString(PASSWORD, value)
                .putString(CARRIER_SUFFIX, carrierSuffix)
                .apply();
    }

    private SecretKey getOrCreateKey() throws GeneralSecurityException {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        try {
            keyStore.load(null);
        } catch (IOException exception) {
            throw new GeneralSecurityException("无法读取 Android Keystore", exception);
        }
        if (keyStore.containsAlias(KEY_ALIAS)) {
            return (SecretKey) keyStore.getKey(KEY_ALIAS, null);
        }

        KeyGenerator keyGenerator = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES,
                "AndroidKeyStore"
        );
        keyGenerator.init(new KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT
        ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build());
        return keyGenerator.generateKey();
    }
}
