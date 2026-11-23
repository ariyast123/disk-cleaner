"""HeatWatch — game-session temperature guard for Ariya's laptop.

Watches CPU/GPU temperatures while a game runs (via
LibreHardwareMonitor, with nvidia-smi as the GPU fallback),
records every session's peaks and time-over-threshold, warns
live when the CPU cooks, and keeps a running verdict on whether
a repaste is actually due.

The self-update system ships with every lesson from GameMode
VPN baked in: cache-busted update checks that repeat every few
minutes, no modal dialog on the restart path, a guaranteed
process exit, and a narrated update helper with a capped wait.
"""
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

import heatwatch_core as core

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except Exception:  # tray is an enhancement, never a requirement
    pystray = None
    TRAY_AVAILABLE = False

VERSION = "1.2.5"
UPDATE_REPO = "ariyast123/disk-cleaner"
UPDATE_PATH = "heatwatch"
UPDATE_FILES = ("heatwatch_app.py", "heatwatch_core.py", "build.bat",
                "heatwatch_icon.ico")
UPDATE_PY_SOURCES = ("heatwatch_app.py", "heatwatch_core.py")

# Palette: GameMode's dark navy family, heat accents.
BG = "#0A0C16"
SIDEBAR = "#0E1122"
PANEL = "#131731"
PANEL_EDGE = "#232850"
CARD = "#171C3A"
VIOLET = "#7C5CFF"
ORANGE = "#F97316"
CYAN = "#22D3EE"
GREEN = "#34D399"
RED = "#F87171"
AMBER = "#FBBF24"
TEXT = "#E9ECF8"
MUTED = "#8B93B8"
FAINT = "#5B6284"

GAME_COLORS = {
    "Counter-Strike 2": "#E8792E",
    "Rust": "#B3402A",
    "FiveM / GTA V": "#8B5CF6",
    "Overwatch": "#F06414",
    "Deadlock": "#94A3B8",
}
CUSTOM_COLORS = ["#22D3EE", "#34D399", "#F472B6", "#FBBF24", "#60A5FA"]


def project_folder():
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.basename(exe_dir).lower() == "dist":
            return os.path.dirname(exe_dir)
        return exe_dir
    return os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Update plumbing (pure helpers are module-level so tests can drive them)
# ---------------------------------------------------------------------------

def parse_version(text):
    parts = []
    for chunk in str(text).strip().lstrip("v").split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def validate_update_files(files):
    if not isinstance(files, dict):
        return False
    for name in UPDATE_FILES:
        data = files.get(name)
        if not data:
            return False
    for name in UPDATE_PY_SOURCES:
        try:
            compile(files[name].decode("utf-8"), name, "exec")
        except Exception:
            return False
    return True


def _whats_new_file():
    return os.path.join(core.data_dir(), "whats_new.json")


def save_whats_new(info):
    import json
    notes = info.get("patch_notes") or info.get("notes") or ""
    if isinstance(notes, list):
        notes = "\n".join(str(line) for line in notes)
    payload = {"version": str(info.get("version", "")), "notes": str(notes)}
    tmp = _whats_new_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, _whats_new_file())


def pop_whats_new(version):
    """Return the saved patch notes for exactly this version, once."""
    import json
    path = _whats_new_file()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    try:
        os.remove(path)
    except OSError:
        pass
    if isinstance(payload, dict) and payload.get("version") == version:
        return str(payload.get("notes") or "")
    return None


def _raw_url(path, cache_bust=False):
    """raw.githubusercontent URL for a repo file. The cache_bust
    query defeats GitHub's per-region raw cache, which lags
    minutes behind a publish (learned the hard way on GameMode)."""
    url = f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/{path}"
    if cache_bust:
        url += f"?t={int(time.time())}"
    return url


def fetch_update_info(timeout=10):
    """Return the repo's heatwatch version.json dict, or None."""
    import json
    import urllib.request

    url = _raw_url(f"{UPDATE_PATH}/version.json", cache_bust=True)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict) and data.get("version"):
            return data
    except Exception:
        pass
    return None


def download_update_files(timeout=30):
    """Download the update files; return {name: bytes} or None."""
    import urllib.request

    files = {}
    try:
        for name in UPDATE_FILES:
            url = _raw_url(f"{UPDATE_PATH}/{name}", cache_bust=True)
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                files[name] = resp.read()
    except Exception:
        return None
    return files if validate_update_files(files) else None


def apply_update_files(project_dir, files):
    for name, data in files.items():
        tmp = os.path.join(project_dir, name + ".new")
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, os.path.join(project_dir, name))


def update_helper_lines(project, launched_exe):
    """finish_update.bat, kill-first design (Ariya's request,
    Nov 22, 2026): the helper does NOT wait politely for the app
    to close. Its first move is taskkill — every running copy of
    HeatWatch.exe dies at once (the app that requested the update has
    already exited itself; any other copy is a stale duplicate).
    A short capped loop then verifies they are gone; a copy that
    somehow survives is logged and the build proceeds anyway.
    Then: rebuild with build.bat auto, copy the fresh exe back
    over the launched one (so pinned shortcuts update in place)
    and relaunch. Every phase is echoed to the console AND
    update_build.log."""
    built = os.path.join(project, "dist", "HeatWatch.exe")
    lines = [
        "@echo off",
        "title HeatWatch update",
        f'cd /d "{project}"',
        "echo [helper] update started > update_build.log",
        "echo HeatWatch update: closing any running copies...",
        "taskkill /F /IM HeatWatch.exe >> update_build.log 2>&1",
        "set /a WAITS=0",
        ":waitloop",
        'tasklist /FI "IMAGENAME eq HeatWatch.exe" 2>NUL | '
        'find /I "HeatWatch.exe" >NUL',
        "if errorlevel 1 goto allclosed",
        "set /a WAITS+=1",
        "if %WAITS% GEQ 10 goto proceed",
        "timeout /t 1 /nobreak >NUL",
        "goto waitloop",
        ":proceed",
        "echo [helper] a copy is still running - continuing anyway >> update_build.log",
        ":allclosed",
        "echo [helper] building >> update_build.log",
        "echo HeatWatch update: building (1-2 minutes, details in update_build.log)...",
        "call build.bat auto >> update_build.log 2>&1",
        f'set "BUILT={built}"',
        f'set "LAUNCHED={launched_exe}"',
        'if exist "%BUILT%" (',
        '  if /I not "%BUILT%"=="%LAUNCHED%" copy /Y "%BUILT%" "%LAUNCHED%" >> update_build.log 2>&1',
        '  echo [helper] starting updated app >> update_build.log',
        '  start "" "%LAUNCHED%"',
        ") else (",
        '  echo [helper] build produced no exe - relaunching previous version >> update_build.log',
        '  if exist "%LAUNCHED%" start "" "%LAUNCHED%"',
        ")",
    ]
    return lines


