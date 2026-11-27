# 江西理工大学校园网连接工具

适用于江西理工大学校园网，提供 Windows 和 Android 两个版本。

开启代理可能会影响本软件使用。

## 下载

- 蓝奏云下载：<https://wwamb.lanzoul.com/b01i61kqyd>（密码：`c80v`）

## Windows

支持有线和 `JXUST-WLAN` 无线接入、自动认证、注销、开机启动及多账号切换。每个账号记住自己的运营商，账号和密码由 Windows DPAPI 加密保存。

在 Windows 上安装带 Tkinter 的 Python 3.10 或更新版本，然后在仓库根目录运行：

```powershell
py -m pip install "requests>=2.32.4,<3"
py desktop_app.py
```

如需打包为独立的 `dist/CampusWLAN.exe`：

```powershell
py -m pip install "pyinstaller>=6.16,<7"
py -m PyInstaller CampusWLAN.spec
```

## Android

用 Android Studio 打开 `android-app`。项目需要 Android SDK 36，生成的应用支持 Android 9 及以上版本。安装方法和功能说明见 [安卓版文档](android-app/README.md)。

## 许可

本项目采用 [PolyForm Noncommercial License 1.0.0](LICENSE)。除许可明确允许的情形外，商用须另行取得权利人授权。
