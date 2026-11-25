"""Campus portal actions and Windows network selection."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import random
import re
import socket
import struct
import subprocess
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection

from desktop_settings import Profile


LOGIN_URL = "http://10.17.8.18:801/eportal/portal/login"
LOGIN_REFERER = "http://10.17.8.18/"
SELF_SERVICE = "http://drcom.jxust.edu.cn:60001/Self"
INTERNET_PROBE = "http://www.gstatic.com/generate_204"
WIFI_SSID = "JXUST-WLAN"
REQUEST_TIMEOUT = 10
SYSTEM32 = Path(os.environ["SystemRoot"]) / "System32"
POWERSHELL = SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NETSH = SYSTEM32 / "netsh.exe"
IP_UNICAST_IF = 31  # Windows IPv4 socket option

ADAPTER_QUERY = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$profiles = @{}
Get-NetConnectionProfile -ErrorAction SilentlyContinue | ForEach-Object {
    $profiles[[int]$_.InterfaceIndex] = [string]$_.Name
}
$metrics = @{}
Get-NetIPInterface -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object {
    $metrics[[int]$_.InterfaceIndex] = [int]$_.InterfaceMetric
}
$addresses = @(Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -Type Unicast -ErrorAction SilentlyContinue |
    Where-Object { -not $_.SkipAsSource -and $_.IPAddress -notlike '169.254.*' })
$adapters = @(foreach ($adapter in (Get-NetAdapter -Physical | Where-Object Status -eq 'Up')) {
    $index = [int]$adapter.ifIndex
    $address = $addresses | Where-Object InterfaceIndex -eq $index | Select-Object -First 1
    [PSCustomObject]@{
        index = $index
        type = [int]$adapter.InterfaceType
        guid = [string]$adapter.InterfaceGuid
        ip = [string]$address.IPAddress
        mac = ([string]$adapter.MacAddress).Replace('-', '')
        network = [string]$profiles[$index]
        metric = $metrics[$index]
    }
})
ConvertTo-Json -InputObject @($adapters | Sort-Object metric, index) -Compress
"""

WLAN_GUID = re.compile(rb"^[ \t]*GUID[ \t]*:[ \t]*\{?([0-9a-f-]{36})\}?", re.I | re.M)
WLAN_SSID = re.compile(rb"^[ \t]*SSID[ \t]*:[ \t]*([^\r\n]+)", re.I | re.M)
CHECK_CODE = re.compile(r"""name=["']checkcode["']\s+value=["']([^"']+)["']""", re.I)


@dataclass(frozen=True, slots=True)
class Adapter:
    index: int
    type: int
    guid: str
    ip: str
    mac: str
    network: str


