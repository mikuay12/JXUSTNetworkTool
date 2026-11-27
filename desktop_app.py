"""The unified Windows application for wired and wireless campus access."""

import ctypes
from dataclasses import replace
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

import campus_network
from desktop_settings import (
    CARRIERS, CONNECTION_MODES, DEFAULT_CARRIER, MAX_INTERVAL,
    Profile, Settings, SettingsStore, base_account, set_startup, single_instance, startup_enabled,
)


TITLE = "校园网连接工具"
VERSION = "1.1.0"
AUTHOR = "mikuay12"
LICENSE_NAME = "PolyForm Noncommercial 1.0.0"
REPO_URL = "https://github.com/mikuay12/JXUSTNetworkTool"
BACKGROUND = "#eef3f8"
CARD = "#ffffff"
INK = "#142640"
MUTED = "#536882"
BLUE = "#1759cf"
FONT = "Microsoft YaHei UI"


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        # PROCESS_SYSTEM_DPI_AWARE = 1
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


class CampusApp:
    def __init__(self, root: tk.Tk, default_mode: str = "wifi", store: SettingsStore | None = None):
        self.root = root
        self.store = store or SettingsStore()
        self.storage_available = True
        try:
            self.settings = self.store.load(default_mode)
        except (OSError, ValueError, TypeError, KeyError):
            self.settings = Settings(mode=default_mode)
            self.storage_available = False

        self.account = tk.StringVar(root)
        self.password = tk.StringVar(root)
        self.interval = tk.StringVar(root, value=str(self.settings.interval))
        self.startup = tk.BooleanVar(root)
        self.status = tk.StringVar(root)
        self.form_account = ""
        self.worker = None
        self.cancel = None
        self.job = ""
        self.running_mode = ""
        self.pending = None
        self.events = queue.SimpleQueue()
        self.about_dialog = None
        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)

        self._create_widgets()
        self._update_account_list()
        self.account.trace_add("write", self._account_changed)
        self.account.set(self.settings.last_account)
        try:
            self.startup.set(startup_enabled())
        except OSError:
            self._log("无法读取 Windows 开机启动设置。")

        if not self.storage_available:
            self._log("无法读取已保存的账号。请先移出本地加密数据文件，再重新打开软件。")
        if profile := self.settings.profiles.get(self.settings.last_account):
            self._launch("monitor", (profile, self.settings.mode, self.settings.interval))
        else:
            self._log("输入校园网账号和密码，选择运营商和连接方式后开始运行。")
            self._update_controls()
        root.after(100, self._poll)

    def _px(self, value: int) -> int:
        return max(1, round(value * self.scale)) if value > 0 else 0

    def _pad(self, *values: int) -> tuple[int, ...]:
        return tuple(self._px(v) for v in values)

    def _create_widgets(self):
        self.root.title(TITLE)
        self.root.configure(background=BACKGROUND)
        self.root.geometry(f"{self._px(598)}x{self._px(550)}")
        self.root.minsize(self._px(520), self._px(510))
        self.root.option_add("*TCombobox*Listbox.font", (FONT, 10))

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=(FONT, 10), background=BACKGROUND, foreground=INK)
        style.configure("Title.TLabel", font=(FONT, 19, "bold"), foreground=INK)
        style.configure("Status.TLabel", font=(FONT, 10, "bold"), foreground=BLUE)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Card.TLabel", background=CARD, foreground=MUTED)
        style.configure("CardValue.TLabel", background=CARD, foreground=INK)
        style.configure("Link.TLabel", background=CARD, foreground=BLUE, font=(FONT, 10, "underline"))
        style.configure("Section.TLabel", background=CARD, font=(FONT, 11, "bold"), foreground=INK)
        style.configure("Card.TCheckbutton", background=CARD, indicatorsize=self._px(14))
        style.map("Card.TCheckbutton", background=[("active", CARD)])
        style.configure("TEntry", padding=self._pad(7, 5), fieldbackground=CARD, bordercolor="#acbed4")
        style.configure(
            "TCombobox", padding=self._pad(7, 5), fieldbackground=CARD,
            bordercolor="#acbed4", arrowsize=self._px(14),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", CARD)],
            selectbackground=[("readonly", CARD)],
            selectforeground=[("readonly", INK)],
        )
        style.configure("TScrollbar", arrowsize=self._px(14))
        style.configure("TButton", padding=self._pad(12, 6), background=CARD, bordercolor="#acbed4")
        style.map("TButton", background=[("pressed", "#dae6f6"), ("active", "#e6effc")])
        style.configure("Primary.TButton", background=BLUE, foreground=CARD, bordercolor=BLUE)
        style.map(
            "Primary.TButton",
            background=[("disabled", "#d8e3f2"), ("pressed", "#114494"), ("active", "#1c66e5")],
            foreground=[("disabled", MUTED), ("!disabled", CARD)],
        )

        body = ttk.Frame(self.root, padding=self._pad(22, 16, 22, 18))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        header = ttk.Frame(body)
        header.grid(row=0, column=0, sticky="ew", pady=(0, self._px(13)))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=TITLE, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.status, style="Status.TLabel").grid(row=0, column=1, sticky="e")

        form = ttk.Frame(body, style="Card.TFrame", padding=self._pad(17, 11, 17, 12))
        form.grid(row=1, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        row_pad = self._px(4)
        label_gap = self._px(12)

        ttk.Label(form, text="账号", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, label_gap), pady=row_pad)
        self.account_box = ttk.Combobox(form, textvariable=self.account)
        self.account_box.grid(row=0, column=1, columnspan=3, sticky="ew", pady=row_pad)
        self.account_box.bind("<<ComboboxSelected>>", self._account_selected)

        ttk.Label(form, text="密码", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=(0, label_gap), pady=row_pad)
        ttk.Entry(form, textvariable=self.password, show="•").grid(
            row=1, column=1, columnspan=3, sticky="ew", pady=row_pad,
        )

        ttk.Label(form, text="运营商", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=(0, label_gap), pady=row_pad)
        self.carrier_box = ttk.Combobox(form, values=tuple(CARRIERS.values()), state="readonly", width=10)
        self.carrier_box.current(tuple(CARRIERS).index(DEFAULT_CARRIER))
        self.carrier_box.grid(row=2, column=1, sticky="ew", pady=row_pad)
        self.carrier_box.bind("<<ComboboxSelected>>", self._carrier_selected)

        ttk.Label(form, text="连接方式", style="Card.TLabel").grid(
            row=2, column=2, sticky="w", padx=(self._px(15), label_gap), pady=row_pad,
        )
        self.mode_box = ttk.Combobox(form, values=tuple(CONNECTION_MODES.values()), state="readonly", width=10)
        self.mode_box.current(tuple(CONNECTION_MODES).index(self.settings.mode))
        self.mode_box.grid(row=2, column=3, sticky="ew", pady=row_pad)
        self.mode_box.bind("<<ComboboxSelected>>", self._mode_selected)

        ttk.Label(form, text="检测间隔", style="Card.TLabel").grid(row=3, column=0, sticky="w", padx=(0, label_gap), pady=row_pad)
        interval_row = ttk.Frame(form, style="Card.TFrame")
        interval_row.grid(row=3, column=1, sticky="w", pady=row_pad)
        ttk.Entry(interval_row, textvariable=self.interval, width=8).pack(side="left")
        ttk.Label(interval_row, text="秒", style="Card.TLabel").pack(side="left", padx=(self._px(7), 0))

        ttk.Checkbutton(
            form, text="开机启动", variable=self.startup, command=self._toggle_startup, style="Card.TCheckbutton",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(self._px(5), 0))
        ttk.Button(form, text="保存账号", command=self._save_account).grid(
            row=4, column=2, columnspan=2, sticky="e", pady=(self._px(5), 0),
        )

        actions = ttk.Frame(body)
        actions.grid(row=2, column=0, sticky="ew", pady=self._px(12))
        self.start_button = ttk.Button(actions, command=self._start, style="Primary.TButton", width=13)
        self.start_button.pack(side="left", padx=(0, self._px(8)))
        self.stop_button = ttk.Button(actions, text="停止运行", command=self._stop)
        self.stop_button.pack(side="left", padx=(0, self._px(8)))
        self.logout_button = ttk.Button(actions, text="立即注销", command=self._logout)
        self.logout_button.pack(side="left")
        ttk.Button(actions, text="关于", command=self._show_about).pack(side="right")

        logs = ttk.Frame(body, style="Card.TFrame", padding=self._pad(14, 9, 12, 10))
        logs.grid(row=3, column=0, sticky="nsew")
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(1, weight=1)
        ttk.Label(logs, text="运行日志", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, self._px(6)))
        scrollbar = ttk.Scrollbar(logs, orient="vertical")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.log_view = tk.Text(
            logs, height=5, width=1, font=(FONT, 10), background=CARD, foreground=MUTED,
            relief="flat", borderwidth=0, highlightthickness=0, wrap="word", spacing1=self._px(3),
            yscrollcommand=scrollbar.set, state="disabled",
        )
        self.log_view.grid(row=1, column=0, sticky="nsew")
        scrollbar.configure(command=self.log_view.yview)
        self.account_box.focus_set()

    def _show_about(self):
        if self.about_dialog is not None and self.about_dialog.winfo_exists():
            self.about_dialog.lift()
            self.about_dialog.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        self.about_dialog = dialog
        dialog.title(f"关于 - {TITLE}")
        dialog.configure(background=BACKGROUND)
        dialog.resizable(False, False)
        dialog.transient(self.root)

        def close(_event=None):
            self.about_dialog = None
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Escape>", close)

        container = ttk.Frame(dialog, padding=self._pad(20, 16, 20, 16))
        container.pack(fill="both", expand=True)

        card = ttk.Frame(container, style="Card.TFrame", padding=self._pad(18, 14, 18, 14))
        card.pack(fill="both", expand=True)
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text=TITLE, style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, self._px(2)),
        )
        ttk.Label(card, text="江西理工大学校园网连接工具", style="Card.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, self._px(12)),
        )

        rows = (
            ("版本号", f"v{VERSION}"),
            ("作者", AUTHOR),
            ("许可协议", LICENSE_NAME),
        )
        for index, (label, value) in enumerate(rows, start=2):
            ttk.Label(card, text=label, style="Card.TLabel").grid(
                row=index, column=0, sticky="w", padx=(0, self._px(16)), pady=self._px(3),
            )
            ttk.Label(card, text=value, style="CardValue.TLabel").grid(
                row=index, column=1, sticky="w", pady=self._px(3),
            )

        ttk.Label(card, text="项目链接", style="Card.TLabel").grid(
            row=5, column=0, sticky="w", padx=(0, self._px(16)), pady=self._px(3),
        )
        link = ttk.Label(card, text=REPO_URL, style="Link.TLabel", cursor="hand2")
        link.grid(row=5, column=1, sticky="w", pady=self._px(3))
        link.bind("<Button-1>", lambda _event: webbrowser.open(REPO_URL))

        footer = ttk.Frame(container)
        footer.pack(fill="x", pady=(self._px(12), 0))
        ttk.Button(footer, text="关闭", command=close).pack(side="right")

        dialog.update_idletasks()
        width = dialog.winfo_reqwidth()
        height = dialog.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        dialog.grab_set()
        dialog.focus_force()

    def _update_account_list(self):
        self.account_box.configure(values=tuple(sorted(self.settings.profiles)))

    def _account_changed(self, *_):
        account = base_account(self.account.get())
        if account == self.form_account:
            return
        self.form_account = account
        profile = self.settings.profiles.get(account)
        self.password.set(profile.password if profile else "")
        self.carrier_box.current(tuple(CARRIERS).index(profile.carrier if profile else DEFAULT_CARRIER))

    def _account_selected(self, _event):
        account = self.form_account
        if account in self.settings.profiles and account != self.settings.last_account:
            self._commit(replace(self.settings, last_account=account))

    def _carrier_selected(self, _event):
        profile = self.settings.profiles.get(self.form_account)
        carrier = tuple(CARRIERS)[self.carrier_box.current()]
        if profile and profile.carrier != carrier:
            self._remember(replace(profile, carrier=carrier))

    def _mode_selected(self, _event):
        self._commit(replace(self.settings, mode=self._mode()))

    def _mode(self):
        return tuple(CONNECTION_MODES)[self.mode_box.current()]

    def _profile(self):
        account = base_account(self.account.get())
        password = self.password.get()
        if not account or not password:
            self._log("请输入账号和密码。")
            return None
        return Profile(account, password, tuple(CARRIERS)[self.carrier_box.current()])

    def _commit(self, settings: Settings) -> bool:
        if not self.storage_available:
            self._log("加密存储不可用，无法保存此次修改。")
            return False
        if settings == self.settings:
            return True
        try:
            self.store.save(settings)
        except OSError:
            self._log("无法保存加密设置，请检查本地用户目录权限。")
            return False
        self.settings = settings
        return True

    def _remember(self, profile: Profile, **preferences) -> bool:
        profiles = {**self.settings.profiles, profile.account: profile}
        if self._commit(replace(self.settings, profiles=profiles, last_account=profile.account, **preferences)):
            self._update_account_list()
            return True
        return False

    def _save_account(self):
        if (profile := self._profile()) and self._remember(profile):
            self.account.set(profile.account)
            self._log("账号已加密保存。")

    def _toggle_startup(self):
        enabled = self.startup.get()
        try:
            set_startup(enabled)
        except OSError:
            self.startup.set(not enabled)
            self._log("无法修改 Windows 开机启动设置。")
            return
        self._log("已启用开机启动，登录 Windows 后自动打开。" if enabled else "已关闭开机启动。")

    def _start(self):
        try:
            interval = int(self.interval.get())
            if not 1 <= interval <= MAX_INTERVAL:
                raise ValueError
        except ValueError:
            self._log("请输入有效的检测间隔，单位为秒。")
            return
        if profile := self._profile():
            mode = self._mode()
            self._remember(profile, mode=mode, interval=interval)
            self.account.set(profile.account)
            self._submit("monitor", (profile, mode, interval))

    def _stop(self):
        if self.job == "monitor":
            self.pending = None
            self.cancel.set()
            self._update_controls()

    def _logout(self):
        if profile := self._profile():
            self._submit("logout", (profile,))

    def _submit(self, kind, arguments):
        if self.worker is None:
            self._launch(kind, arguments)
        elif self.job == "monitor":
            self.pending = (kind, arguments)
            self.cancel.set()
            self._update_controls()

    def _launch(self, kind, arguments):
        self.job = kind
        self.cancel = threading.Event()
        if kind == "monitor":
            _, self.running_mode, interval = arguments
            self._log(f"已启动{CONNECTION_MODES[self.running_mode]}检测，每 {interval} 秒检查一次。")
        else:
            self._log("正在通过校园网自服务注销…")
        self.worker = threading.Thread(
            target=self._run_job, args=(kind, arguments, self.cancel), daemon=True,
        )
        self.worker.start()
        self._update_controls()

    def _run_job(self, kind, arguments, cancel):
        try:
            if kind == "monitor":
                campus_network.monitor(*arguments, cancel, self.events.put)
            else:
                self.events.put(campus_network.logout(*arguments))
        except Exception:
            self.events.put("本次操作未能完成，请检查网络连接后重试。")

    def _poll(self):
        while True:
            try:
                self._log(self.events.get_nowait())
            except queue.Empty:
                break
        if self.worker is not None and not self.worker.is_alive():
            if self.job == "monitor" and self.cancel.is_set():
                self._log("已停止自动检测。")
            self.worker = None
            self.cancel = None
            self.job = ""
            if self.pending:
                kind, arguments = self.pending
                self.pending = None
                self._launch(kind, arguments)
            else:
                self._update_controls()
        self.root.after(100, self._poll)

    def _update_controls(self):
        monitoring = self.job == "monitor"
        logging_out = self.job == "logout" or (self.pending is not None and self.pending[0] == "logout")
        stopping = monitoring and self.cancel.is_set()
        if logging_out:
            self.status.set("正在注销")
        elif self.pending:
            self.status.set("正在应用设置")
        elif stopping:
            self.status.set("正在停止")
        elif monitoring:
            self.status.set(f"{CONNECTION_MODES[self.running_mode]}检测中")
        else:
            self.status.set("待运行")
        self.start_button.configure(
            text="应用并运行" if monitoring else "开始运行", state="disabled" if logging_out else "normal",
        )
        self.stop_button.configure(
            state="normal" if monitoring and not logging_out and (not stopping or self.pending) else "disabled",
        )
        self.logout_button.configure(state="disabled" if logging_out else "normal")

    def _log(self, message):
        self.log_view.configure(state="normal")
        self.log_view.insert("end", time.strftime("[%H:%M:%S] ") + message + "\n")
        lines = int(self.log_view.index("end-1c").split(".")[0])
        if lines > 251:
            self.log_view.delete("1.0", f"{lines - 250}.0")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")


def main(default_mode: str = "wifi"):
    _enable_dpi_awareness()
    with single_instance() as acquired:
        root = tk.Tk()
        if not acquired:
            root.withdraw()
            messagebox.showinfo(TITLE, "校园网连接工具已在运行。", parent=root)
            root.destroy()
            return
        CampusApp(root, default_mode)
        root.mainloop()


if __name__ == "__main__":
    main()
