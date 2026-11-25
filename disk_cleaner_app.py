"""Disk Cleaner - a careful Windows disk cleanup tool.

Design rules:
  * Scan first, show everything, delete nothing without an explicit tick
    and a confirmation.
  * Deletion goes to the Recycle Bin (recoverable), never permanent.
  * System space hogs (Windows.old, WinSxS, hiberfil.sys...) are only
    measured and explained - the app points to the official safe tool
    instead of deleting system files itself.
  * Known cache folders are scanned individually. AppData as a whole is
    never opened, and folders like Discord's "Local Storage" (settings)
    are never touched.

Run:  python disk_cleaner_app.py
Build: build.bat  (creates dist\\DiskCleaner.exe)
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

import cleaner_core as core

try:
    from send2trash import send2trash

    SEND2TRASH_OK = True
except ImportError:
    SEND2TRASH_OK = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

CHECKED = "☑"
UNCHECKED = "☐"

# Cohesive dark palette used across sidebar, cards and the results tree.
C = {
    "bg": "#16181b",
    "panel": "#1e2126",
    "panel2": "#262a31",
    "border": "#33373f",
    "text": "#e9ebee",
    "muted": "#9aa1ab",
    "accent": "#3d8bfd",
    "accent_hover": "#2f7ae0",
    "danger": "#c0453a",
    "danger_hover": "#a83a30",
    "ok": "#3fa46a",
    "warn": "#d9933a",
    "tree_a": "#22252a",
    "tree_b": "#1e2126",
    "tree_cat": "#2c3644",
}


def profile_folder(name):
    return os.path.join(os.path.expanduser("~"), name)


def own_folders():
    """Folders this app itself lives in - never scanned or listed.

    Running as a built exe, that is the exe's folder; if the exe sits
    in a dist subfolder (the usual PyInstaller layout), the project
    folder above it - where the .py sources and build.bat live -
    counts too. Without this, a project folder kept inside Downloads
    would be scanned like any other folder, and the app's own source
    files could be flagged as duplicates of each other.
    """
    if getattr(sys, "frozen", False):
        here = os.path.dirname(os.path.abspath(sys.executable))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
    folders = [here]
    if os.path.basename(here).lower() == "dist":
        folders.append(os.path.dirname(here))
    return folders


# ----------------------------------------------------------------------
# Self-update via GitHub. On startup the app fetches a tiny
# version.json from the repo; if a newer version exists, a banner
# offers a one-click update: download the source files into the
# project folder, then a helper script rebuilds the exe once this
# app has closed and relaunches it. UPDATE_REPO is filled in once
# Ariya's repo exists; while it is empty the mechanism is fully off
# (no network calls at all).
# ----------------------------------------------------------------------
VERSION = "1.2.8"
UPDATE_REPO = "ariyast123/disk-cleaner"
UPDATE_FILES = ("disk_cleaner_app.py", "cleaner_core.py", "build.bat")


def parse_version(text):
    """'1.2.0' -> (1, 2); unparseable chunks count as 0. Trailing
    zeros are dropped so '1.1' and '1.1.0' compare equal."""
    parts = []
    for chunk in str(text).strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts) or (0,)


def fetch_update_info(repo, timeout=10):
    """Return {'version': ..., 'notes': ..., 'patch_notes': ...} from
    the repo, or None."""
    import json
    import urllib.request

    url = f"https://raw.githubusercontent.com/{repo}/main/version.json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict) and data.get("version"):
            return data
    except Exception:
        pass
    return None


def validate_update_files(files):
    """Every update file present and non-empty, and both Python
    sources compile - checked before anything on disk is touched."""
    if not files:
        return False
    for name in UPDATE_FILES:
        if not files.get(name):
            return False
    for name in ("disk_cleaner_app.py", "cleaner_core.py"):
        try:
            compile(files[name].decode("utf-8"), name, "exec")
        except Exception:
            return False
    return True


def download_update_files(repo, timeout=30):
    """Download the update files; return {name: bytes} or None."""
    import urllib.request

    files = {}
    try:
        for name in UPDATE_FILES:
            url = f"https://raw.githubusercontent.com/{repo}/main/{name}"
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                files[name] = resp.read()
    except Exception:
        return None
    return files if validate_update_files(files) else None


def apply_update_files(project_dir, files):
    """Write downloaded files into the project folder via temp names,
    so a failed write never leaves a half-written source file."""
    for name, data in files.items():
        tmp = os.path.join(project_dir, name + ".new")
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, os.path.join(project_dir, name))


# ----------------------------------------------------------------------
# What's New window: when an update is applied, the target version's
# patch notes are saved to ~/DiskCleaner/whats_new.json; on the next
# launch the running app shows them once in a small closable window
# and deletes the file, so the window appears exactly once.
# ----------------------------------------------------------------------
def whats_new_path():
    return os.path.join(os.path.expanduser("~"), "DiskCleaner",
                        "whats_new.json")


def save_whats_new(version, notes, path=None):
    """Save the patch notes for `version` to show once on next launch.
    Never raises: a failed save just means no What's New window."""
    try:
        target = path or whats_new_path()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump({"version": version, "notes": notes}, fh)
        return True
    except OSError:
        return False