class NetworkError(Exception):
    pass


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True, timeout=12,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _adapters() -> list[Adapter]:
    try:
        result = _run([str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", ADAPTER_QUERY])
        result.check_returncode()
        return [
            Adapter(item["index"], item["type"], item["guid"].strip("{}").lower(),
                    item["ip"], item["mac"], item["network"])
            for item in json.loads(result.stdout)
        ]
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as error:
        raise NetworkError("无法读取 Windows 网卡信息。") from error


def _campus_wifi(adapters: list[Adapter]) -> list[Adapter]:
    wifi = [adapter for adapter in adapters if adapter.type == 71]
    if not wifi:
        return []
    try:
        output = _run([str(NETSH), "wlan", "show", "interfaces"]).stdout
    except (OSError, subprocess.SubprocessError):
        output = b""

    # Use the actual SSID when available. Some Windows versions hide it
    # without location access, so fall back to Windows' network profile name.
    interfaces = WLAN_GUID.split(output)
    names = {}
    for guid, details in zip(interfaces[1::2], interfaces[2::2]):
        if match := WLAN_SSID.search(details):
            names[guid.decode("ascii").lower()] = match[1].strip()
    return [
        adapter for adapter in wifi
        if names.get(adapter.guid, adapter.network.encode("utf-8")) == WIFI_SSID.encode("ascii")
    ]


def _select_adapter(mode, stop, log) -> Adapter | None:
    adapters = _adapters()
    if stop.is_set():
        return None
    if mode == "ethernet":
        ethernet = next((adapter for adapter in adapters if adapter.type == 6 and adapter.ip), None)
        if ethernet is None:
            log("等待有线网卡获得 IPv4 地址，请检查网线连接。")
        return ethernet

    wifi = _campus_wifi(adapters)
    if stop.is_set():
        return None
    if not wifi:
        log(f"正在连接 {WIFI_SSID}…")
        try:
            result = _run([str(NETSH), "wlan", "connect", f"name={WIFI_SSID}", f"ssid={WIFI_SSID}"])
            result.check_returncode()
        except (OSError, subprocess.SubprocessError):
            log(f"请先在 Windows 的 Wi-Fi 设置中连接一次 {WIFI_SSID}。")
            return None
        if stop.wait(3):
            return None
        wifi = _campus_wifi(_adapters())
    adapter = next((adapter for adapter in wifi if adapter.ip), None)
    if adapter is None:
        log(f"等待 {WIFI_SSID} 连接并获得 IPv4 地址。")
    return adapter


class InterfaceHTTPAdapter(HTTPAdapter):
    def __init__(self, interface: Adapter):
        self.interface = interface
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        # Bind the source IPv4 and route the socket through the selected Windows
        # interface even when both Ethernet and Wi-Fi are connected.
        options = [
            *HTTPConnection.default_socket_options,
            (socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", self.interface.index)),
        ]
        super().init_poolmanager(
            connections, maxsize, block,
            source_address=(self.interface.ip, 0), socket_options=options, **pool_kwargs,
        )


def _session(interface: Adapter | None = None) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    if interface is not None:
        session.mount("http://", InterfaceHTTPAdapter(interface))
    return session


def _internet_available(session: requests.Session) -> bool:
    try:
        with session.get(INTERNET_PROBE, timeout=5, allow_redirects=False, stream=True) as response:
            return response.status_code == 204
    except requests.RequestException:
        return False


def _login(session: requests.Session, interface: Adapter, profile: Profile) -> str:
    params = {
        "callback": "dr1003",
        "login_method": "1",
        "user_account": profile.portal_account,
        "user_password": profile.password,
        "wlan_user_ip": interface.ip,
        "wlan_user_ipv6": "",
        "wlan_user_mac": interface.mac,
        "wlan_ac_ip": "",
        "wlan_ac_name": "",
        "jsVersion": "4.1.3",
        "terminal_type": "1",
        "lang": "zh-cn",
        "v": str(random.randint(1000, 9999)),
    }
    try:
        response = session.get(
            LOGIN_URL, params=params, headers={"Referer": LOGIN_REFERER},
            timeout=REQUEST_TIMEOUT, allow_redirects=False,
        )
    except requests.RequestException:
        # Request exceptions can contain a URL with the password in its query.
        return "无法连接校园网认证服务器，请检查所选网络。"
    if not 200 <= response.status_code < 300:
        return f"校园网认证服务器返回 HTTP {response.status_code}。"
    try:
        body = response.text
        result = json.loads(body[body.index("{"):body.rindex("}") + 1])
        status = result.get("result")
    except (ValueError, AttributeError):
        return "校园网认证服务器返回了无法识别的响应。"
    if str(status).lower() in {"1", "success", "true"}:
        return "校园网认证成功。"
    return "校园网认证未通过，请检查账号、密码和运营商。"


def monitor(profile: Profile, mode: str, interval: int, stop, log) -> None:
    while not stop.is_set():
        adapter = None
        try:
            adapter = _select_adapter(mode, stop, log)
        except NetworkError as error:
            log(str(error))
        if adapter and not stop.is_set():
            with _session(adapter) as session:
                if _internet_available(session):
                    if not stop.is_set():
                        log("网络已连通。")
                elif not stop.is_set():
                    log("网络暂不可用，正在进行校园网认证…")
                    result = _login(session, adapter, profile)
                    if not stop.is_set():
                        log(result)
        stop.wait(interval if adapter else min(interval, 10))


def logout(profile: Profile) -> str:
    """Sign in to self-service and disconnect the account's first online device."""
    with _session() as session:
        session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"})
        dashboard_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{SELF_SERVICE}/dashboard",
        }
        try:
            page = session.get(f"{SELF_SERVICE}/login/", timeout=REQUEST_TIMEOUT)
            page.raise_for_status()
            checkcode = CHECK_CODE.search(page.text)
            if not checkcode:
                return "无法读取注销页面，请确认校园网自服务可访问。"
            session.get(f"{SELF_SERVICE}/login/randomCode", params={"t": random.random()}, timeout=REQUEST_TIMEOUT)
            verification = session.post(
                f"{SELF_SERVICE}/login/verify",
                data={"checkcode": checkcode[1], "account": profile.account, "password": profile.password, "code": ""},
                headers={"Referer": f"{SELF_SERVICE}/login/?302=LI"},
                allow_redirects=False, timeout=REQUEST_TIMEOUT,
            )
            verification.raise_for_status()
            time.sleep(0.5)
            online = session.get(
                f"{SELF_SERVICE}/dashboard/getOnlineList",
                params={"t": random.random(), "_": int(time.time() * 1000)},
                headers=dashboard_headers, timeout=REQUEST_TIMEOUT, allow_redirects=False,
            )
            if online.status_code != 200:
                return "无法读取在线设备，请检查账号和密码。"
            devices = online.json()
            if isinstance(devices, dict):
                devices = devices.get("data", devices.get("rows"))
            if not isinstance(devices, list):
                return "无法读取在线设备，请检查账号和密码。"
            if not devices:
                return "当前账号没有设备在线。"
            session_id = devices[0].get("sessionId")
            if not session_id:
                return "在线记录缺少会话编号，无法注销。"
            time.sleep(0.5)
            offline = session.get(
                f"{SELF_SERVICE}/dashboard/tooffline",
                params={"t": random.random(), "sessionid": session_id},
                headers=dashboard_headers, timeout=REQUEST_TIMEOUT, allow_redirects=False,
            )
            if offline.status_code == 200 and offline.json().get("success") is True:
                return "注销成功，设备已断网。"
            return "校园网自服务未确认注销，请稍后重试。"
        except (requests.RequestException, ValueError, AttributeError):
            return "注销失败，请检查网络和账号密码后重试。"
