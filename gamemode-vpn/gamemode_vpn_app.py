"""GameMode VPN — Proton auto-pilot for game nights (CustomTkinter UI).

Watches for your games and handles Proton VPN around each session.
Auto mode clicks Proton's own Disconnect / Connect buttons through
Windows UI Automation and verifies every result live against your
real connection state; if a click is ever unavailable, a guided
step panel takes over. Closing the window minimizes to the tray.

Run:  python gamemode_vpn_app.py
Build: build.bat  (PyInstaller one-file exe)
Data: settings + log live in ~\\GameModeVPN, never next to the exe.
"""

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

import gamemode_core as core

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except Exception:  # tray is an enhancement, never a requirement
    pystray = None
    TRAY_AVAILABLE = False

VERSION = "1.2.6"

# Self-update channel: the gamemode-vpn/ folder of the same GitHub repo
# that carries Disk Cleaner. On startup the app fetches version.json;
# a newer version raises a banner with a one-click update.
UPDATE_REPO = "ariyast123/disk-cleaner"
UPDATE_PATH = "gamemode-vpn"

# ---------------------------------------------------------------------------
# Palette — deep-space navy, violet -> cyan accents (matches his starfield
# Firefox theme), semantic status colors.
# ---------------------------------------------------------------------------
BG = "#0A0C16"
SIDEBAR = "#0E1122"
PANEL = "#131731"
PANEL_EDGE = "#232850"
CARD = "#171C3A"
CARD_HOVER = "#1D2347"
VIOLET = "#7C5CFF"
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
}
CUSTOM_COLORS = ["#22D3EE", "#34D399", "#F472B6", "#FBBF24", "#60A5FA", "#A78BFA"]

STEP_STYLE = {
    "done": ("✓", GREEN),
    "current": ("●", AMBER),
    "next": ("○", FAINT),
    "warn": ("!", RED),
}


def fmt_duration(seconds):
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _tray_image():
    """The tray icon: the app icon (gamemode_icon.ico) when it is on
    disk, else the drawn orb — a violet ring with a cyan core."""
    try:
        icon_path = os.path.join(project_folder(), "gamemode_icon.ico")
        if os.path.isfile(icon_path):
            image = Image.open(icon_path).convert("RGBA")
            return image.resize((64, 64))
    except Exception:
        pass
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([5, 5, 59, 59], outline=(124, 92, 255, 255), width=4)
    draw.ellipse([21, 21, 43, 43], fill=(34, 211, 238, 255))
    return image


def project_folder():
    """The folder holding the .py sources and build.bat: when the exe
    sits in dist, that is the folder above it."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.basename(exe_dir).lower() == "dist":
            return os.path.dirname(exe_dir)
        return exe_dir
    return os.path.dirname(os.path.abspath(__file__))


def fetch_update_info(timeout=10):
    """Return the repo's gamemode version.json dict, or None."""
    import json
    import urllib.request

    url = (f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/"
           f"{UPDATE_PATH}/version.json")
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
        for name in core.UPDATE_FILES:
            url = (f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/"
                   f"{UPDATE_PATH}/{name}")
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                files[name] = resp.read()
    except Exception:
        return None
    return files if core.validate_update_files(files) else None


def apply_update_files(project_dir, files):
    """Write downloaded files into the project folder via temp names,
    so a failed write never leaves a half-written source file."""
    for name, data in files.items():
        tmp = os.path.join(project_dir, name + ".new")
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, os.path.join(project_dir, name))


def update_helper_lines(project, launched_exe):
    """The finish_update.bat body: wait for every GameModeVPN.exe to
    exit, rebuild, then copy the fresh exe back over the copy that
    was actually launched (a taskbar pin may point at a standalone
    copy outside dist) and relaunch THAT path — so a pinned
    shortcut can never resurrect an old version after an update.

    The wait is capped at ~60 seconds: the app that requested the
    update has already closed itself, so any copy still alive after
    that is a stale duplicate (five stacked copies once stalled an
    update silently) and is force-closed. Every phase is written
    into update_build.log from the first line, so a stall leaves
    evidence instead of a missing file."""
    built = os.path.join(project, "dist", "GameModeVPN.exe")
    return [
        "@echo off",
        "title GameMode VPN update",
        f'cd /d "{project}"',
        'echo [helper] update started - waiting for GameMode VPN '
        'to close > update_build.log',
        "set /a WAITS=0",
        ":waitloop",
        'tasklist /FI "IMAGENAME eq GameModeVPN.exe" 2>NUL | '
        'find /I "GameModeVPN.exe" >NUL',
        "if errorlevel 1 goto allclosed",
        "set /a WAITS+=1",
        "if %WAITS% GEQ 30 goto forceclose",
        "timeout /t 2 /nobreak >NUL",
        "goto waitloop",
        ":forceclose",
        'echo [helper] copies still running after 60s - '
        'closing them >> update_build.log',
        'taskkill /F /IM GameModeVPN.exe >NUL 2>&1',
        "timeout /t 2 /nobreak >NUL",
        ":allclosed",
        'echo [helper] building >> update_build.log',
        "call build.bat auto >> update_build.log 2>&1",
        f'set "BUILT={built}"',
        f'set "LAUNCHED={launched_exe}"',
        'if exist "%BUILT%" (',
        '  if /I not "%BUILT%"=="%LAUNCHED%" copy /Y "%BUILT%" "%LAUNCHED%" >NUL',
        '  start "" "%LAUNCHED%"',
        ") else (",
        '  if exist "%LAUNCHED%" start "" "%LAUNCHED%"',
        ")",
        "",
    ]


class GameModeApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = core.load_settings()
        self.engine = core.Engine(self.settings)
        self.cache = core.SnapshotCache()
        self.msg_queue = queue.Queue()
        self._stop = threading.Event()
        self._steps_signature = None
        self._games_signature = None
        self._launched_session = None
        self.manual_restore = False
        self._auto_marks = {}       # auto action -> marker already attempted
        self._restore_seq = 0
        self._update_pending = False
        self._tray_icon = None
        self._tray_notice_shown = False
        self._pulse_phase = False
        self._log_lines = []

        self.title("GameMode VPN")
        try:
            _icon = os.path.join(project_folder(), "gamemode_icon.ico")
            if os.path.isfile(_icon):
                self.iconbitmap(_icon)
        except Exception:
            pass
        self.geometry("1140x760")
        self.minsize(1000, 660)
        self.configure(fg_color=BG)

        self._build_sidebar()
        self._build_main()
        self._rebuild_game_rows()
        self._refresh_proton_path()
        self._log("GameMode VPN started — watching for games")

        self.update_info = None
        self._worker = threading.Thread(target=self._watch_loop, daemon=True)
        self._worker.start()
        threading.Thread(target=self._check_update_worker, daemon=True).start()
        self.after(120, self._drain_queue)
        self.after(500, self._tick)
        self.after(700, self._maybe_show_whats_new)
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, width=308, fg_color=SIDEBAR, corner_radius=0)
        bar.grid(row=0, column=0, sticky="nsew")
        bar.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(bar, text="GAMEMODE", font=ctk.CTkFont("Segoe UI", 25, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=22, pady=(22, 0))
        ctk.CTkLabel(bar, text="VPN", font=ctk.CTkFont("Segoe UI", 25, "bold"),
                     text_color=VIOLET).pack(anchor="w", padx=22)
        ctk.CTkLabel(bar, text="Proton auto-pilot for game nights",
                     font=ctk.CTkFont("Segoe UI", 12), text_color=MUTED).pack(
                         anchor="w", padx=22, pady=(2, 10))

        # Status orb (canvas so it can glow / pulse)
        self.orb = tk.Canvas(bar, width=118, height=118, bg=SIDEBAR,
                             highlightthickness=0)
        self.orb.pack(pady=(6, 2))
        self._orb_ring = self.orb.create_oval(9, 9, 109, 109, outline=FAINT, width=2)
        self._orb_core = self.orb.create_oval(24, 24, 94, 94, fill=FAINT, outline="")

        self.status_headline = ctk.CTkLabel(
            bar, text="CHECKING…", font=ctk.CTkFont("Segoe UI", 19, "bold"),
            text_color=TEXT)
        self.status_headline.pack(pady=(2, 0))
        self.status_sub = ctk.CTkLabel(
            bar, text="Reading your connection state", wraplength=264,
            font=ctk.CTkFont("Segoe UI", 12), text_color=MUTED)
        self.status_sub.pack(pady=(0, 12))

        info = ctk.CTkFrame(bar, fg_color=PANEL, corner_radius=14,
                            border_width=1, border_color=PANEL_EDGE)
        info.pack(fill="x", padx=18, pady=(2, 14))
        self.info_rows = {}
        for key, label in (("vpn", "VPN"), ("ks", "Kill switch"),
                           ("game", "Active game"), ("session", "Session")):
            row = ctk.CTkFrame(info, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=5)
            ctk.CTkLabel(row, text=label, width=86, anchor="w",
                         font=ctk.CTkFont("Segoe UI", 12), text_color=MUTED).pack(side="left")
            value = ctk.CTkLabel(row, text="—", anchor="w",
                                 font=ctk.CTkFont("Segoe UI", 12, "bold"),
                                 text_color=TEXT)
            value.pack(side="left", fill="x", expand=True)
            self.info_rows[key] = value

        ctk.CTkButton(bar, text="Open Proton", height=42, corner_radius=12,
                      fg_color=VIOLET, hover_color="#6A4BF0", text_color="white",
                      font=ctk.CTkFont("Segoe UI", 14, "bold"),
                      command=self._open_proton).pack(fill="x", padx=18, pady=(2, 8))
        ctk.CTkButton(bar, text="Restore VPN", height=38, corner_radius=12,
                      fg_color="transparent", border_width=1, border_color=PANEL_EDGE,
                      hover_color=CARD_HOVER, text_color=TEXT,
                      font=ctk.CTkFont("Segoe UI", 13),
                      command=self._restore_clicked).pack(fill="x", padx=18)

        # Self-update banner (hidden until an update is available)
        self.update_banner = ctk.CTkFrame(bar, fg_color="#2A2140", corner_radius=12,
                                          border_width=1, border_color=VIOLET)
        self.update_label = ctk.CTkLabel(
            self.update_banner, text="", wraplength=248, justify="left", anchor="w",
            font=ctk.CTkFont("Segoe UI", 12, "bold"), text_color=TEXT)
        self.update_label.pack(anchor="w", padx=12, pady=(10, 4))
        banner_btns = ctk.CTkFrame(self.update_banner, fg_color="transparent")
        banner_btns.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(banner_btns, text="Update now", height=30, corner_radius=9,
                      fg_color=VIOLET, hover_color="#6A4BF0", text_color="white",
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      command=self._start_update).pack(side="left")
        ctk.CTkButton(banner_btns, text="✕", width=30, height=30, corner_radius=9,
                      fg_color="transparent", hover_color=CARD_HOVER, text_color=MUTED,
                      command=self._dismiss_update_banner).pack(side="left", padx=6)

        ctk.CTkLabel(bar, text=f"v{VERSION}  •  data in ~/GameModeVPN",
                     font=ctk.CTkFont("Segoe UI", 10), text_color=FAINT).pack(
                         side="bottom", pady=12)

    def _build_main(self):
        main = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        self.main_frame = main

        # violet -> cyan accent bar
        accent = ctk.CTkFrame(main, fg_color="transparent", height=4)
        accent.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        accent.grid_columnconfigure(0, weight=1)
        accent.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(accent, fg_color=VIOLET, height=4, corner_radius=0).grid(
            row=0, column=0, sticky="ew")
        ctk.CTkFrame(accent, fg_color=CYAN, height=4, corner_radius=0).grid(
            row=0, column=1, sticky="ew")

        # Action panel (hidden until steps exist)
        self.action_panel = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=16,
                                         border_width=1, border_color=AMBER)
        self.action_title = ctk.CTkLabel(
            self.action_panel, text="ACTION NEEDED",
            font=ctk.CTkFont("Segoe UI", 15, "bold"), text_color=AMBER)
        self.action_title.pack(anchor="w", padx=18, pady=(14, 4))
        self.action_steps = ctk.CTkFrame(self.action_panel, fg_color="transparent")
        self.action_steps.pack(fill="x", padx=18)
        ctk.CTkButton(self.action_panel, text="Open Proton", height=36,
                      corner_radius=10, fg_color=AMBER, hover_color="#E5A812",
                      text_color="#191104", font=ctk.CTkFont("Segoe UI", 13, "bold"),
                      command=self._open_proton).pack(anchor="w", padx=18, pady=(8, 14))
        self._action_row = 1

        # Games card
        games_card = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=16,
                                  border_width=1, border_color=PANEL_EDGE)
        games_card.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        header = ctk.CTkFrame(games_card, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(14, 6))
        ctk.CTkLabel(header, text="WATCHED GAMES",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=TEXT).pack(side="left")
        ctk.CTkButton(header, text="+ Add game", width=96, height=30,
                      corner_radius=9, fg_color=CARD, hover_color=CARD_HOVER,
                      text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12),
                      command=self._toggle_add_form).pack(side="right")

        self._add_form_visible = False
        self.add_form = ctk.CTkFrame(games_card, fg_color=CARD, corner_radius=12)
        self.new_name = ctk.CTkEntry(self.add_form, placeholder_text="Game name (e.g. Valorant)",
                                     fg_color=BG, border_color=PANEL_EDGE, text_color=TEXT)
        self.new_name.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=10)
        self.new_exes = ctk.CTkEntry(self.add_form, placeholder_text="Process names, comma separated (e.g. valorant.exe)",
                                     fg_color=BG, border_color=PANEL_EDGE, text_color=TEXT)
        self.new_exes.pack(side="left", fill="x", expand=True, padx=6, pady=10)
        ctk.CTkButton(self.add_form, text="Add", width=64, height=30, corner_radius=9,
                      fg_color=VIOLET, hover_color="#6A4BF0", text_color="white",
                      command=self._add_game).pack(side="left", padx=(6, 12), pady=10)

        self.games_holder = ctk.CTkFrame(games_card, fg_color="transparent")
        self.games_holder.pack(fill="x", padx=10, pady=(2, 12))

        # Settings card
        settings_card = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=16,
                                     border_width=1, border_color=PANEL_EDGE)
        settings_card.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        ctk.CTkLabel(settings_card, text="SETTINGS",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=18, pady=(14, 6))

        self.auto_launch_var = tk.BooleanVar(value=bool(self.settings["auto_launch_proton"]))
        ctk.CTkSwitch(settings_card, text="Open Proton automatically when a game starts",
                      variable=self.auto_launch_var, progress_color=VIOLET,
                      font=ctk.CTkFont("Segoe UI", 12), text_color=TEXT,
                      command=self._save_toggles).pack(anchor="w", padx=18, pady=5)
        self.auto_mode_var = tk.BooleanVar(value=bool(self.settings["auto_mode"]))
        ctk.CTkSwitch(settings_card, text="Auto mode — click Proton's buttons for me",
                      variable=self.auto_mode_var, progress_color=VIOLET,
                      font=ctk.CTkFont("Segoe UI", 12), text_color=TEXT,
                      command=self._save_toggles).pack(anchor="w", padx=18, pady=5)
        self.tray_var = tk.BooleanVar(value=bool(self.settings["minimize_to_tray"]))
        ctk.CTkSwitch(settings_card, text="Minimize to tray when closing the window",
                      variable=self.tray_var, progress_color=VIOLET,
                      font=ctk.CTkFont("Segoe UI", 12), text_color=TEXT,
                      command=self._save_toggles).pack(anchor="w", padx=18, pady=5)
        self.start_win_var = tk.BooleanVar(value=bool(self.settings["start_with_windows"]))
        ctk.CTkSwitch(settings_card, text="Start with Windows",
                      variable=self.start_win_var, progress_color=VIOLET,
                      font=ctk.CTkFont("Segoe UI", 12), text_color=TEXT,
                      command=self._save_toggles).pack(anchor="w", padx=18, pady=5)

        path_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        path_row.pack(fill="x", padx=18, pady=(8, 14))
        ctk.CTkLabel(path_row, text="Proton app:", font=ctk.CTkFont("Segoe UI", 12),
                     text_color=MUTED).pack(side="left")
        self.proton_path_label = ctk.CTkLabel(path_row, text="—",
                                              font=ctk.CTkFont("Segoe UI", 12),
                                              text_color=TEXT)
        self.proton_path_label.pack(side="left", padx=8)
        ctk.CTkButton(path_row, text="Browse…", width=78, height=28, corner_radius=8,
                      fg_color=CARD, hover_color=CARD_HOVER, text_color=TEXT,
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._browse_proton).pack(side="left")

        # Log card
        log_card = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=16,
                                border_width=1, border_color=PANEL_EDGE)
        log_card.grid(row=4, column=0, sticky="ew")
        ctk.CTkLabel(log_card, text="ACTIVITY",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=18, pady=(14, 6))
        self.log_box = ctk.CTkTextbox(log_card, height=118, fg_color=BG,
                                      text_color=MUTED, corner_radius=10,
                                      font=ctk.CTkFont("Consolas", 11))
        self.log_box.pack(fill="x", padx=14, pady=(0, 14))
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------
    # Game rows
    # ------------------------------------------------------------------

    def _games_signature_value(self):
        games = tuple((g["name"], g["enabled"]) for g in self.settings["games"])
        return games, tuple(sorted(self.engine.active_games))

    def _rebuild_game_rows(self):
        for child in self.games_holder.winfo_children():
            child.destroy()
        custom_idx = 0
        for game in self.settings["games"]:
            row = ctk.CTkFrame(self.games_holder, fg_color=CARD, corner_radius=12)
            row.pack(fill="x", pady=4)
            color = GAME_COLORS.get(game["name"])
            if color is None:
                color = CUSTOM_COLORS[custom_idx % len(CUSTOM_COLORS)]
                custom_idx += 1
            initials = "".join(word[0] for word in game["name"].split()[:2]).upper() or "?"
            ctk.CTkLabel(row, text=initials, width=40, height=40, corner_radius=10,
                         fg_color=color, text_color="white",
                         font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(
                             side="left", padx=(10, 10), pady=8)
            text_col = ctk.CTkFrame(row, fg_color="transparent")
            text_col.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(text_col, text=game["name"], anchor="w",
                         font=ctk.CTkFont("Segoe UI", 13, "bold"),
                         text_color=TEXT).pack(fill="x")
            ctk.CTkLabel(text_col, text=", ".join(game["patterns"]), anchor="w",
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=MUTED).pack(fill="x")
            running = game["name"] in self.engine.active_games
            ctk.CTkLabel(row, text="● running" if running else "",
                         width=74, text_color=GREEN,
                         font=ctk.CTkFont("Segoe UI", 11, "bold")).pack(side="left")
            var = tk.BooleanVar(value=bool(game["enabled"]))
            ctk.CTkSwitch(row, text="", width=46, variable=var, progress_color=VIOLET,
                          command=lambda g=game, v=var: self._toggle_game(g, v)).pack(
                              side="left", padx=(2, 4))
            if not game.get("builtin"):
                ctk.CTkButton(row, text="✕", width=30, height=30, corner_radius=8,
                              fg_color="transparent", hover_color=CARD_HOVER,
                              text_color=MUTED,
                              command=lambda g=game: self._remove_game(g)).pack(
                                  side="left", padx=(0, 8))
        self._games_signature = self._games_signature_value()

    def _toggle_game(self, game, var):
        game["enabled"] = bool(var.get())
        core.save_settings(self.settings)
        self._log(f"{game['name']} watching {'on' if game['enabled'] else 'off'}")

    def _remove_game(self, game):
        self.settings["games"] = [g for g in self.settings["games"]
                                  if g["name"] != game["name"]]
        core.save_settings(self.settings)
        self._games_signature = None
        self._rebuild_game_rows()
        self._log(f"Removed {game['name']} from the watch list")

    def _toggle_add_form(self):
        if self._add_form_visible:
            self.add_form.pack_forget()
            self._add_form_visible = False
        else:
            self.add_form.pack(fill="x", padx=10, pady=(4, 2),
                               after=self.games_holder.master.winfo_children()[0])
            self._add_form_visible = True

    def _add_game(self):
        name = self.new_name.get().strip()
        patterns = [p.strip().lower() for p in self.new_exes.get().split(",") if p.strip()]
        if not name or not patterns:
            self._log("Add game needs a name and at least one process name")
            return
        if any(g["name"].lower() == name.lower() for g in self.settings["games"]):
            self._log(f"{name} is already on the watch list")
            return
        self.settings["games"].append(
            {"name": name, "patterns": patterns, "enabled": True, "builtin": False})
        core.save_settings(self.settings)
        self.new_name.delete(0, "end")
        self.new_exes.delete(0, "end")
        self.add_form.pack_forget()
        self._add_form_visible = False
        self._games_signature = None
        self._rebuild_game_rows()
        self._log(f"Added {name} to the watch list")

    # ------------------------------------------------------------------
    # Settings actions
    # ------------------------------------------------------------------

    def _save_toggles(self):
        self.settings["auto_launch_proton"] = bool(self.auto_launch_var.get())
        self.settings["auto_mode"] = bool(self.auto_mode_var.get())
        self.settings["minimize_to_tray"] = bool(self.tray_var.get())
        want_start = bool(self.start_win_var.get())
        if want_start != bool(self.settings["start_with_windows"]):
            self.settings["start_with_windows"] = want_start
            self._apply_start_with_windows(want_start)
        core.save_settings(self.settings)

    def _apply_start_with_windows(self, enable):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE)
            if enable:
                if getattr(sys, "frozen", False):
                    command = f'"{sys.executable}"'
                else:
                    command = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
                winreg.SetValueEx(key, "GameModeVPN", 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, "GameModeVPN")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            self._log(f"Start with Windows {'on' if enable else 'off'}")
        except (ImportError, OSError) as exc:
            self._log(f"Could not change the Windows startup entry ({exc})")

    def _browse_proton(self):
        path = filedialog.askopenfilename(
            title="Find the Proton app (ProtonVPN.Client.exe)",
            filetypes=[("Executables", "*.exe"), ("All files", "*.*")])
        if path:
            self.settings["proton_path"] = path
            core.save_settings(self.settings)
            self._refresh_proton_path()
            self._log(f"Proton app set to {path}")

    def _refresh_proton_path(self):
        found = core.find_proton_exe(self.settings)
        if found:
            self.proton_path_label.configure(text=found, text_color=TEXT)
        else:
            self.proton_path_label.configure(
                text="Not found — Browse to ProtonVPN.Client.exe", text_color=AMBER)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _open_proton(self):
        path = core.launch_proton(self.settings)
        if path:
            self._log("Proton opened — do the highlighted step there")
        else:
            self._log("Proton app not found — set its path under Settings")
            self._refresh_proton_path()

    def _restore_clicked(self):
        if self.engine.vpn_state == "protected":
            self._log("Already protected — nothing to restore")
            return
        self.manual_restore = True
        self._steps_signature = None
        self._open_proton()
        self._maybe_auto("connect", ("manual", int(time.time())))
        self._refresh_status()

    # ------------------------------------------------------------------
    # Self-update (GitHub): check on startup, banner, one-click apply,
    # What's New shown once after the update lands.
    # ------------------------------------------------------------------

    def _check_update_worker(self):
        info = fetch_update_info()
        if info and core.parse_version(info["version"]) > core.parse_version(VERSION):
            self.msg_queue.put(("update_available", info))

    def _show_update_banner(self, info):
        self.update_info = info
        text = f"Update available: v{info['version']}"
        notes = (info.get("notes") or "").strip()
        if notes:
            text += f" — {notes}"
        self.update_label.configure(text=text)
        if not self.update_banner.winfo_manager():
            self.update_banner.pack(fill="x", padx=18, pady=(12, 0))
        self._log(f"Update available: v{info['version']}")

    def _dismiss_update_banner(self):
        self.update_banner.pack_forget()

    def _start_update(self):
        if not self.update_info:
            return
        if not messagebox.askyesno(
            "Update GameMode VPN",
            f"Download version {self.update_info['version']} and update?\n\n"
            "The new files go into the project folder. When you then close "
            "GameMode VPN, it rebuilds itself and reopens automatically — "
            "that takes about a minute.",
        ):
            return
        self.update_banner.pack_forget()
        self._log("Downloading update…")

        def worker():
            files = download_update_files()
            self.msg_queue.put(("update_downloaded", files))

        threading.Thread(target=worker, daemon=True).start()

    def _update_downloaded(self, files):
        if not files:
            self._log("Update download failed — nothing was changed")
            messagebox.showerror(
                "Update failed",
                "Could not download the update files. Nothing was changed.")
            return
        # Save the patch notes first: the NEW build shows them once.
        if self.update_info:
            core.save_whats_new(self.update_info)
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
            messagebox.showinfo(
                "Update ready",
                "The new files are in place.\n\nGameMode VPN will now "
                "close, rebuild itself and reopen on the new version.")
            self._on_close()
        else:
            self._log("Update ready — restart the app to use it")
            messagebox.showinfo(
                "Update ready",
                "The new files are in place. Restart the app to use the "
                "new version.")

    def _write_update_helper(self):
        """Write finish_update.bat and start it detached: it waits for
        this app to exit, rebuilds the exe and relaunches it."""
        project = project_folder()
        helper = os.path.join(project, "finish_update.bat")
        lines = update_helper_lines(project, sys.executable)
        with open(helper, "w", encoding="ascii") as fh:
            fh.write("\r\n".join(lines))
        subprocess.Popen(
            ["cmd", "/c", helper],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )

    def _maybe_show_whats_new(self):
        data = core.pop_whats_new(VERSION)
        if not data:
            return
        notes = (data.get("patch_notes") or "").strip() or "Small fixes and polish."
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"What's New in v{data.get('version', VERSION)}")
        dialog.geometry("440x300")
        dialog.configure(fg_color=BG)
        dialog.transient(self)
        ctk.CTkLabel(dialog, text=f"What's New in v{data.get('version', VERSION)}",
                     font=ctk.CTkFont("Segoe UI", 16, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(18, 6))
        ctk.CTkLabel(dialog, text=notes, wraplength=392, justify="left", anchor="w",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=MUTED).pack(anchor="w", padx=20, fill="x")
        ctk.CTkButton(dialog, text="Close", height=34, corner_radius=10,
                      fg_color=VIOLET, hover_color="#6A4BF0", text_color="white",
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      command=dialog.destroy).pack(side="bottom", pady=16)
        self._log(f"Updated to v{data.get('version', VERSION)} — What's New shown")

    # ------------------------------------------------------------------
    # Watch loop + queue
    # ------------------------------------------------------------------

    def _watch_loop(self):
        while not self._stop.is_set():
            try:
                running, state = core.collect_snapshot(self.settings, self.cache)
                self.msg_queue.put(("snapshot", running, state))
            except Exception as exc:  # never let the watcher die silently
                self.msg_queue.put(("error", str(exc)))
            self._stop.wait(float(self.settings.get("poll_seconds", 2.0)))

    def _drain_queue(self):
        try:
            while True:
                item = self.msg_queue.get_nowait()
                if item[0] == "snapshot":
                    self._apply_snapshot(item[1], item[2])
                elif item[0] == "error":
                    self._log(f"Watcher hiccup: {item[1]}")
                elif item[0] == "update_available":
                    self._show_update_banner(item[1])
                elif item[0] == "update_downloaded":
                    self._update_downloaded(item[1])
                elif item[0] == "auto_result":
                    self._auto_result(item[1], item[2], item[3])
                elif item[0] == "tray_show":
                    self._show_from_tray()
                elif item[0] == "tray_quit":
                    self._on_close()
        except queue.Empty:
            pass
        self.after(120, self._drain_queue)

    def _apply_snapshot(self, running, state):
        events = self.engine.update(running, state)
        for event in events:
            self._handle_event(event)
        learned = self.engine.ks_seen
        if learned is not None and self.settings.get("kill_switch_seen") != learned:
            self.settings["kill_switch_seen"] = learned
            core.save_settings(self.settings)
            self._log("Kill switch " + (
                "detected — the steps include it" if learned
                else "not in play — steps shortened"))
        if self.manual_restore and state == "protected":
            self.manual_restore = False
            self._log("Protected again — routine complete")
        if self._games_signature != self._games_signature_value():
            self._rebuild_game_rows()
        self._refresh_status()

    def _handle_event(self, event):
        if event.startswith("game_started:"):
            name = event.split(":", 1)[1]
            self._log(f"Game detected: {name}")
            if self.settings["auto_launch_proton"]:
                self._launch_once_for_session()
        elif event == "action_needed":
            self._log("Proton is still on — follow the steps to go bare")
            if self.settings["auto_launch_proton"]:
                self._launch_once_for_session()
            self._maybe_auto("disconnect", self.engine.session_start)
        elif event == "blocked_midway":
            self._log("Kill switch is still ON — internet blocked (expected mid-step)")
        elif event == "game_mode_on":
            self._log("GAME MODE ON — you are bare, good to play")
            self._auto_marks.pop("disconnect", None)
        elif event == "game_ended":
            self._log("Game closed")
            self._launched_session = None
            self._auto_marks.pop("disconnect", None)
        elif event == "restore_needed":
            self._restore_seq += 1
            self._log("Session over — restore your VPN (steps above)")
            if self.settings["auto_launch_proton"]:
                self._launch_once_for_session()
            self._maybe_auto("connect", ("restore", self._restore_seq))
        elif event == "protected_restored":
            self.manual_restore = False
            self._auto_marks.pop("connect", None)
            self._log("Protected again — routine complete")

    # ------------------------------------------------------------------
    # Auto mode: click Proton's buttons via UI Automation (core layer
    # does the work; any failure leaves the guided steps in charge).
    # ------------------------------------------------------------------

    def _maybe_auto(self, action, marker):
        if not self.settings.get("auto_mode", True):
            return
        if self._auto_marks.get(action) == marker:
            return
        self._auto_marks[action] = marker
        self._log(f"Auto mode: asking Proton to {action}…")

        def worker():
            core.launch_proton(self.settings)
            ok, detail = core.auto_proton_action(action)
            self.msg_queue.put(("auto_result", action, ok, detail))

        threading.Thread(target=worker, daemon=True).start()

    def _auto_result(self, action, ok, detail):
        if ok:
            self._log(f"Auto mode: {detail} — verifying…")
            return
        # A late failure is not a failure when the job is already
        # done — e.g. Ariya clicked Disconnect himself while the
        # auto scan was still looking for the button.
        if action == "disconnect" and self.engine.vpn_state == "bare":
            self._log("Auto mode: already bare — no click was needed")
            return
        if action == "connect" and self.engine.vpn_state == "protected":
            self._log("Auto mode: already protected — no click was needed")
            return
        self._log(f"Auto mode could not {action} ({detail}) — the steps above still work")

    def _launch_once_for_session(self):
        marker = self.engine.session_start or "restore"
        if self._launched_session != marker:
            self._launched_session = marker
            self._open_proton()

    # ------------------------------------------------------------------
    # Status rendering
    # ------------------------------------------------------------------

    def _status_display(self):
        mode, state = self.engine.mode, self.engine.vpn_state
        if mode == "gaming":
            return CYAN, "GAME MODE", "VPN off on purpose — ping is all yours"
        if mode == "action_needed":
            return AMBER, "ACTION NEEDED", "A game is up but Proton is still in the way"
        if mode == "restore_needed" or (self.manual_restore and state != "protected"):
            return AMBER, "RESTORE VPN", "Session over — reconnect and re-arm the kill switch"
        if state == "protected":
            return GREEN, "PROTECTED", "Proton connected — traffic is tunneled"
        if state == "bare":
            return RED, "UNPROTECTED", "Proton is off — you are on your bare connection"
        if state == "blocked":
            return RED, "BLOCKED", "Kill switch is on but the VPN is off — no internet"
        return FAINT, "CHECKING…", "Reading your connection state"

    def _refresh_status(self):
        color, headline, sub = self._status_display()
        self.orb.itemconfigure(self._orb_core, fill=color)
        self.orb.itemconfigure(self._orb_ring, outline=color)
        self.status_headline.configure(text=headline, text_color=color)
        self.status_sub.configure(text=sub)

        state = self.engine.vpn_state
        self.info_rows["vpn"].configure(text={
            "protected": "Connected", "bare": "Off", "blocked": "Off",
            "unknown": "—"}.get(state, "—"))
        self.info_rows["ks"].configure(text={
            "protected": "On (Advanced)", "bare": "Off / not blocking",
            "blocked": "ON — blocking", "unknown": "—"}.get(state, "—"))
        games = ", ".join(sorted(self.engine.active_games)) or "—"
        self.info_rows["game"].configure(text=games)

        steps = self.engine.current_steps()
        if self.manual_restore and state != "protected" and self.engine.mode == "idle":
            steps = [
                ("In Proton: click Connect (Quick Connect)", "current"),
                ("Then set Kill Switch back to Advanced and click Apply", "next"),
                ("Protection restores by itself once the tunnel is up", "next"),
            ]
        signature = (self.engine.mode, state, tuple(steps), self.manual_restore)
        if signature != self._steps_signature:
            self._steps_signature = signature
            self._render_steps(steps)

    def _render_steps(self, steps):
        for child in self.action_steps.winfo_children():
            child.destroy()
        if not steps:
            self.action_panel.grid_remove()
            return
        self.action_panel.grid(row=self._action_row, column=0, sticky="ew",
                               pady=(0, 14))
        self.action_title.configure(
            text="RESTORE YOUR VPN" if self.engine.mode == "restore_needed"
            or self.manual_restore else "ACTION NEEDED — GO BARE FOR THE GAME")
        for text, state in steps:
            icon, color = STEP_STYLE[state]
            row = ctk.CTkFrame(self.action_steps, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=icon, width=22, text_color=color,
                         font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(side="left")
            ctk.CTkLabel(row, text=text, wraplength=560, justify="left", anchor="w",
                         font=ctk.CTkFont("Segoe UI", 12),
                         text_color=TEXT if state in ("current", "warn") else MUTED).pack(
                             side="left", fill="x", expand=True)

    def _tick(self):
        # session clock
        if self.engine.mode == "gaming":
            self.info_rows["session"].configure(
                text=fmt_duration(self.engine.game_mode_seconds()))
        elif self.engine.session_start is not None:
            self.info_rows["session"].configure(
                text=fmt_duration(self.engine.session_seconds()))
        else:
            self.info_rows["session"].configure(text="—")
        # orb pulse while action is needed
        needs = self.engine.mode in ("action_needed", "restore_needed") or self.manual_restore
        if needs:
            self._pulse_phase = not self._pulse_phase
            color, _, _ = self._status_display()
            self.orb.itemconfigure(
                self._orb_ring, outline=color if self._pulse_phase else PANEL_EDGE)
        self.after(500, self._tick)

    # ------------------------------------------------------------------
    # Log + lifecycle
    # ------------------------------------------------------------------

    def _log(self, text):
        stamp = time.strftime("%H:%M:%S")
        core.log_line(text)
        self._log_lines.append(f"{stamp}  {text}")
        self._log_lines = self._log_lines[-9:]
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", "\n".join(self._log_lines))
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------
    # Tray: closing the window hides the app; the watcher keeps
    # running. Quit lives in the tray menu (and closing quits as
    # usual when the tray toggle is off or the tray is unavailable).
    # ------------------------------------------------------------------

    def _should_tray_hide(self):
        return bool(self.settings.get("minimize_to_tray", True)) and TRAY_AVAILABLE

    def _ensure_tray(self):
        if self._tray_icon is not None:
            return True
        if not TRAY_AVAILABLE:
            return False
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Open GameMode VPN",
                                 lambda icon, item: self.msg_queue.put(("tray_show",)),
                                 default=True),
                pystray.MenuItem("Quit",
                                 lambda icon, item: self.msg_queue.put(("tray_quit",))),
            )
            self._tray_icon = pystray.Icon("gamemode-vpn", _tray_image(), "GameMode VPN", menu)
            self._tray_icon.run_detached()
            return True
        except Exception:
            self._tray_icon = None
            return False

    def _on_window_close(self):
        if self._update_pending:
            # an update helper is waiting for this process to exit;
            # hiding to the tray would stall it forever
            self._on_close()
            return
        if self._should_tray_hide() and self._ensure_tray():
            self.withdraw()
            if not self._tray_notice_shown:
                self._tray_notice_shown = True
                try:
                    self._tray_icon.notify(
                        "Still watching for games. Right-click the tray icon "
                        "to open GameMode VPN or quit it.",
                        "GameMode VPN is in the tray")
                except Exception:
                    pass
            return
        self._on_close()

    def _show_from_tray(self):
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _on_close(self):
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self._stop.set()
        self.destroy()


_mutex_handle = None


def _first_instance():
    """True when this process is the only GameMode VPN instance.

    Windows: a named mutex — a second launch sees ERROR_ALREADY_EXISTS
    and backs off instead of stacking up another hidden copy (five
    stacked instances once stalled the updater, which waits for every
    GameModeVPN.exe process to exit before it may rebuild). Any failure,
    and every non-Windows platform, means "proceed": the guard must
    never be the reason the app does not open.
    """
    global _mutex_handle
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        handle = ctypes.windll.kernel32.CreateMutexW(
            None, False, "GameModeVPN-SingleInstance-7C5CFF"
        )
        if not handle:
            return True
        if ctypes.windll.kernel32.GetLastError() == 183:  # ALREADY_EXISTS
            return False
        _mutex_handle = handle  # keep it open for the process lifetime
        return True
    except Exception:
        return True


def main():
    if not _first_instance():
        root = ctk.CTk()
        root.withdraw()
        messagebox.showinfo(
            "GameMode VPN",
            "GameMode VPN is already running.\n"
            "Look for its window or its icon in the system tray.",
        )
        root.destroy()
        return
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    GameModeApp().mainloop()


if __name__ == "__main__":
    main()