def _startup_command(frozen, executable, script_path):
    """The command the Run key stores. --minimized makes boot
    launches start hidden in the tray."""
    if frozen:
        return f'"{executable}" --minimized'
    return f'"{executable}" "{script_path}" --minimized'


def _wants_minimized(argv):
    return any(arg in ("--minimized", "/minimized") for arg in argv[1:])


def fmt_temp(value):
    if value is None:
        return "—"
    return f"{value:.0f}°C"


def gauge_fraction(value, top=110.0):
    """How full a temperature gauge bar is (0..1)."""
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value) / float(top)))


def fmt_duration(seconds):
    seconds = int(seconds or 0)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours} h {minutes:02d} m"
    if minutes:
        return f"{minutes} m {secs:02d} s"
    return f"{secs} s"


def temp_color(value, warn):
    if value is None:
        return FAINT
    if value >= warn:
        return RED
    if value >= warn - 15:
        return AMBER
    return GREEN


VERDICT_TEXT = {
    "unknown": ("No full sessions yet", FAINT,
                "Play a full game session (10+ minutes) and the "
                "verdict will judge your cooling from real data."),
    "healthy": ("Cooling looks healthy", GREEN,
                "Recent session peaks stay under the warning line. "
                "No repaste needed yet."),
    "hot": ("Running hot — watch it", AMBER,
            "Recent sessions regularly cross the warning line. "
            "Dust and old paste are the usual suspects."),
    "repaste": ("Repaste is due", RED,
                "Recent sessions sit at the throttle zone. "
                "Fresh thermal paste + a fan cleaning should "
                "bring peaks down."),
}