def load_whats_new(path=None):
    """Return {'version': ..., 'notes': ...} or None when there is no
    valid pending note (missing file, bad JSON, empty notes)."""
    try:
        with open(path or whats_new_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    notes = data.get("notes")
    if not isinstance(version, str) or not version.strip():
        return None
    if not isinstance(notes, str) or not notes.strip():
        return None
    return {"version": version.strip(), "notes": notes.strip()}


def clear_whats_new(path=None):
    """Delete the pending note, if any. Never raises."""
    try:
        os.remove(path or whats_new_path())
    except OSError:
        pass


def show_whats_new_dialog(parent, version, notes):
    """Small closable window with the new version's patch notes."""
    win = ctk.CTkToplevel(parent)
    win.title(f"What's new in Disk Cleaner {version}")
    win.geometry("520x360")
    win.minsize(420, 280)
    win.transient(parent)
    ctk.CTkLabel(
        win, text=f"Disk Cleaner {version} - what's new",
        font=ctk.CTkFont(size=15, weight="bold"),
    ).pack(anchor="w", padx=16, pady=(14, 6))
    box = ctk.CTkTextbox(win, wrap="word")
    box.pack(fill="both", expand=True, padx=16, pady=(0, 10))
    box.insert("1.0", notes)
    box.configure(state="disabled")
    ctk.CTkButton(win, text="Close", width=120,
                  command=win.destroy).pack(pady=(0, 14))
    win.focus_set()
    return win


def project_folder():
    """The folder holding the .py sources and build.bat: when the exe
    sits in dist, that is the folder above it."""
    return own_folders()[-1]


def update_helper_lines(project, launched_exe):
    """The finish_update.bat body, kill-first design (Ariya's
    request, Nov 22, 2026): the helper does NOT wait politely for
    the app to close. Its first move is taskkill — every running
    copy of DiskCleaner.exe dies at once — then it verifies they
    are gone (a short capped loop; a copy that somehow survives
    is logged and the build proceeds anyway), rebuilds with
    `build.bat auto` (no pause — nobody is there to press a key)
    logging to update_build.log, copies the fresh exe back over
    the copy that was actually launched (a taskbar pin may point
    at a standalone copy outside dist) and relaunches THAT path.
    If the build failed, the old launched copy is relaunched
    instead of nothing."""
    built = os.path.join(project, "dist", "DiskCleaner.exe")
    return [
        "@echo off",
        "title Disk Cleaner update",
        f'cd /d "{project}"',
        "echo [helper] update started > update_build.log",
        "echo Disk Cleaner update: closing any running copies...",
        "taskkill /F /IM DiskCleaner.exe >> update_build.log 2>&1",
        "set /a WAITS=0",
        ":waitloop",
        'tasklist /FI "IMAGENAME eq DiskCleaner.exe" 2>NUL | '
        'find /I "DiskCleaner.exe" >NUL',
        "if errorlevel 1 goto allclosed",
        "set /a WAITS+=1",
        "if %WAITS% GEQ 10 goto proceed",
        "timeout /t 1 /nobreak >NUL",
        "goto waitloop",
        ":proceed",
        "echo [helper] a copy is still running - continuing "
        "anyway >> update_build.log",
        ":allclosed",
        "echo [helper] building >> update_build.log",
        "call build.bat auto >> update_build.log 2>&1",
        f'set "BUILT={built}"',
        f'set "LAUNCHED={launched_exe}"',
        'if exist "%BUILT%" (',
        '  if /I not "%BUILT%"=="%LAUNCHED%" copy /Y "%BUILT%" "%LAUNCHED%" >NUL',
        '  start "" "%LAUNCHED%"',
        ") else (",
        '  if exist "%LAUNCHED%" start "" "%LAUNCHED%"',
        ")",
        "echo [helper] relaunch issued >> update_build.log",
        "",
    ]


class DiskCleanerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Disk Cleaner")
        self.geometry("1240x800")
        self.minsize(1020, 640)
        self.configure(fg_color=C["bg"])

        self.cancel_event = threading.Event()
        # Worker threads never touch Tk directly (not thread-safe); they
        # post messages here and the main thread applies them.
        self.ui_queue = queue.Queue()
        self.scanning = False
        self.cleaning = False
        self._scan_total = 0  # file count from the pre-scan counting pass (0 = unknown)
        self.results = []            # list[core.FoundFile] from the last scan
        self.file_iids = {}          # tree iid -> FoundFile (current view)
        self.checked_paths = set()   # paths the user has ticked
        self.cat_iids = {}           # category -> parent iid (current view)
        self.custom_folders = []
        self._filter_after = None
        self.update_info = None
        self._whats_new_window = None
        self.biggest_running = False
        self.biggest_entries = []  # list[core.FolderSize] from the last run

        self._build_sidebar()
        self._build_main()
        self._update_drive_label()
        self.after(100, self._poll_queue)
        self.after(500, self._maybe_show_whats_new)
        if UPDATE_REPO:
            threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _poll_queue(self):
        """Apply worker-thread messages on the main thread, then reschedule."""
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                kind = msg[0]
                if kind == "counting":
                    self.status.configure(text="Counting files...")
                elif kind == "scan_total":
                    # The counting pass finished: switch the bar from its
                    # indeterminate stripe to a real percentage.
                    self._scan_total = msg[1]
                    if self._scan_total > 0:
                        self.progress.stop()
                        self.progress.configure(mode="determinate")
                        self.progress.set(0)
                        self.status.configure(
                            text="Scanning... 0 files checked (0%)"
                        )
                elif kind == "progress":
                    n = msg[1]
                    text = f"Scanning... {n} files checked"
                    if self._scan_total:
                        # Capped just below full: the count is an estimate
                        # (unreadable files, single-file caches), and the
                        # duplicate phase reports no progress, so 100%
                        # is only set when the scan actually finishes.
                        pct = min(n / self._scan_total, 0.99)
                        text += f" ({pct * 100:.0f}%)"
                        self.progress.set(pct)
                    self.status.configure(text=text)
                elif kind == "scan_done":
                    self._scan_done(msg[1], msg[2])
                elif kind == "clean_progress":
                    self.status.configure(
                        text=f"Cleaning... {msg[1]} of {msg[2]} files processed"
                    )
                elif kind == "clean_done":
                    self._clean_done(msg[1], msg[2], msg[3], msg[4], msg[5])
                elif kind == "update_available":
                    self._show_update_banner(msg[1])
                elif kind == "update_downloaded":
                    self._update_downloaded(msg[1])
                elif kind == "biggest_done":
                    self._show_biggest(msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # Self-update (GitHub): check on startup, banner, one-click apply.
    # ------------------------------------------------------------------
    def _maybe_show_whats_new(self):
        """Show the pending What's New note exactly once: the file is
        deleted as soon as it is read, and the window only appears
        when the note's version is the version now running."""
        info = load_whats_new()
        if info is None:
            return
        clear_whats_new()
        if info["version"] != VERSION:
            return
        try:
            self._whats_new_window = show_whats_new_dialog(
                self, info["version"], info["notes"])
        except Exception:
            pass

    def _check_update_worker(self):
        info = fetch_update_info(UPDATE_REPO)
        if info and parse_version(info["version"]) > parse_version(VERSION):
            self.ui_queue.put(("update_available", info))

    def _show_update_banner(self, info):
        self.update_info = info
        text = f"Update available: version {info['version']}"
        notes = (info.get("notes") or "").strip()
        if notes:
            text += f" - {notes}"
        self.update_label.configure(text=text)
        self.update_banner.pack(fill="x", padx=12, pady=(10, 0), before=self.tabs)

    def _start_update(self):
        if not self.update_info:
            return
        if not messagebox.askyesno(
            "Update Disk Cleaner",
            f"Download version {self.update_info['version']} and update?\n\n"
            "The new files go into the project folder. Disk Cleaner "
            "then closes itself, rebuilds and reopens on the new "
            "version - that takes about a minute, and you don't "
            "need to close anything yourself.",
        ):
            return
        self.update_banner.pack_forget()
        self.status.configure(text="Downloading update...")

        def worker():
            files = download_update_files(UPDATE_REPO)
            self.ui_queue.put(("update_downloaded", files))

        threading.Thread(target=worker, daemon=True).start()

    def _update_downloaded(self, files):
        if not files:
            self.status.configure(
                text="Update download failed - check your connection."
            )
            messagebox.showerror(
                "Update failed",
                "Could not download the update files. Nothing was changed.",
            )
            return
        try:
            apply_update_files(project_folder(), files)
        except OSError as exc:
            messagebox.showerror(
                "Update failed", f"Could not write the new files:\n{exc}"
            )
            return
        # Remember this version's patch notes so the next launch can
        # show them once in the What's New window.
        notes = (self.update_info.get("patch_notes") or "").strip()
        if notes:
            save_whats_new(self.update_info["version"], notes)
        if getattr(sys, "frozen", False):
            self._write_update_helper()
            self.status.configure(
                text="Updating - the app will close and reopen on "
                     "the new version."
            )
            # No dialog, no manual close (Ariya's rule): the helper
            # kills any copy still running, and this timer is the
            # backstop that guarantees this process exits.
            threading.Timer(1.0, os._exit, args=(0,)).start()
            try:
                self.destroy()
            except Exception:
                pass
        else:
            self.status.configure(text="Update ready - restart the app.")
            messagebox.showinfo(
                "Update ready",
                "The new files are in place. Restart the app to use the "
                "new version.",
            )

    def _write_update_helper(self):
        """Write finish_update.bat and hand it to Explorer: it closes
        this app to exit, rebuilds the exe and relaunches it."""
        project = project_folder()
        helper = os.path.join(project, "finish_update.bat")
        lines = update_helper_lines(project, sys.executable)
        with open(helper, "w", encoding="ascii") as fh:
            fh.write("\r\n".join(lines))
        # Hand the helper to Explorer instead of launching it
        # from this process. The batch's first job is to kill
        # THIS app, and on Ariya's PC a helper launched by the
        # app died along with it (Nov 22-23, 2026: the console
        # opened, closed, and nothing was rebuilt or
        # relaunched), while the very same file double-clicked
        # in Explorer always worked - a documented pattern: a
        # script that kills its launcher gets killed with it.
        # Explorer is a long-lived shell process, so a batch it
        # opens is completely independent of this app, exactly
        # like a manual double-click. The direct launch below is
        # only a fallback if Explorer cannot be started.
        try:
            subprocess.Popen(["explorer.exe", helper])
        except OSError:
            subprocess.Popen(
                ["cmd", "/c", helper],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )

    # ------------------------------------------------------------------
    # Sidebar: fixed header, scrollable settings, fixed action block.
    # The Scan button must stay visible at any window height.
    # ------------------------------------------------------------------
    def _section_label(self, parent, text, top=12):
        ctk.CTkLabel(
            parent, text=text, text_color=C["muted"],
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(top, 4))

    def _divider(self, parent):
        ctk.CTkFrame(parent, height=1, fg_color=C["border"]).pack(
            fill="x", padx=18, pady=(10, 2)
        )

    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, width=312, corner_radius=0, fg_color=C["panel"])
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)

        # --- fixed bottom action block (packed first so it never scrolls away)
        actions = ctk.CTkFrame(bar, fg_color="transparent")
        actions.pack(side="bottom", fill="x")
        self.scan_btn = ctk.CTkButton(
            actions, text="Scan", height=44, corner_radius=12,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=C["accent"], hover_color=C["accent_hover"],
            command=self._start_scan,
        )
        self.scan_btn.pack(fill="x", padx=20, pady=(10, 6))
        self.cancel_btn = ctk.CTkButton(
            actions, text="Cancel", height=30, corner_radius=8,
            fg_color="transparent", border_width=1, border_color=C["border"],
            text_color=C["text"], hover_color=C["panel2"],
            command=self._cancel, state="disabled",
        )
        self.cancel_btn.pack(fill="x", padx=20)
        self.progress = ctk.CTkProgressBar(
            actions, height=8, corner_radius=4, progress_color=C["accent"]
        )
        self.progress.pack(fill="x", padx=20, pady=(12, 4))
        self.progress.set(0)
        self.status = ctk.CTkLabel(
            actions, text="Pick folders, then press Scan.", text_color=C["muted"],
            font=ctk.CTkFont(size=12), wraplength=268, justify="left",
        )
        self.status.pack(anchor="w", padx=20, pady=(0, 12))

        # --- fixed header
        header = ctk.CTkFrame(bar, fg_color="transparent")
        header.pack(side="top", fill="x")
        ctk.CTkLabel(
            header, text="Disk Cleaner", font=ctk.CTkFont(size=24, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 0))
        ctk.CTkLabel(
            header, text="See what is eating your drive - clean it safely.",
            text_color=C["muted"], font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=20, pady=(0, 10))
        card = ctk.CTkFrame(header, fg_color=C["panel2"], corner_radius=10)
        card.pack(fill="x", padx=16, pady=(0, 2))
        self.drive_title = ctk.CTkLabel(
            card, text="Drive", font=ctk.CTkFont(size=13, weight="bold")
        )
        self.drive_title.pack(anchor="w", padx=14, pady=(9, 0))
        self.drive_bar = ctk.CTkProgressBar(
            card, height=8, corner_radius=4, progress_color=C["ok"]
        )
        self.drive_bar.pack(fill="x", padx=14, pady=(5, 2))
        self.drive_bar.set(0)
        self.drive_label = ctk.CTkLabel(
            card, text="", text_color=C["muted"], font=ctk.CTkFont(size=11)
        )
        self.drive_label.pack(anchor="w", padx=14, pady=(0, 9))

        # --- scrollable settings
        scroll = ctk.CTkScrollableFrame(
            bar, fg_color="transparent", scrollbar_button_color=C["panel2"],
            scrollbar_button_hover_color=C["border"],
        )
        scroll.pack(side="top", fill="both", expand=True)

        self._section_label(scroll, "SCAN LOCATIONS", top=8)
        self.folder_vars = {}
        for name in ("Downloads", "Desktop", "Documents", "Pictures", "Music", "Videos"):
            var = tk.BooleanVar(value=(name in ("Downloads", "Videos", "Documents")))
            self.folder_vars[name] = var
            ctk.CTkCheckBox(
                scroll, text=name, variable=var, fg_color=C["accent"],
                hover_color=C["accent_hover"], corner_radius=5, border_width=2,
            ).pack(anchor="w", padx=28, pady=2)
        ctk.CTkButton(
            scroll, text="Add a folder...", command=self._add_folder, width=170,
            fg_color="transparent", border_width=1, border_color=C["border"],
            text_color=C["text"], hover_color=C["panel2"], corner_radius=8,
        ).pack(anchor="w", padx=28, pady=(7, 2))
        self.custom_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.custom_frame.pack(fill="x", padx=28, pady=(2, 0))

        self._divider(scroll)
        self._section_label(scroll, "WHAT COUNTS AS JUNK", top=4)
        self.large_mb = self._labeled_entry(scroll, "Large file at least (MB)", "500")
        self.old_days = self._labeled_entry(scroll, "Unused for at least (days)", "180")
        self.installer_days = self._labeled_entry(scroll, "Old installers after (days)", "30")

        self._section_label(scroll, "INCLUDE")
        self.caches_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            scroll, text="Known app & game caches", variable=self.caches_var,
            fg_color=C["accent"], hover_color=C["accent_hover"],
            corner_radius=5, border_width=2,
        ).pack(anchor="w", padx=28, pady=2)
        self.dup_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            scroll, text="Find duplicate files (slower)", variable=self.dup_var,
            fg_color=C["accent"], hover_color=C["accent_hover"],
            corner_radius=5, border_width=2,
        ).pack(anchor="w", padx=28, pady=2)
        self.hogs_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            scroll, text="Report system space hogs", variable=self.hogs_var,
            fg_color=C["accent"], hover_color=C["accent_hover"],
            corner_radius=5, border_width=2,
        ).pack(anchor="w", padx=28, pady=2)
        self.full_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            scroll, text="Full system scan (Program Files, Windows)",
            variable=self.full_var,
            fg_color=C["warn"], hover_color=C["warn"],
            corner_radius=5, border_width=2,
        ).pack(anchor="w", padx=28, pady=(2, 10))

    def _labeled_entry(self, parent, label, default):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=28, pady=2)
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=12)).pack(side="left")
        entry = ctk.CTkEntry(
            row, width=66, corner_radius=8, border_color=C["border"],
            fg_color=C["panel2"], justify="center",
        )
        entry.insert(0, default)
        entry.pack(side="right")
        return entry

    def _update_drive_label(self):
        try:
            drive = os.environ.get("SystemDrive", "C:") + "\\"
            usage = shutil.disk_usage(drive)
        except OSError:
            self.drive_title.configure(text="Drive")
            self.drive_label.configure(text="Usage unavailable")
            return
        used_frac = (usage.total - usage.free) / usage.total if usage.total else 0
        self.drive_title.configure(text=f"Drive {drive}")
        self.drive_bar.set(used_frac)
        color = C["ok"] if used_frac < 0.75 else C["warn"] if used_frac < 0.9 else C["danger"]
        self.drive_bar.configure(progress_color=color)
        self.drive_label.configure(
            text=f"{core.human_size(usage.free)} free of {core.human_size(usage.total)}"
            f"  ({used_frac * 100:.0f}% used)"
        )

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder to scan")
        if not folder:
            return
        # The Windows folder picker returns C:/ style paths; store the
        # canonical C:\ spelling so the same folder is never added twice.
        folder = os.path.normpath(folder)
        if any(os.path.normcase(folder) == os.path.normcase(f) for f in self.custom_folders):
            return
        self.custom_folders.append(folder)
        self._refresh_custom_folders()

    def _remove_folder(self, folder):
        self.custom_folders = [f for f in self.custom_folders if f != folder]
        self._refresh_custom_folders()

    def _refresh_custom_folders(self):
        for child in self.custom_frame.winfo_children():
            child.destroy()
        if not self.custom_folders:
            return
        ctk.CTkLabel(
            self.custom_frame, text="Also scanning:", text_color=C["muted"],
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(4, 2))
        for folder in self.custom_folders:
            row = ctk.CTkFrame(self.custom_frame, fg_color=C["panel2"], corner_radius=6)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(
                row, text=folder, font=ctk.CTkFont(size=11),
                wraplength=185, justify="left",
            ).pack(side="left", padx=(8, 2), pady=4)
            ctk.CTkButton(
                row, text="✕", width=24, height=24, corner_radius=6,
                fg_color="transparent", hover_color=C["danger"],
                command=lambda f=folder: self._remove_folder(f),
            ).pack(side="right", padx=4)

    def _int_setting(self, entry, default):
        try:
            value = int(entry.get().strip())
            return value if value > 0 else default
        except ValueError:
            return default

    # ------------------------------------------------------------------
    # Main area
    # ------------------------------------------------------------------
    def _build_main(self):
        main = ctk.CTkFrame(self, corner_radius=0, fg_color=C["bg"])
        main.pack(side="right", fill="both", expand=True)

        # Update banner: built now, packed only when an update exists.
        self.update_banner = ctk.CTkFrame(
            main, fg_color=C["panel2"], corner_radius=8
        )
        self.update_label = ctk.CTkLabel(
            self.update_banner, text="",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.update_label.pack(side="left", padx=14, pady=8)
        ctk.CTkButton(
            self.update_banner, text="Update now", width=110,
            fg_color=C["accent"], hover_color=C["accent_hover"],
            command=self._start_update,
        ).pack(side="right", padx=(6, 8), pady=6)
        ctk.CTkButton(
            self.update_banner, text="✕", width=34,
            fg_color="transparent", hover_color=C["panel"],
            command=self.update_banner.pack_forget,
        ).pack(side="right", pady=6)

        self.tabs = ctk.CTkTabview(
            main, fg_color=C["bg"],
            segmented_button_fg_color=C["panel"],
            segmented_button_selected_color=C["accent"],
            segmented_button_selected_hover_color=C["accent_hover"],
            segmented_button_unselected_color=C["panel"],
            segmented_button_unselected_hover_color=C["panel2"],
            text_color=C["text"],
        )
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(10, 4))
        files_tab = self.tabs.add("Files to clean")
        hogs_tab = self.tabs.add("System space")
        folders_tab = self.tabs.add("Biggest folders")
        files_tab.configure(fg_color=C["bg"])
        hogs_tab.configure(fg_color=C["bg"])
        folders_tab.configure(fg_color=C["bg"])

        # Toolbar: filter + quick-select
        toolbar = ctk.CTkFrame(files_tab, fg_color="transparent")
        toolbar.pack(fill="x", pady=(2, 8))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", self._on_filter_change)
        filter_entry = ctk.CTkEntry(
            toolbar, textvariable=self.filter_var, width=280, corner_radius=8,
            border_color=C["border"], fg_color=C["panel"],
            placeholder_text="Filter files by name or path...",
        )
        filter_entry.pack(side="left")
        ctk.CTkButton(
            toolbar, text="Clear scan", width=88, height=30, corner_radius=8,
            fg_color="transparent", border_width=1, border_color=C["border"],
            text_color=C["text"], hover_color=C["panel2"],
            command=self._clear_scan,
        ).pack(side="right", padx=(6, 0))
        for label, cmd in (
            ("Safe junk", self._select_safe),
            ("All", self._select_all),
            ("None", self._select_none),
        ):
            ctk.CTkButton(
                toolbar, text=label, width=78, height=30, corner_radius=8,
                fg_color=C["panel2"], hover_color=C["border"], command=cmd,
            ).pack(side="right", padx=(6, 0))

        # Results tree
        tree_frame = ctk.CTkFrame(files_tab, fg_color=C["panel"], corner_radius=10)
        tree_frame.pack(fill="both", expand=True)
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Clean.Treeview",
            background=C["tree_b"],
            fieldbackground=C["tree_b"],
            foreground=C["text"],
            rowheight=25,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Clean.Treeview.Heading",
            background=C["panel2"], foreground=C["text"],
            font=("Segoe UI", 10, "bold"), borderwidth=0,
        )
        style.map("Clean.Treeview", background=[("selected", "#35507a")])
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("check", "path", "size", "modified", "note"),
            show="headings",
            style="Clean.Treeview",
            selectmode="browse",
        )
        self.tree.heading("check", text="")
        self.tree.heading("path", text="File")
        self.tree.heading("size", text="Size")
        self.tree.heading("modified", text="Modified")
        self.tree.heading("note", text="Note")
        self.tree.column("check", width=32, anchor="center", stretch=False)
        self.tree.column("path", width=430)
        self.tree.column("size", width=92, anchor="e", stretch=False)
        self.tree.column("modified", width=92, anchor="center", stretch=False)
        self.tree.column("note", width=300)
        self.tree.tag_configure("even", background=C["tree_b"])
        self.tree.tag_configure("odd", background=C["tree_a"])
        self.tree.tag_configure(
            "cat", background=C["tree_cat"], foreground="#ffffff",
            font=("Segoe UI", 10, "bold"),
        )
        yscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        yscroll.pack(side="right", fill="y", pady=6)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-Button-1>", self._on_tree_double_click)
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        self.empty_label = ctk.CTkLabel(
            tree_frame,
            text="No results yet.\nChoose folders on the left and press Scan.",
            text_color=C["muted"], font=ctk.CTkFont(size=14), justify="center",
        )
        self.empty_label.place(relx=0.5, rely=0.42, anchor="center")

        self.hogs_frame = ctk.CTkScrollableFrame(
            hogs_tab, fg_color=C["bg"], scrollbar_button_color=C["panel2"]
        )
        self.hogs_frame.pack(fill="both", expand=True)

        # Biggest-folders tab: which subfolders use the most space, so
        # he sees where it goes before scanning for individual files.
        top = ctk.CTkFrame(folders_tab, fg_color="transparent")
        top.pack(fill="x", pady=(2, 4))
        ctk.CTkLabel(
            top,
            text="Top folders by size in the folders you scan.",
            text_color=C["muted"], font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=6)
        self.biggest_btn = ctk.CTkButton(
            top, text="Find biggest folders", width=170, height=32,
            corner_radius=8, fg_color=C["accent"],
            hover_color=C["accent_hover"],
            command=self._find_biggest_folders,
        )
        self.biggest_btn.pack(side="right", padx=6)
        self.biggest_status = ctk.CTkLabel(
            folders_tab, text="", text_color=C["muted"],
            font=ctk.CTkFont(size=12), wraplength=800, justify="left",
        )
        self.biggest_status.pack(anchor="w", padx=6, pady=(0, 4))
        self.biggest_frame = ctk.CTkScrollableFrame(
            folders_tab, fg_color=C["bg"],
            scrollbar_button_color=C["panel2"],
        )
        self.biggest_frame.pack(fill="both", expand=True)

        footer = ctk.CTkFrame(main, fg_color="transparent")
        footer.pack(fill="x", padx=12, pady=(4, 12))
        self.selected_label = ctk.CTkLabel(
            footer, text="Selected: nothing", font=ctk.CTkFont(size=13)
        )
        self.selected_label.pack(side="left")
        self.clean_btn = ctk.CTkButton(
            footer,
            text="Move selected to Recycle Bin",
            height=40, corner_radius=10,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=C["danger"], hover_color=C["danger_hover"],
            command=self._clean_selected,
            state="normal" if SEND2TRASH_OK else "disabled",
        )
        self.clean_btn.pack(side="right")
        if not SEND2TRASH_OK:
            self.selected_label.configure(
                text="send2trash is missing - run:  pip install send2trash"
            )

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    def _scan_roots(self):
        """Ticked profile folders + added custom folders, de-duplicated."""
        roots = [profile_folder(n) for n, v in self.folder_vars.items() if v.get()]
        roots = [r for r in roots if os.path.isdir(r)] + list(self.custom_folders)
        return list({os.path.normcase(os.path.normpath(r)): r for r in roots}.values())

    def _start_scan(self):
        if self.scanning or self.cleaning:
            return
        roots = self._scan_roots()
        if not roots and not self.caches_var.get():
            messagebox.showinfo("Nothing to scan", "Tick at least one folder first.")
            return
        if self.full_var.get() and not messagebox.askyesno(
            "Full system scan",
            "This also scans inside Program Files, Program Files (x86), "
            "Windows and ProgramData.\n\n"
            "Files there belong to installed programs and to Windows itself. "
            "Deleting them can break those programs - only ever delete "
            "leftovers of programs you have already uninstalled.\n\n"
            "Critical system areas (System32, WinSxS, the Windows Installer "
            "cache, Package Cache and similar) are never listed, even in a "
            "full scan.\n\n"
            "Continue with the full scan?",
        ):
            return

        self.cancel_event.clear()
        self.scanning = True
        self.scan_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.clean_btn.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.status.configure(text="Scanning...")

        temp_dirs = []
        temp_env = os.environ.get("TEMP")
        if temp_env and os.path.isdir(temp_env):
            temp_dirs.append(temp_env)

        cache_targets = (
            core.default_cache_targets() if self.caches_var.get() else ()
        )
        protected = own_folders()
        include_system = self.full_var.get()
        args = dict(
            roots=roots,
            temp_dirs=temp_dirs,
            cache_targets=cache_targets,
            large_bytes=self._int_setting(self.large_mb, 500) * 1024 * 1024,
            old_days=self._int_setting(self.old_days, 180),
            installer_days=self._int_setting(self.installer_days, 30),
            find_duplicates=self.dup_var.get(),
            include_system=include_system,
            extra_protected=protected,
            progress=lambda n: self.ui_queue.put(("progress", n)),
            cancel_event=self.cancel_event,
        )
        want_hogs = self.hogs_var.get()

        def worker():
            # Quick counting pass first, so the bar can show a real
            # percentage instead of an indeterminate stripe.
            self.ui_queue.put(("counting",))
            total = core.count_files(
                roots=roots,
                temp_dirs=temp_dirs,
                cache_targets=cache_targets,
                include_system=include_system,
                extra_protected=protected,
                cancel_event=self.cancel_event,
            )
            self.ui_queue.put(("scan_total", total))
            found = core.scan(**args)
            hogs = core.system_hogs(self.cancel_event) if want_hogs else []
            self.ui_queue.put(("scan_done", found, hogs))

        threading.Thread(target=worker, daemon=True).start()

    def _cancel(self):
        self.cancel_event.set()
        self.status.configure(text="Cancelling...")

    def _scan_done(self, found, hogs):
        self.scanning = False
        self._scan_total = 0
        self.scan_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.clean_btn.configure(state="normal" if SEND2TRASH_OK else "disabled")
        self.progress.stop()
        self.progress.configure(mode="determinate")
        cancelled = self.cancel_event.is_set()
        self.progress.set(0 if cancelled else 1)
        self.results = found
        self.checked_paths = {f.path for f in found if f.pre_checked}
        self._populate_tree()
        self._show_hogs(hogs)
        total_size = sum(f.size for f in found)
        self.status.configure(
            text=(
                f"{'Cancelled. ' if cancelled else 'Done. '}"
                f"{len(found)} candidate files, {core.human_size(total_size)} total. "
                "Nothing has been deleted."
            )
        )
        self._update_drive_label()

    # ------------------------------------------------------------------
    # Tree population & selection (selection is stored by file path, so
    # it survives filtering and re-population)
    # ------------------------------------------------------------------
    def _on_filter_change(self, *_args):
        if self._filter_after is not None:
            self.after_cancel(self._filter_after)
        self._filter_after = self.after(250, self._populate_tree)

    def _visible_results(self):
        text = self.filter_var.get().strip().lower()
        if not text:
            return list(self.results)
        return [f for f in self.results if text in f.path.lower()]

    def _populate_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.file_iids.clear()
        self.cat_iids.clear()

        visible = self._visible_results()
        if not visible:
            if self.results:
                self.empty_label.configure(text="No files match your filter.")
            else:
                self.empty_label.configure(
                    text="No results yet.\nChoose folders on the left and press Scan."
                )
            self.empty_label.place(relx=0.5, rely=0.42, anchor="center")
        else:
            self.empty_label.place_forget()

        by_cat = {}
        for f in visible:
            by_cat.setdefault(f.category, []).append(f)
        ordered = sorted(
            by_cat.items(), key=lambda kv: sum(x.size for x in kv[1]), reverse=True
        )
        idx = 0
        parity = 0
        for category, files in ordered:
            total = sum(x.size for x in files)
            parent = self.tree.insert(
                "",
                "end",
                iid=f"cat{idx}",
                values=(
                    UNCHECKED,
                    f"{category}  ({len(files)} files)",
                    core.human_size(total),
                    "",
                    "",
                ),
                open=True,
                tags=("cat",),
            )
            idx += 1
            self.cat_iids[category] = parent
            for f in files:
                iid = f"f{idx}"
                idx += 1
                self.tree.insert(
                    parent,
                    "end",
                    iid=iid,
                    values=(
                        CHECKED if f.path in self.checked_paths else UNCHECKED,
                        f.path,
                        core.human_size(f.size),
                        datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d"),
                        f.note,
                    ),
                    tags=("even" if parity % 2 == 0 else "odd",),
                )
                parity += 1
                self.file_iids[iid] = f
            self._refresh_parent(parent)
        self._refresh_selected_label()

    def _refresh_parent(self, parent):
        children = self.tree.get_children(parent)
        if not children:
            return
        ticked = sum(
            1 for ch in children
            if ch in self.file_iids and self.file_iids[ch].path in self.checked_paths
        )
        glyph = CHECKED if ticked == len(children) else UNCHECKED
        values = list(self.tree.item(parent, "values"))
        values[0] = glyph
        self.tree.item(parent, values=values)

    def _refresh_selected_label(self):
        if not SEND2TRASH_OK:
            return
        total = sum(f.size for f in self.results if f.path in self.checked_paths)
        count = sum(1 for f in self.results if f.path in self.checked_paths)
        self.selected_label.configure(
            text=f"Selected: {count} files - {core.human_size(total)}"
        )

    def _set_checked(self, iid, value):
        f = self.file_iids.get(iid)
        if f is None:
            return
        if value:
            self.checked_paths.add(f.path)
        else:
            self.checked_paths.discard(f.path)
        values = list(self.tree.item(iid, "values"))
        values[0] = CHECKED if value else UNCHECKED
        self.tree.item(iid, values=values)

    def _on_tree_click(self, event):
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if iid in self.cat_iids.values():
            children = self.tree.get_children(iid)
            make_checked = not all(
                ch in self.file_iids and self.file_iids[ch].path in self.checked_paths
                for ch in children
            )
            for child in children:
                self._set_checked(child, make_checked)
            self._refresh_parent(iid)
        elif iid in self.file_iids:
            self._set_checked(iid, self.file_iids[iid].path not in self.checked_paths)
            self._refresh_parent(self.tree.parent(iid))
        self._refresh_selected_label()

    def _on_tree_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid in self.file_iids:
            self._open_file(self.file_iids[iid].path)

    def _on_tree_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid not in self.file_iids:
            return
        self.tree.selection_set(iid)
        path = self.file_iids[iid].path
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open file", command=lambda: self._open_file(path))
        menu.add_command(
            label="Show in Explorer", command=lambda: self._reveal_in_explorer(path)
        )
        menu.add_command(
            label="Open containing folder",
            command=lambda: self._open_folder(path),
        )
        menu.tk_popup(event.x_root, event.y_root)

    @staticmethod
    def _open_file(path):
        """Open the file itself with its default app (plays videos, etc.)."""
        try:
            os.startfile(path)  # Windows only
        except (OSError, AttributeError):
            pass

    @staticmethod
    def _open_folder(path):
        try:
            os.startfile(os.path.dirname(path))  # Windows only
        except (OSError, AttributeError):
            pass

    @staticmethod
    def _reveal_in_explorer(path):
        """Open Explorer with this exact file selected/highlighted."""
        try:
            subprocess.Popen(["explorer.exe", f"/select,{path}"])
        except OSError:
            pass

    def _clear_scan(self):
        """Throw away the current results so a fresh scan can start clean.

        Only clears the list - nothing on disk is touched."""
        if self.scanning or self.cleaning:
            return
        self.results = []
        self.checked_paths = set()
        self.filter_var.set("")
        self._populate_tree()
        self._show_hogs([])
        self.progress.set(0)
        self.status.configure(text="Cleared. Pick folders, then press Scan.")

    def _select_safe(self):
        self.checked_paths = {f.path for f in self.results if f.pre_checked}
        self._populate_tree()

    def _select_all(self):
        self.checked_paths = {f.path for f in self.results}
        self._populate_tree()

    def _select_none(self):
        self.checked_paths = set()
        self._populate_tree()

    # ------------------------------------------------------------------
    # System hogs tab
    # ------------------------------------------------------------------
    def _show_hogs(self, hogs):
        for child in self.hogs_frame.winfo_children():
            child.destroy()
        ctk.CTkLabel(
            self.hogs_frame,
            text="These are measured and explained only - the app never deletes "
            "system files itself. Each one names the safe, official way to "
            "reclaim its space.",
            text_color=C["muted"], wraplength=780, justify="left",
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=10, pady=(10, 6))
        if not hogs:
            ctk.CTkLabel(
                self.hogs_frame, text="No system space hogs found.",
                text_color=C["muted"], font=ctk.CTkFont(size=13),
            ).pack(anchor="w", padx=10, pady=8)
            return
        for hog in hogs:
            card = ctk.CTkFrame(self.hogs_frame, fg_color=C["panel"], corner_radius=10)
            card.pack(fill="x", padx=8, pady=5)
            accent = ctk.CTkFrame(card, width=4, fg_color=C["accent"], corner_radius=2)
            accent.pack(side="left", fill="y", padx=(8, 0), pady=10)
            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(side="left", fill="both", expand=True, padx=(10, 12), pady=10)
            size_text = core.human_size(hog.size) if hog.size >= 0 else "size varies"
            head = ctk.CTkFrame(body, fg_color="transparent")
            head.pack(fill="x")
            ctk.CTkLabel(
                head, text=hog.name, font=ctk.CTkFont(size=14, weight="bold")
            ).pack(side="left")
            ctk.CTkLabel(
                head, text=size_text, text_color=C["accent"],
                font=ctk.CTkFont(size=14, weight="bold"),
            ).pack(side="right")
            ctk.CTkLabel(
                body, text=hog.detail, text_color=C["muted"],
                wraplength=720, justify="left", font=ctk.CTkFont(size=12),
            ).pack(anchor="w", pady=(3, 6))
            if hog.action_label:
                ctk.CTkButton(
                    body, text=hog.action_label, width=200, height=30,
                    corner_radius=8, fg_color=C["panel2"],
                    hover_color=C["border"],
                    command=lambda h=hog: self._hog_action(h),
                ).pack(anchor="e")

    def _hog_action(self, hog):
        try:
            if hog.action_kind == "settings":
                os.startfile("ms-settings:storagesense")
            elif hog.action_kind == "cleanmgr":
                subprocess.Popen(["cleanmgr.exe"])
            elif hog.action_kind == "protection":
                subprocess.Popen(["SystemPropertiesProtection.exe"])
            elif hog.action_kind == "copy":
                self.clipboard_clear()
                self.clipboard_append(hog.command)
                self.status.configure(
                    text=f"Copied. Run in an admin terminal:  {hog.command}"
                )
            elif hog.action_kind == "empty_recycle":
                if messagebox.askyesno(
                    "Empty Recycle Bin",
                    "Empty the Recycle Bin on all drives? This is permanent.",
                ):
                    import ctypes

                    # SHEmptyRecycleBinW: 1=no confirm, 2=no progress UI, 4=no sound
                    ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
                    self.status.configure(text="Recycle Bin emptied.")
                    self._update_drive_label()
        except (OSError, AttributeError) as exc:
            messagebox.showerror("Could not open", str(exc))

    # ------------------------------------------------------------------
    # Biggest folders (report only - measuring, never deleting)
    # ------------------------------------------------------------------
    def _find_biggest_folders(self):
        if self.scanning or self.cleaning or self.biggest_running:
            return
        roots = self._scan_roots()
        if not roots:
            messagebox.showinfo("Nothing to scan", "Tick at least one folder first.")
            return
        self.biggest_running = True
        self.biggest_btn.configure(state="disabled")
        self.biggest_status.configure(text="Measuring folders...")
        protected = own_folders()
        include_system = self.full_var.get()

        def worker():
            entries = core.top_folders(
                roots, limit=10, include_system=include_system,
                extra_protected=protected)
            self.ui_queue.put(("biggest_done", entries))

        threading.Thread(target=worker, daemon=True).start()

    def _show_biggest(self, entries):
        self.biggest_running = False
        self.biggest_entries = entries
        self.biggest_btn.configure(state="normal")
        for child in self.biggest_frame.winfo_children():
            child.destroy()
        if not entries:
            self.biggest_status.configure(
                text="No subfolders with files found in the selected folders."
            )
            return
        total = sum(e.size for e in entries)
        top = entries[0].size
        self.biggest_status.configure(
            text=f"Top {len(entries)} folders by size - "
            f"{core.human_size(total)} in total. "
            "Sizes are measured only; nothing is deleted from here."
        )
        for entry in entries:
            card = ctk.CTkFrame(
                self.biggest_frame, fg_color=C["panel"], corner_radius=10
            )
            card.pack(fill="x", padx=8, pady=5)
            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=12, pady=(10, 0))
            ctk.CTkLabel(
                head, text=entry.path,
                font=ctk.CTkFont(size=13, weight="bold"),
            ).pack(side="left")
            ctk.CTkLabel(
                head, text=core.human_size(entry.size), text_color=C["accent"],
                font=ctk.CTkFont(size=13, weight="bold"),
            ).pack(side="right")
            sub = ctk.CTkFrame(card, fg_color="transparent")
            sub.pack(fill="x", padx=12, pady=(2, 10))
            bar = ctk.CTkProgressBar(
                sub, height=8, corner_radius=4, progress_color=C["accent"]
            )
            bar.pack(side="left", fill="x", expand=True, pady=2)
            bar.set(entry.size / top if top else 0)
            ctk.CTkLabel(
                sub, text=f"{entry.file_count} files", text_color=C["muted"],
                font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=(10, 0))
            ctk.CTkButton(
                sub, text="Open", width=64, height=26, corner_radius=8,
                fg_color=C["panel2"], hover_color=C["border"],
                command=lambda p=entry.path: self._open_directory(p),
            ).pack(side="right", padx=(10, 0))

    @staticmethod
    def _open_directory(path):
        """Open a folder itself in Explorer (Windows only)."""
        try:
            os.startfile(path)
        except (OSError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # Cleaning
    # ------------------------------------------------------------------
    def _clean_selected(self):
        targets = [f for f in self.results if f.path in self.checked_paths]
        if not targets:
            messagebox.showinfo("Nothing selected", "Tick at least one file first.")
            return
        total = sum(f.size for f in targets)
        if not messagebox.askyesno(
            "Move to Recycle Bin",
            f"Move {len(targets)} files ({core.human_size(total)}) to the Recycle Bin?\n\n"
            "You can restore them from the Recycle Bin afterwards. "
            "Files in use by a running app will be skipped.",
        ):
            return

        self.cancel_event.clear()
        self.cleaning = True
        self.clean_btn.configure(state="disabled")
        self.scan_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.status.configure(text=f"Cleaning... 0 of {len(targets)} files processed")

        def worker():
            sizes = {f.path: f.size for f in targets}
            log_lines = []

            def progress(done, total):
                if done % 200 == 0 or done == total:
                    self.ui_queue.put(("clean_progress", done, total))

            moved, failed, processed = core.recycle_files(
                [f.path for f in targets], trash_one=send2trash,
                cancel_event=self.cancel_event, progress_cb=progress)
            failed_map = dict(failed)
            for p in [f.path for f in targets][:processed]:
                if p in failed_map:
                    log_lines.append(f"SKIP  {p}  ({failed_map[p]})")
                else:
                    log_lines.append(f"OK    {p}")
            freed = sum(sizes[p] for p in [f.path for f in targets][:processed]
                        if p not in failed_map)
            self._write_log(log_lines)
            remaining = len(targets) - processed
            self.ui_queue.put(("clean_done", targets, moved, len(failed),
                               freed, remaining))

        threading.Thread(target=worker, daemon=True).start()

    def _write_log(self, lines):
        try:
            log_dir = os.path.join(os.path.expanduser("~"), "DiskCleaner")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "cleanup_log.txt")
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n=== {datetime.now().isoformat(timespec='seconds')} ===\n")
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass

    def _clean_done(self, targets, moved, failed, freed, remaining=0):
        self.cleaning = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.clean_btn.configure(state="normal" if SEND2TRASH_OK else "disabled")
        self.scan_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        # Drop files that are actually gone; keep the rest listed - and
        # keep their ticks, so a stopped clean can simply be resumed.
        gone = {f.path for f in targets if not os.path.exists(f.path)}
        self.results = [f for f in self.results if f.path not in gone]
        self.checked_paths -= gone
        self._populate_tree()
        text = (
            f"Moved {moved} files to the Recycle Bin ({core.human_size(freed)}). "
            f"Skipped {failed} (in use or no permission)."
        )
        if remaining:
            text += (
                f" Stopped early: {remaining} files were not processed - "
                "they are still listed and still ticked."
            )
        text += " Log: ~/DiskCleaner/cleanup_log.txt"
        self.status.configure(text=text)
        self._update_drive_label()


if __name__ == "__main__":
    app = DiskCleanerApp()
    app.mainloop()
