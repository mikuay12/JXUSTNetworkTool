# 校园网连接工具（Android）

这是 `CampusWLANTool` 的原生 Android 版本，最低支持 Android 9（API 28）。应用只在前台工作，提供连接 `JXUST-WLAN`、认证和注销三个操作。

账号会保存在应用私有存储中；密码使用 Android Keystore 生成的 AES-GCM 密钥加密后保存。卸载应用会清除已保存的凭据。

## 安装

用 Android Studio 生成的调试 APK 通常位于 `app/build/outputs/apk/debug/app-debug.apk`。将它发送到安卓手机，按系统提示允许“安装未知应用”后即可安装。

## 构建

用 Android Studio 打开本目录，等待 Gradle 同步完成，然后运行 `app` 或生成 APK。项目需要 Android SDK 36。

## 行为说明

- Android 9 可直接添加并连接开放 Wi-Fi。
- Android 10 及以上会显示系统提供的 Wi-Fi 连接确认，这是 Android 的安全要求。
- 认证请求不发送 MAC 地址，并强制通过 Wi-Fi 网络访问校园网认证服务器。
- 可选择电信、移动或联通，并记住所选运营商；认证时分别添加 `@telecom`、`@cmcc` 或 `@unicom`。
- 注销严格沿用桌面版流程：登录自服务、读取在线列表，并注销列表中的第一台设备。
- 校园认证服务使用 HTTP，因此应用仅对现有的两个校园网域名开放明文访问。