class HeatWatchApp(ctk.CTk):
    def __init__(self, start_minimized=False):
        super().__init__()
        self.settings = core.load_settings()
        self.tracker = core.SessionTracker(
            warn_cpu=self.settings["warn_cpu_c"],
            warn_gpu=self.settings["warn_gpu_c"],
            debounce_seconds=self.settings["gone_debounce_seconds"])
        self.warner = core.HeatWarner(self.settings["warn_cpu_c"])
        self.history = core.load_history()
        self.latest = {"cpu": None, "gpu": None, "source": "none"}
        self.buffer = core.SampleBuffer(capacity=120)
        self._orb_phase = False
        self.update_info = None
        self._update_pending = False
        self._hidden_in_tray = False
        self._tray_icon = None
        self._tray_notified = False
        self._stop = threading.Event()
        self.msg_queue = queue.Queue()
        self._log_lines = []

        self.title("HeatWatch")
        self.geometry("1140x760")
        self.minsize(1000, 660)
        self.configure(fg_color=BG)
        icon = os.path.join(project_folder(), "heatwatch_icon.ico")
        if os.path.isfile(icon):
            try:
                self.iconbitmap(icon)
            except Exception:
                pass
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self._build_ui()
        self._refresh_history()
        self._log("HeatWatch started — watching temperatures")

        threading.Thread(target=self._sample_loop, daemon=True).start()
        threading.Thread(target=self._check_update_worker,
                         daemon=True).start()
        self.after(150, self._drain_queue)
        self.after(700, self._pulse_orb)
        if not start_minimized:
            self._maybe_show_whats_new()

        if core.is_windows() and self.settings["start_with_windows"]:
            self._apply_startup_entry(True)  # self-heal the entry
        if start_minimized:
            self.after(300, self._start_in_tray)

    # -- UI construction ----------------------------------------------------

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        sidebar = ctk.CTkFrame(self, width=300, fg_color=SIDEBAR,
                               corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        title = ctk.CTkLabel(sidebar, text="HEATWATCH",
                             font=ctk.CTkFont(size=24, weight="bold"),
                             text_color=TEXT)
        title.pack(anchor="w", padx=20, pady=(18, 0))
        sub = ctk.CTkLabel(sidebar, text="Game-session temperature guard",
                           font=ctk.CTkFont(size=12), text_color=MUTED)
        sub.pack(anchor="w", padx=20, pady=(0, 12))

        self.source_label = ctk.CTkLabel(
            sidebar, text="Temperature source: looking…",
            font=ctk.CTkFont(size=12), text_color=MUTED,
            wraplength=260, justify="left", anchor="w")
        self.source_label.pack(anchor="w", padx=20, pady=(0, 6))

        self.orb = tk.Canvas(sidebar, width=76, height=76,
                             bg=SIDEBAR, highlightthickness=0)
        self.orb.pack(anchor="w", padx=20, pady=(0, 8))
        self._draw_orb()

        cpu_card = ctk.CTkFrame(sidebar, fg_color=CARD, corner_radius=12)
        cpu_card.pack(fill="x", padx=16, pady=(4, 8))
        ctk.CTkLabel(cpu_card, text="CPU", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", padx=14,
                                            pady=(10, 0))
        self.cpu_value = ctk.CTkLabel(
            cpu_card, text="—", font=ctk.CTkFont(size=40, weight="bold"),
            text_color=FAINT)
        self.cpu_value.pack(anchor="w", padx=14, pady=(0, 2))
        self.cpu_gauge = ctk.CTkProgressBar(
            cpu_card, height=8, corner_radius=4, fg_color=PANEL,
            progress_color=GREEN)
        self.cpu_gauge.set(0)
        self.cpu_gauge.pack(fill="x", padx=14, pady=(2, 2))
        self.cpu_warn_label = ctk.CTkLabel(
            cpu_card, text="", font=ctk.CTkFont(size=11),
            text_color=FAINT)
        self.cpu_warn_label.pack(anchor="w", padx=14, pady=(0, 10))

        gpu_card = ctk.CTkFrame(sidebar, fg_color=CARD, corner_radius=12)
        gpu_card.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(gpu_card, text="GPU", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", padx=14,
                                            pady=(10, 0))
        self.gpu_value = ctk.CTkLabel(
            gpu_card, text="—", font=ctk.CTkFont(size=40, weight="bold"),
            text_color=FAINT)
        self.gpu_value.pack(anchor="w", padx=14, pady=(0, 2))
        self.gpu_gauge = ctk.CTkProgressBar(
            gpu_card, height=8, corner_radius=4, fg_color=PANEL,
            progress_color=GREEN)
        self.gpu_gauge.set(0)
        self.gpu_gauge.pack(fill="x", padx=14, pady=(2, 10))

        self.verdict_card = ctk.CTkFrame(sidebar, fg_color=CARD,
                                         border_color=PANEL_EDGE,
                                         border_width=1,
                                         corner_radius=12)
        verdict_card = self.verdict_card
        verdict_card.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(verdict_card, text="REPASTE VERDICT",
                     font=ctk.CTkFont(size=11), text_color=MUTED).pack(
                         anchor="w", padx=14, pady=(10, 0))
        self.verdict_title = ctk.CTkLabel(
            verdict_card, text="—", font=ctk.CTkFont(size=15,
                                                     weight="bold"),
            text_color=TEXT)
        self.verdict_title.pack(anchor="w", padx=14, pady=(2, 0))
        self.verdict_detail = ctk.CTkLabel(
            verdict_card, text="", font=ctk.CTkFont(size=11),
            text_color=MUTED, wraplength=250, justify="left",
            anchor="w")
        self.verdict_detail.pack(anchor="w", padx=14, pady=(0, 10))

        self.lhm_button = ctk.CTkButton(
            sidebar, text="Open LibreHardwareMonitor",
            fg_color=VIOLET, hover_color="#6A4DF0", text_color="white",
            command=self._open_lhm)
        self.lhm_button.pack(fill="x", padx=16, pady=(8, 4))

        self.banner_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        self.banner_frame.pack(fill="x", padx=16, pady=(6, 0))

        ctk.CTkLabel(sidebar, text=f"v{VERSION}  •  data in ~/HeatWatch",
                     font=ctk.CTkFont(size=11),
                     text_color=FAINT).pack(side="bottom", anchor="w",
                                            padx=20, pady=12)

        main = ctk.CTkScrollableFrame(self, fg_color=BG,
                                      corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)

        accent = ctk.CTkFrame(main, height=4, fg_color=ORANGE,
                              corner_radius=0)
        accent.grid(row=0, column=0, sticky="ew", padx=0, pady=0)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=18,
                    pady=(14, 10))
        ctk.CTkLabel(header, text="Overview",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=TEXT).pack(side="left")
        self.state_label = ctk.CTkLabel(
            header, text="WAITING FOR SENSORS",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=FAINT)
        self.state_label.pack(side="right")

        self.session_card = ctk.CTkFrame(main, fg_color=PANEL,
                                         border_color=PANEL_EDGE,
                                         border_width=1, corner_radius=14)
        self.session_card.grid(row=2, column=0, sticky="ew",
                               padx=18, pady=(0, 10))
        ctk.CTkLabel(self.session_card, text="CURRENT SESSION",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=16,
                                            pady=(12, 2))
        self.session_title = ctk.CTkLabel(
            self.session_card, text="No game running",
            font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT)
        self.session_title.pack(anchor="w", padx=16)
        self.session_detail = ctk.CTkLabel(
            self.session_card, text="Temperatures are still being "
                                    "watched — a session starts when "
                                    "a watched game opens.",
            font=ctk.CTkFont(size=12), text_color=MUTED,
            wraplength=640, justify="left", anchor="w")
        self.session_detail.pack(anchor="w", padx=16, pady=(2, 6))
        chips = ctk.CTkFrame(self.session_card, fg_color="transparent")
        chips.pack(anchor="w", padx=16, pady=(0, 12))
        self.chip_peak_cpu = ctk.CTkLabel(
            chips, text="PEAK CPU —", font=ctk.CTkFont(size=11,
                                                      weight="bold"),
            text_color=MUTED, fg_color=CARD, corner_radius=8)
        self.chip_peak_cpu.pack(side="left", padx=(0, 8), ipadx=8,
                                ipady=3)
        self.chip_peak_gpu = ctk.CTkLabel(
            chips, text="PEAK GPU —", font=ctk.CTkFont(size=11,
                                                      weight="bold"),
            text_color=MUTED, fg_color=CARD, corner_radius=8)
        self.chip_peak_gpu.pack(side="left", padx=(0, 8), ipadx=8,
                                ipady=3)
        self.chip_over = ctk.CTkLabel(
            chips, text="OVER LINE —", font=ctk.CTkFont(size=11,
                                                       weight="bold"),
            text_color=MUTED, fg_color=CARD, corner_radius=8)
        self.chip_over.pack(side="left", ipadx=8, ipady=3)

        graph_card = ctk.CTkFrame(main, fg_color=PANEL,
                                  border_color=PANEL_EDGE,
                                  border_width=1, corner_radius=14)
        graph_card.grid(row=3, column=0, sticky="ew", padx=18,
                        pady=(0, 10))
        ctk.CTkLabel(graph_card, text="LAST MINUTES — CPU (orange) "
                                      "• GPU (cyan) • dashed = CPU "
                                      "warning line",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=16,
                                            pady=(12, 4))
        self.spark = tk.Canvas(graph_card, height=96, bg="#0D1020",
                               highlightthickness=0)
        self.spark.pack(fill="x", padx=16, pady=(0, 12))

        history_card = ctk.CTkFrame(main, fg_color=PANEL,
                                    border_color=PANEL_EDGE,
                                    border_width=1, corner_radius=14)
        history_card.grid(row=4, column=0, sticky="ew", padx=18,
                          pady=(0, 10))
        ctk.CTkLabel(history_card, text="SESSION HISTORY",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=16,
                                            pady=(12, 4))
        self.history_frame = ctk.CTkFrame(history_card,
                                          fg_color="transparent")
        self.history_frame.pack(fill="x", padx=8, pady=(0, 10))

        games_card = ctk.CTkFrame(main, fg_color=PANEL,
                                  border_color=PANEL_EDGE,
                                  border_width=1, corner_radius=14)
        games_card.grid(row=5, column=0, sticky="ew", padx=18,
                        pady=(0, 10))
        ctk.CTkLabel(games_card, text="WATCHED GAMES",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=16,
                                            pady=(12, 4))
        self.games_frame = ctk.CTkFrame(games_card,
                                        fg_color="transparent")
        self.games_frame.pack(fill="x", padx=8, pady=(0, 10))
        self._render_games()

        settings_card = ctk.CTkFrame(main, fg_color=PANEL,
                                     border_color=PANEL_EDGE,
                                     border_width=1, corner_radius=14)
        settings_card.grid(row=6, column=0, sticky="ew", padx=18,
                           pady=(0, 10))
        ctk.CTkLabel(settings_card, text="SETTINGS",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=16,
                                            pady=(12, 6))
        form = ctk.CTkFrame(settings_card, fg_color="transparent")
        form.pack(fill="x", padx=16)
        self.warn_cpu_entry = self._setting_row(
            form, 0, "CPU warning at (°C)", self.settings["warn_cpu_c"])
        self.warn_gpu_entry = self._setting_row(
            form, 1, "GPU warning at (°C)", self.settings["warn_gpu_c"])
        self.poll_entry = self._setting_row(
            form, 2, "Check every (seconds)", self.settings["poll_seconds"])
        self.port_entry = self._setting_row(
            form, 3, "LibreHardwareMonitor port",
            self.settings["lhm_port"])
        ctk.CTkButton(settings_card, text="Save settings",
                      fg_color=CARD, hover_color="#1D2347",
                      text_color=TEXT,
                      command=self._save_settings_form).pack(
                          anchor="w", padx=16, pady=(8, 4))
        self.tray_switch = self._switch_row(
            settings_card, "Minimize to tray when closed",
            self.settings["minimize_to_tray"], self._toggle_tray)
        self.startup_switch = self._switch_row(
            settings_card, "Start with Windows (hidden in tray)",
            self.settings["start_with_windows"], self._toggle_startup)
        ctk.CTkLabel(
            settings_card,
            text="Needs LibreHardwareMonitor running as "
                 "administrator (free, open source). Fastest feed: "
                 "in LHM tick Options > Remote Web Server. Without "
                 "LHM, only the GPU is visible, via nvidia-smi.",
            font=ctk.CTkFont(size=11), text_color=FAINT,
            wraplength=640, justify="left", anchor="w").pack(
                anchor="w", padx=16, pady=(4, 12))

        log_card = ctk.CTkFrame(main, fg_color=PANEL,
                                border_color=PANEL_EDGE,
                                border_width=1, corner_radius=14)
        log_card.grid(row=7, column=0, sticky="ew", padx=18,
                      pady=(0, 16))
        ctk.CTkLabel(log_card, text="ACTIVITY",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=16,
                                            pady=(12, 4))
        self.log_label = ctk.CTkLabel(
            log_card, text="", font=ctk.CTkFont(size=11),
            text_color=MUTED, wraplength=660, justify="left",
            anchor="w")
        self.log_label.pack(anchor="w", padx=16, pady=(0, 12))

    def _setting_row(self, parent, row, label, value):
        ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=12),
                     text_color=TEXT).grid(row=row, column=0,
                                            sticky="w", pady=3)
        entry = ctk.CTkEntry(parent, width=90, fg_color=CARD,
                             border_color=PANEL_EDGE, text_color=TEXT)
        entry.insert(0, str(value))
        entry.grid(row=row, column=1, sticky="w", padx=(12, 0), pady=3)
        return entry

    def _switch_row(self, parent, label, value, command):
        switch = ctk.CTkSwitch(parent, text=label,
                               font=ctk.CTkFont(size=12),
                               text_color=TEXT, progress_color=VIOLET,
                               command=command)
        if value:
            switch.select()
        else:
            switch.deselect()
        switch.pack(anchor="w", padx=16, pady=3)
        return switch

    def _render_games(self):
        for child in self.games_frame.winfo_children():
            child.destroy()
        self.game_dots = {}
        for idx, game in enumerate(self.settings["games"]):
            row = ctk.CTkFrame(self.games_frame, fg_color=CARD,
                               corner_radius=10)
            row.pack(fill="x", padx=4, pady=3)
            color = GAME_COLORS.get(
                game["name"],
                CUSTOM_COLORS[idx % len(CUSTOM_COLORS)])
            tile = ctk.CTkLabel(row, text=game["name"][:2].upper(),
                                width=34, height=34, fg_color=color,
                                corner_radius=8, text_color="white",
                                font=ctk.CTkFont(size=12, weight="bold"))
            tile.pack(side="left", padx=(8, 10), pady=6)
            dot = ctk.CTkLabel(row, text="●",
                               font=ctk.CTkFont(size=12),
                               text_color=FAINT)
            dot.pack(side="left", padx=(0, 6))
            self.game_dots[game["name"]] = dot
            ctk.CTkLabel(row, text=game["name"],
                         font=ctk.CTkFont(size=13), text_color=TEXT
                         ).pack(side="left")
            ctk.CTkLabel(row, text=", ".join(game["patterns"]),
                         font=ctk.CTkFont(size=11), text_color=FAINT
                         ).pack(side="left", padx=(10, 0))
            switch = ctk.CTkSwitch(
                row, text="", width=44, progress_color=VIOLET,
                command=lambda g=game["name"]: self._toggle_game(g))
            if game["enabled"]:
                switch.select()
            switch.pack(side="right", padx=10)

    # -- Sampling -------------------------------------------------------------

    def _sample_loop(self):
        while not self._stop.is_set():
            try:
                temps = core.collect_temps(self.settings["lhm_port"])
                running = core.running_process_names()
                games = core.match_games(running, self.settings["games"])
                now = time.time()
                events = self.tracker.update(
                    now, games, temps["cpu"], temps["gpu"],
                    temps["source"])
                warned = self.warner.update(now, temps["cpu"])
                self.msg_queue.put(("sample", {
                    "temps": temps, "games": games, "events": events,
                    "warned": warned, "now": now}))
            except Exception as exc:  # the watcher must never die
                core.log_line(f"sample loop error: {exc}")
            self._stop.wait(self.settings["poll_seconds"])

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "sample":
                    self._apply_sample(payload)
                elif kind == "update_available":
                    self._show_update_banner(payload)
                elif kind == "update_downloaded":
                    self._update_downloaded(payload)
        except queue.Empty:
            pass
        if not self._stop.is_set():
            self.after(150, self._drain_queue)

    def _apply_sample(self, payload):
        temps = payload["temps"]
        self.latest = temps
        warn_cpu = self.settings["warn_cpu_c"]
        warn_gpu = self.settings["warn_gpu_c"]
        self.cpu_value.configure(
            text=fmt_temp(temps["cpu"]),
            text_color=temp_color(temps["cpu"], warn_cpu))
        self.gpu_value.configure(
            text=fmt_temp(temps["gpu"]),
            text_color=temp_color(temps["gpu"], warn_gpu))
        self.cpu_gauge.configure(
            progress_color=temp_color(temps["cpu"], warn_cpu))
        self.cpu_gauge.set(gauge_fraction(temps["cpu"]))
        self.gpu_gauge.configure(
            progress_color=temp_color(temps["gpu"], warn_gpu))
        self.gpu_gauge.set(gauge_fraction(temps["gpu"]))
        self.buffer.push(payload["now"], temps["cpu"], temps["gpu"])
        self._draw_sparkline()
        self._draw_orb()
        running = set(payload["games"])
        for name, dot in getattr(self, "game_dots", {}).items():
            dot.configure(
                text_color=GREEN if name in running else FAINT)
        self.cpu_warn_label.configure(
            text=f"warning at {warn_cpu}°C")
        source = temps["source"]
        if source == "none":
            self.source_label.configure(
                text="Temperature source: none found — open "
                     "LibreHardwareMonitor (as administrator) for "
                     "CPU + GPU, or the GPU alone needs nvidia-smi.",
                text_color=AMBER)
        else:
            self.source_label.configure(
                text=f"Temperature source: {source}",
                text_color=MUTED)
        for kind, data in payload["events"]:
            if kind == "started":
                self.warner.reset()
                self._log(f"Session started: {data}")
            elif kind == "ended":
                self.history = core.append_history(data)
                self._log(
                    f"Session ended: {data['game']} — "
                    f"{fmt_duration(data['duration_s'])}, peak CPU "
                    f"{fmt_temp(data['peak_cpu'])}, peak GPU "
                    f"{fmt_temp(data['peak_gpu'])}")
                self._refresh_history()
        if payload["warned"]:
            cpu = temps["cpu"]
            self._log(f"Heat warning: CPU at {fmt_temp(cpu)} for a "
                      f"sustained stretch (line: {warn_cpu}°C)")
            self._notify_tray(
                f"CPU is at {fmt_temp(cpu)} — over the "
                f"{warn_cpu}°C line. Check airflow / fans.",
                "HeatWatch warning")
        current = self.tracker.current()
        if current is None:
            self.session_card.configure(border_color=PANEL_EDGE)
            self.session_title.configure(text="No game running")
            self.session_detail.configure(
                text="Temperatures are still being watched — a "
                     "session starts when a watched game opens.")
            self.chip_peak_cpu.configure(text="PEAK CPU —",
                                         text_color=MUTED)
            self.chip_peak_gpu.configure(text="PEAK GPU —",
                                         text_color=MUTED)
            self.chip_over.configure(text="OVER LINE —",
                                     text_color=MUTED)
            if temps["source"] == "none":
                self.state_label.configure(
                    text="WAITING FOR SENSORS", text_color=FAINT)
            elif (temps["cpu"] is not None
                    and temps["cpu"] >= warn_cpu):
                self.state_label.configure(text="RUNNING HOT",
                                           text_color=RED)
            else:
                self.state_label.configure(text="IDLE — WATCHING",
                                           text_color=MUTED)
        else:
            hot = (temps["cpu"] is not None
                   and temps["cpu"] >= warn_cpu)
            self.session_card.configure(
                border_color=RED if hot else VIOLET)
            elapsed = payload["now"] - current["start"]
            self.session_title.configure(
                text=f"{current['game']} — {fmt_duration(elapsed)}")
            self.session_detail.configure(
                text=f"Peak CPU {fmt_temp(current['peak_cpu'])}  •  "
                     f"Peak GPU {fmt_temp(current['peak_gpu'])}  •  "
                     f"Over the line: CPU "
                     f"{fmt_duration(current['sec_above_cpu'])}, GPU "
                     f"{fmt_duration(current['sec_above_gpu'])}")
            self.chip_peak_cpu.configure(
                text=f"PEAK CPU {fmt_temp(current['peak_cpu'])}",
                text_color=temp_color(current["peak_cpu"], warn_cpu))
            self.chip_peak_gpu.configure(
                text=f"PEAK GPU {fmt_temp(current['peak_gpu'])}",
                text_color=temp_color(current["peak_gpu"], warn_gpu))
            self.chip_over.configure(
                text="OVER LINE "
                     f"{fmt_duration(current['sec_above_cpu'])}",
                text_color=RED if current["sec_above_cpu"] > 0
                else MUTED)
            self.state_label.configure(
                text=f"IN SESSION — {current['game']}",
                text_color=RED if hot else CYAN)

    # -- Live visuals -----------------------------------------------------------

    def _orb_state(self):
        """(ring, core) colors for the status orb."""
        cpu = self.latest.get("cpu")
        warn = self.settings["warn_cpu_c"]
        if cpu is None:
            return FAINT, PANEL
        if cpu >= warn:
            return RED, RED if self._orb_phase else "#7F1D1D"
        if self.tracker.current() is not None:
            return CYAN, ORANGE
        if cpu >= warn - 15:
            return AMBER, PANEL
        return GREEN, PANEL

    def _draw_orb(self):
        if not hasattr(self, "orb"):
            return
        ring, core_fill = self._orb_state()
        self.orb.delete("all")
        self.orb.create_oval(6, 6, 70, 70, outline=ring, width=4)
        self.orb.create_oval(26, 26, 50, 50, fill=core_fill,
                             outline="")

    def _pulse_orb(self):
        self._orb_phase = not self._orb_phase
        cpu = self.latest.get("cpu")
        if cpu is not None and cpu >= self.settings["warn_cpu_c"]:
            self._draw_orb()
        if not self._stop.is_set():
            self.after(700, self._pulse_orb)

    def _draw_sparkline(self):
        if not hasattr(self, "spark"):
            return
        canvas = self.spark
        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        height = 96
        vmin, vmax = 30.0, 110.0
        warn = self.settings["warn_cpu_c"]
        warn_y = height - (warn - vmin) / (vmax - vmin) * height
        canvas.create_line(0, warn_y, width, warn_y, fill=RED,
                           dash=(4, 4))
        for series, color in ((self.buffer.gpu_series(), CYAN),
                              (self.buffer.cpu_series(), ORANGE)):
            points = core.scale_series(series, width - 8, height - 12,
                                       vmin, vmax)
            if len(points) >= 2:
                flat = []
                for x, y in points:
                    flat.extend((x + 4, y + 6))
                canvas.create_line(*flat, fill=color, width=2,
                                   smooth=True)
        if len(self.buffer) < 2:
            canvas.create_text(
                width / 2, height / 2,
                text="Collecting temperatures…",
                fill=FAINT, font=("Segoe UI", 10))
        cpu_now = self.latest.get("cpu")
        gpu_now = self.latest.get("gpu")
        if cpu_now is not None:
            canvas.create_text(width - 6, 10, anchor="e",
                               text=f"CPU {cpu_now:.0f}°",
                               fill=ORANGE, font=("Segoe UI", 9,
                                                  "bold"))
        if gpu_now is not None:
            canvas.create_text(width - 6, 24, anchor="e",
                               text=f"GPU {gpu_now:.0f}°",
                               fill=CYAN, font=("Segoe UI", 9,
                                                "bold"))

    def _refresh_history(self):
        for child in self.history_frame.winfo_children():
            child.destroy()
        recent = list(reversed(self.history[-8:]))
        if not recent:
            ctk.CTkLabel(self.history_frame, text="No sessions yet.",
                         font=ctk.CTkFont(size=12),
                         text_color=FAINT).pack(anchor="w", padx=8,
                                                pady=4)
        for record in recent:
            row = ctk.CTkFrame(self.history_frame,
                               fg_color="transparent")
            row.pack(fill="x", padx=4, pady=1)
            when = time.strftime(
                "%b %d %H:%M", time.localtime(record.get("start", 0)))
            text = (f"{when}  •  {record.get('game', '?')}  •  "
                    f"{fmt_duration(record.get('duration_s'))}  •  "
                    f"peak CPU {fmt_temp(record.get('peak_cpu'))}  •  "
                    f"peak GPU {fmt_temp(record.get('peak_gpu'))}  •  "
                    f"over line "
                    f"{fmt_duration(record.get('sec_above_cpu'))}")
            dot_color = temp_color(record.get("peak_cpu"),
                                   record.get("warn_cpu") or 95)
            ctk.CTkLabel(row, text="●",
                         font=ctk.CTkFont(size=12),
                         text_color=dot_color).pack(side="left",
                                                    padx=(4, 0))
            ctk.CTkLabel(row, text=text,
                         font=ctk.CTkFont(size=12),
                         text_color=TEXT).pack(side="left", padx=4)
            if record.get("series"):
                ctk.CTkButton(
                    row, text="Graph", width=64, height=24,
                    fg_color=CARD, hover_color="#1D2347",
                    text_color=TEXT,
                    command=lambda r=record: self._show_session_graph(r)
                    ).pack(side="right", padx=4)
        result = core.verdict(self.history)
        title, color, detail = VERDICT_TEXT[result["level"]]
        self.verdict_title.configure(text=title, text_color=color)
        self.verdict_card.configure(
            border_color=PANEL_EDGE if result["level"] == "unknown"
            else color)
        extra = ""
        if result["median_peak_cpu"] is not None:
            extra = (f" Median peak CPU over the last "
                     f"{result['sessions_used']} full sessions: "
                     f"{fmt_temp(result['median_peak_cpu'])}.")
        self.verdict_detail.configure(text=detail + extra)

    def _show_session_graph(self, record):
        """Detail window: the session's CPU/GPU curves over time,
        with the warning lines, so a spike's shape is visible."""
        window = ctk.CTkToplevel(self)
        when = time.strftime("%b %d %H:%M",
                             time.localtime(record.get("start", 0)))
        window.title(f"Session graph — {record.get('game', '?')}")
        window.geometry("700x470")
        window.configure(fg_color=BG)
        ctk.CTkLabel(window,
                     text=f"{record.get('game', '?')}  •  {when}  •  "
                          f"{fmt_duration(record.get('duration_s'))}",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=18,
                                           pady=(14, 2))
        ctk.CTkLabel(window,
                     text=f"Peak CPU {fmt_temp(record.get('peak_cpu'))}"
                          f"  •  Peak GPU "
                          f"{fmt_temp(record.get('peak_gpu'))}",
                     font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", padx=18,
                                            pady=(0, 8))
        series = record.get("series") or []
        if not series:
            ctk.CTkLabel(window,
                         text="No temperature samples were recorded "
                              "for this session — it was recorded "
                              "before the graph feature.",
                         font=ctk.CTkFont(size=12), text_color=MUTED,
                         wraplength=620, justify="left",
                         anchor="w").pack(anchor="w", padx=18, pady=12)
            ctk.CTkButton(window, text="Close", fg_color=VIOLET,
                          text_color="white",
                          command=window.destroy).pack(pady=12)
            return
        width, height = 640, 280
        geometry = core.chart_points(
            series, width, height,
            warn_cpu=record.get("warn_cpu",
                                self.settings["warn_cpu_c"]),
            warn_gpu=record.get("warn_gpu",
                                self.settings["warn_gpu_c"]))
        canvas = tk.Canvas(window, width=width, height=height,
                           bg=PANEL, highlightthickness=0)
        canvas.pack(padx=18, pady=(0, 8))
        for mark, y in geometry["grid"]:
            canvas.create_line(44, y, width - 12, y, fill=PANEL_EDGE)
            canvas.create_text(38, y, text=f"{mark}°", fill=FAINT,
                               font=("Segoe UI", 9), anchor="e")
        if geometry["warn_cpu_y"] is not None:
            canvas.create_line(44, geometry["warn_cpu_y"], width - 12,
                               geometry["warn_cpu_y"], fill=RED,
                               dash=(5, 3))
        if geometry["warn_gpu_y"] is not None:
            canvas.create_line(44, geometry["warn_gpu_y"], width - 12,
                               geometry["warn_gpu_y"], fill=AMBER,
                               dash=(5, 3))
        if len(geometry["cpu"]) >= 2:
            canvas.create_line(*[coord for point in geometry["cpu"]
                                 for coord in point],
                               fill=ORANGE, width=2)
        if len(geometry["gpu"]) >= 2:
            canvas.create_line(*[coord for point in geometry["gpu"]
                                 for coord in point],
                               fill=CYAN, width=2)
        canvas.create_text(44, height - 8, text="0:00", fill=FAINT,
                           font=("Segoe UI", 9), anchor="n")
        canvas.create_text(width - 12, height - 8,
                           text=fmt_duration(geometry["t_max"]),
                           fill=FAINT, font=("Segoe UI", 9), anchor="n")
        legend = ctk.CTkFrame(window, fg_color="transparent")
        legend.pack(anchor="w", padx=18, pady=(0, 4))
        ctk.CTkLabel(legend, text="— CPU",
                     font=ctk.CTkFont(size=12),
                     text_color=ORANGE).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(legend, text="— GPU",
                     font=ctk.CTkFont(size=12),
                     text_color=CYAN).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(legend, text="- - CPU warning line",
                     font=ctk.CTkFont(size=12),
                     text_color=RED).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(legend, text="- - GPU warning line",
                     font=ctk.CTkFont(size=12),
                     text_color=AMBER).pack(side="left")
        if not geometry["cpu"]:
            ctk.CTkLabel(window, text="CPU: no samples in this session",
                         font=ctk.CTkFont(size=12),
                         text_color=MUTED).pack(anchor="w", padx=18)
        if not geometry["gpu"]:
            ctk.CTkLabel(window, text="GPU: no samples in this session",
                         font=ctk.CTkFont(size=12),
                         text_color=MUTED).pack(anchor="w", padx=18)
        ctk.CTkButton(window, text="Close", fg_color=VIOLET,
                      text_color="white",
                      command=window.destroy).pack(pady=10)

    # -- Settings actions -----------------------------------------------------

    def _save_settings(self):
        core.save_settings(self.settings)

    def _save_settings_form(self):
        def _num(entry, fallback):
            try:
                return float(entry.get().strip())
            except (TypeError, ValueError):
                return fallback

        raw = dict(self.settings)
        raw["warn_cpu_c"] = _num(self.warn_cpu_entry,
                                 self.settings["warn_cpu_c"])
        raw["warn_gpu_c"] = _num(self.warn_gpu_entry,
                                 self.settings["warn_gpu_c"])
        raw["poll_seconds"] = _num(self.poll_entry,
                                   self.settings["poll_seconds"])
        raw["lhm_port"] = _num(self.port_entry,
                               self.settings["lhm_port"])
        self.settings = core.normalize_settings(raw)
        self.tracker.warn_cpu = self.settings["warn_cpu_c"]
        self.tracker.warn_gpu = self.settings["warn_gpu_c"]
        self.warner.warn_c = self.settings["warn_cpu_c"]
        self.warner.reset()
        self._save_settings()
        self._log("Settings saved")

    def _toggle_game(self, name):
        for game in self.settings["games"]:
            if game["name"] == name:
                game["enabled"] = not game["enabled"]
        self._save_settings()

    def _toggle_tray(self):
        self.settings["minimize_to_tray"] = bool(self.tray_switch.get())
        self._save_settings()

    def _toggle_startup(self):
        enabled = bool(self.startup_switch.get())
        self.settings["start_with_windows"] = enabled
        self._save_settings()
        if core.is_windows():
            self._apply_startup_entry(enabled)

    def _apply_startup_entry(self, enabled):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE)
            with key:
                if enabled:
                    command = _startup_command(
                        getattr(sys, "frozen", False), sys.executable,
                        os.path.abspath(__file__))
                    winreg.SetValueEx(key, "HeatWatch", 0,
                                      winreg.REG_SZ, command)
                else:
                    try:
                        winreg.DeleteValue(key, "HeatWatch")
                    except FileNotFoundError:
                        pass
        except Exception as exc:
            core.log_line(f"startup entry failed: {exc}")

    def _open_lhm(self):
        path = core.find_lhm_exe(self.settings)
        if path:
            try:
                subprocess.Popen([path])
                self._log("LibreHardwareMonitor opened (approve the "
                          "admin prompt so it can read the CPU)")
                return
            except OSError as exc:
                core.log_line(f"LHM launch failed: {exc}")
        messagebox.showinfo(
            "LibreHardwareMonitor not found",
            "HeatWatch reads CPU temperatures from "
            "LibreHardwareMonitor (free, open source).\n\n"
            "Install it with:\n"
            "  winget install LibreHardwareMonitor.LibreHardwareMonitor\n"
            "or download the zip from its GitHub releases "
            "(github.com/LibreHardwareMonitor/LibreHardwareMonitor) "
            "— avoid look-alike download sites.\n\n"
            "Run it as administrator, keep it open, and for the "
            "fastest feed tick Options > Remote Web Server.")

    # -- Logging / tray --------------------------------------------------------

    def _log(self, message):
        core.log_line(message)
        stamp = time.strftime("%H:%M:%S")
        self._log_lines.append(f"{stamp}  {message}")
        self._log_lines = self._log_lines[-9:]
        self.log_label.configure(text="\n".join(self._log_lines))

    def _tray_image(self):
        icon = os.path.join(project_folder(), "heatwatch_icon.ico")
        if os.path.isfile(icon):
            try:
                image = Image.open(icon)
                image.thumbnail((64, 64))
                return image.convert("RGBA")
            except Exception:
                pass
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse([10, 10, 54, 54], outline=(249, 115, 22),
                     width=5)
        draw.ellipse([24, 24, 40, 40], fill=(248, 113, 113))
        return image

    def _ensure_tray(self):
        if not TRAY_AVAILABLE or self._tray_icon is not None:
            return self._tray_icon is not None
        menu = pystray.Menu(
            pystray.MenuItem("Open HeatWatch", self._tray_show,
                             default=True),
            pystray.MenuItem("Quit", self._tray_quit))
        self._tray_icon = pystray.Icon("HeatWatch",
                                       self._tray_image(),
                                       "HeatWatch", menu)
        self._tray_icon.run_detached()
        return True

    def _notify_tray(self, message, title="HeatWatch"):
        if not TRAY_AVAILABLE or not self._ensure_tray():
            return
        try:
            self._tray_icon.notify(message, title)
        except Exception:
            pass

    def _tray_show(self, icon=None, item=None):
        self.after(0, self._show_from_tray)

    def _show_from_tray(self):
        self._hidden_in_tray = False
        self.deiconify()
        self.lift()
        self.focus_force()
        self._maybe_show_whats_new()

    def _tray_quit(self, icon=None, item=None):
        self.after(0, self._on_close)

    def _start_in_tray(self):
        if self._ensure_tray():
            self.withdraw()
            self._hidden_in_tray = True
        else:
            self.iconify()

    def _should_tray_hide(self):
        return (not self._update_pending
                and self.settings["minimize_to_tray"]
                and TRAY_AVAILABLE)

    def _on_window_close(self):
        if self._update_pending:
            self._on_close()
            return
        if self._should_tray_hide() and self._ensure_tray():
            self.withdraw()
            self._hidden_in_tray = True
            if not self._tray_notified:
                self._tray_notified = True
                self._notify_tray("HeatWatch keeps watching from "
                                  "the tray.", "HeatWatch")
            return
        self._on_close()

    def _on_close(self):
        self._stop.set()
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self.destroy()

    # -- Self-update -------------------------------------------------------------

    def _check_update_worker(self):
        # Check at startup, then re-check every few minutes: the
        # app mostly lives in the tray, and one startup check that
        # raced a stale cache once meant no banner until a lucky
        # restart (GameMode, Nov 2026).
        while not self._stop.is_set():
            info = fetch_update_info()
            if info and parse_version(info["version"]) > parse_version(VERSION):
                self.msg_queue.put(("update_available", info))
                return
            if self._stop.wait(5 * 60):
                return

    def _show_update_banner(self, info):
        self.update_info = info
        if self._hidden_in_tray:
            self._notify_tray(
                f"Version {info['version']} is ready — open "
                f"HeatWatch to install it.",
                "HeatWatch update available")
        for child in self.banner_frame.winfo_children():
            child.destroy()
        banner = ctk.CTkFrame(self.banner_frame, fg_color=CARD,
                              corner_radius=10)
        banner.pack(fill="x")
        ctk.CTkLabel(banner, text=f"Update available: v{info['version']}",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=10,
                                           pady=(8, 0))
        notes = str(info.get("notes") or "")
        if notes:
            ctk.CTkLabel(banner, text=notes,
                         font=ctk.CTkFont(size=11), text_color=MUTED,
                         wraplength=240, justify="left",
                         anchor="w").pack(anchor="w", padx=10)
        row = ctk.CTkFrame(banner, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(4, 8))
        ctk.CTkButton(row, text="Update now", width=110,
                      fg_color=ORANGE, hover_color="#EA580C",
                      text_color="white",
                      command=self._start_update).pack(side="left")
        ctk.CTkButton(row, text="✕", width=30, fg_color="transparent",
                      text_color=MUTED,
                      command=banner.destroy).pack(side="right")

    def _start_update(self):
        info = self.update_info
        if not info:
            return
        if not messagebox.askyesno(
                "Update HeatWatch",
                f"Download and install version {info['version']}?\n\n"
                "HeatWatch will close, rebuild itself and reopen "
                "on the new version."):
            return
        self._log(f"Downloading update {info['version']}…")
        threading.Thread(target=self._download_worker,
                         daemon=True).start()

    def _download_worker(self):
        files = download_update_files()
        self.msg_queue.put(("update_downloaded", files))

    def _update_downloaded(self, files):
        if not files:
            self._log("Update download failed — nothing was changed")
            messagebox.showerror(
                "Update failed",
                "Could not download the update files. "
                "Nothing was changed.")
            return
        if self.update_info:
            save_whats_new(self.update_info)
        try:
            apply_update_files(project_folder(), files)
        except OSError as exc:
            messagebox.showerror(
                "Update failed", f"Could not write the new files:\n{exc}")
            return
        if getattr(sys, "frozen", False):
            self._update_pending = True
            self._write_update_helper()
            self._log("Update ready — restarting to finish the update")
            if self._hidden_in_tray:
                self._notify_tray(
                    "Updating now — HeatWatch will reopen on the "
                    "new version.", "HeatWatch update")
            # No modal dialog on this path (one unseen OK button
            # once stalled GameMode's whole update), and a timer
            # guarantees the exit the helper is waiting for.
            threading.Timer(1.0, os._exit, args=(0,)).start()
            self._on_close()
        else:
            self._log("Update ready — restart the app to use it")
            messagebox.showinfo(
                "Update ready",
                "The new files are in place. Restart the app to "
                "use the new version.")

    def _write_update_helper(self):
        project = project_folder()
        helper = os.path.join(project, "finish_update.bat")
        lines = update_helper_lines(project, sys.executable)
        with open(helper, "w", encoding="ascii") as fh:
            fh.write("\r\n".join(lines))
        subprocess.Popen(
            ["cmd", "/c", helper],
            # The helper gets its OWN console window, exactly like
            # a manual double-click of finish_update.bat. It used
            # to be DETACHED_PROCESS (no console): on Ariya's PC
            # the detached batch died silently right after its
            # first log line (Nov 22, 2026) - a windowed app's
            # invalid std handles kill cmd when it echoes. Manual
            # runs always worked; now automatic ones match them.
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )

    def _maybe_show_whats_new(self):
        if self._hidden_in_tray:
            return  # waits for a visible launch
        notes = pop_whats_new(VERSION)
        if notes is None:
            return
        window = ctk.CTkToplevel(self)
        window.title("What's New")
        window.geometry("440x320")
        window.configure(fg_color=BG)
        ctk.CTkLabel(window, text=f"What's new in v{VERSION}",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=18,
                                           pady=(16, 6))
        ctk.CTkLabel(window, text=notes, font=ctk.CTkFont(size=12),
                     text_color=MUTED, wraplength=400, justify="left",
                     anchor="w").pack(anchor="w", padx=18)
        ctk.CTkButton(window, text="Close", fg_color=VIOLET,
                      text_color="white",
                      command=window.destroy).pack(pady=16)


_mutex_handle = None


def _first_instance():
    """Single-instance guard (GameMode grew five stacked copies
    before it got one). Fails open: any doubt means proceed."""
    global _mutex_handle
    if not core.is_windows():
        return True
    try:
        import ctypes
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(
            None, False, "HeatWatch-SingleInstance-F97316")
        if not _mutex_handle:
            return True
        return ctypes.windll.kernel32.GetLastError() != 183
    except Exception:
        return True


def main():
    if not _first_instance():
        root = ctk.CTk()
        root.withdraw()
        messagebox.showinfo(
            "HeatWatch",
            "HeatWatch is already running — check the system tray.")
        root.destroy()
        return
    app = HeatWatchApp(start_minimized=_wants_minimized(sys.argv))
    app.mainloop()


if __name__ == "__main__":
    main()
