"""Windows settings, credential protection, and sign-in startup."""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import winreg


CARRIERS = {
    "@telecom": "电信",
    "@cmcc": "移动",
    "@unicom": "联通",
}
DEFAULT_CARRIER = "@unicom"
CONNECTION_MODES = {"wifi": "无线", "ethernet": "有线"}
MAX_INTERVAL = int(threading.TIMEOUT_MAX)

SETTINGS_PATH = Path(os.environ["LOCALAPPDATA"]) / "CampusWLANTool" / "profiles.dat"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "CampusWLANTool"
CRYPTPROTECT_UI_FORBIDDEN = 1
ERROR_ALREADY_EXISTS = 183


def base_account(account: str) -> str:
    account = account.strip()
    for suffix in CARRIERS:
        if account.lower().endswith(suffix):
            return account[:-len(suffix)].strip()
    return account


@dataclass(frozen=True, slots=True)
class Profile:
    account: str
    password: str = field(repr=False)
    carrier: str = DEFAULT_CARRIER

    @property
    def portal_account(self) -> str:
        return self.account + self.carrier


@dataclass(frozen=True, slots=True)
class Settings:
    profiles: dict[str, Profile] = field(default_factory=dict)
    last_account: str = ""
    mode: str = "wifi"
    interval: int = 600


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_crypt32.CryptProtectData.argtypes = (
    ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
)
_crypt32.CryptUnprotectData.argtypes = (
    ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
)
_crypt32.CryptProtectData.restype = _crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
_kernel32.LocalFree.restype = ctypes.c_void_p
_kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL


def _crypt(data: bytes, *, protect: bool) -> bytes:
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = DataBlob(len(data), buffer)
    result = DataBlob()
    operation = _crypt32.CryptProtectData if protect else _crypt32.CryptUnprotectData
    # Omit CRYPTPROTECT_LOCAL_MACHINE to bind the data to the current Windows user.
    if not operation(
        ctypes.byref(source), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        _kernel32.LocalFree(result.data)


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path

    def load(self, default_mode: str) -> Settings:
        try:
            encrypted = self.path.read_bytes()
        except FileNotFoundError:
            return Settings(mode=default_mode)

        document = json.loads(_crypt(encrypted, protect=False))
        if not isinstance(document, dict) or document.get("version") != 1:
            raise ValueError("Unsupported settings format")

        profiles = {}
        for record in document["profiles"]:
            profile = Profile(**record)
            if not (
                isinstance(profile.account, str) and profile.account
                and isinstance(profile.password, str) and profile.password
                and profile.carrier in CARRIERS
            ):
                raise ValueError("Invalid account profile")
            profiles[profile.account] = profile

        last_account, mode, interval = (document[key] for key in ("last_account", "mode", "interval"))
        if not (
            (last_account == "" or last_account in profiles)
            and mode in CONNECTION_MODES
            and type(interval) is int and 1 <= interval <= MAX_INTERVAL
        ):
            raise ValueError("Invalid saved settings")
        return Settings(profiles, last_account, mode, interval)

    def save(self, settings: Settings) -> None:
        document = {
            "version": 1,
            "profiles": [asdict(profile) for profile in settings.profiles.values()],
            "last_account": settings.last_account,
            "mode": settings.mode,
            "interval": settings.interval,
        }
        encrypted = _crypt(json.dumps(document, ensure_ascii=False).encode("utf-8"), protect=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.path.parent, mode="wb", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                temporary.write(encrypted)
                temporary.close()
                temporary_path.replace(self.path)
            finally:
                temporary.close()
                temporary_path.unlink(missing_ok=True)


def startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return bool(winreg.QueryValueEx(key, RUN_VALUE)[0])
    except FileNotFoundError:
        return False


def set_startup(enabled: bool) -> None:
    if enabled:
        executable = Path(sys.executable).resolve()
        command = [str(executable)]
        if not getattr(sys, "frozen", False):
            pythonw = executable.with_name("pythonw.exe")
            if pythonw.is_file():
                command[0] = str(pythonw)
            command.append(str(Path(__file__).with_name("desktop_app.py").resolve()))
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, subprocess.list2cmdline(command))
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            pass


@contextmanager
def single_instance():
    ctypes.set_last_error(0)
    handle = _kernel32.CreateMutexW(None, False, r"Local\CampusWLANTool")
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    try:
        yield error != ERROR_ALREADY_EXISTS
    finally:
        _kernel32.CloseHandle(handle)
