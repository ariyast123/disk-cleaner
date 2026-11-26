"""GameMode VPN — core engine (no GUI code in here).

Watches for Ariya's games and walks him through the Proton VPN
routine that replaces split tunneling on the free plan:

  game starts  ->  kill switch off, disconnect Proton  ->  play bare
  game closes  ->  reconnect Proton, kill switch back to Advanced

Why guided instead of fully automatic: Proton's Windows app has no
CLI and no documented API (the official CLI is Linux-only), and the
Advanced kill switch is a set of persistent Windows Filtering
Platform filters that only the Proton app itself may toggle. So
this core automates everything around those two clicks: process
detection, connection-state verification, the session state machine
and the step list — and the GUI performs the clicks with him.

All system access goes through small probe functions; the state
machine and the matchers take plain data, so tests inject fakes.
"""

import fnmatch
import json
import math
import os
import re
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_GAMES = [
    {"name": "Counter-Strike 2", "patterns": ["cs2.exe"], "enabled": True, "builtin": True},
    {"name": "Rust", "patterns": ["rustclient.exe"], "enabled": True, "builtin": True},
    {"name": "FiveM / GTA V", "patterns": ["fivem*.exe", "gta5.exe"], "enabled": True, "builtin": True},
    {"name": "Overwatch", "patterns": ["overwatch.exe"], "enabled": True, "builtin": True},
]

PROTON_EXE_CANDIDATES = [
    r"C:\Program Files\Proton\VPN\ProtonVPN.exe",
    r"C:\Program Files (x86)\Proton\VPN\ProtonVPN.exe",
    r"C:\Program Files\Proton Technologies\ProtonVPN\ProtonVPN.exe",
    r"C:\Program Files (x86)\Proton Technologies\ProtonVPN\ProtonVPN.exe",
]

VPN_STATES = ("protected", "bare", "blocked", "unknown")


def default_settings():
    return {
        "games": [dict(g) for g in DEFAULT_GAMES],
        "poll_seconds": 2.0,
        "gone_debounce_seconds": 10.0,
        "auto_launch_proton": True,
        "auto_mode": True,          # click Proton's buttons via UI Automation
        "minimize_to_tray": True,   # closing the window hides to the tray
        "kill_switch_seen": None,   # learned: True / False / None (unknown)
        "adapter_keywords": ["proton"],
        "proton_path": "",          # "" = auto-detect
        "start_with_windows": False,
        "ping_proof": False,        # measure the real ping once Game Mode is on
        "ping_host": "8.8.8.8",     # host the ping contacts (only when ping_proof)
    }


def data_dir():
    """Per-user data folder: settings + log live here, never next to the exe."""
    return os.path.join(os.path.expanduser("~"), "GameModeVPN")


def settings_path():
    return os.path.join(data_dir(), "settings.json")


def log_path():
    return os.path.join(data_dir(), "gamemode.log")


def history_path():
    return os.path.join(data_dir(), "history.json")


# ---------------------------------------------------------------------------
# Session history: one record per finished game session, newest last,
# capped so the file can never grow without bound. A corrupt or
# foreign file degrades to an empty list, never an exception.
# ---------------------------------------------------------------------------

HISTORY_MAX_ENTRIES = 50


def _clean_history_entry(entry):
    if not isinstance(entry, dict):
        return None
    games = entry.get("games")
    if not isinstance(games, list):
        return None
    names = [str(g).strip() for g in games if str(g).strip()]
    if not names:
        return None
    try:
        duration = int(entry.get("duration_seconds") or 0)
        game_mode = int(entry.get("game_mode_seconds") or 0)
    except (TypeError, ValueError):
        return None
    cleaned = {
        "games": names,
        "started_at": str(entry.get("started_at", "")),
        "duration_seconds": max(0, duration),
        "game_mode_seconds": max(0, game_mode),
        "game_mode_on": bool(entry.get("game_mode_on", False)),
        "was_protected": bool(entry.get("was_protected", False)),
        "restore_needed": bool(entry.get("restore_needed", False)),
        "peak_state": str(entry.get("peak_state", "unknown")),
    }
    # Ping proof is optional and new: keep the key only when a real
    # measurement was recorded, so older records round-trip unchanged.
    ping_ms = entry.get("ping_ms")
    if ping_ms is not None:
        try:
            ping_ms = max(0, int(ping_ms))
        except (TypeError, ValueError):
            ping_ms = None
        if ping_ms is not None:
            cleaned["ping_ms"] = ping_ms
    return cleaned


def load_history(path=None):
    path = path or history_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    cleaned = []
    for entry in data:
        item = _clean_history_entry(entry)
        if item is not None:
            cleaned.append(item)
    return cleaned


def append_history(record, path=None, max_entries=HISTORY_MAX_ENTRIES):
    """Append one session record, capped at max_entries (oldest drop
    first). Atomic tmp+replace write; False when the file cannot be
    written — the caller logs nothing, history is never load-bearing."""
    entry = _clean_history_entry(record)
    if entry is None:
        return False
    path = path or history_path()
    entries = load_history(path)
    entries.append(entry)
    entries = entries[-max(1, int(max_entries)):]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(entries, handle, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Settings: load / save / normalize
# ---------------------------------------------------------------------------

def _clamp(value, low, high, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
DEFAULT_PING_HOST = "8.8.8.8"


def clean_ping_host(value):
    """A safe ping target: a hostname or an IPv4 address, nothing
    else. Anything odd (spaces, slashes, shell metacharacters,
    empty) falls back to the default — the host is passed straight
    to the ping command, so it must never carry an injection."""
    host = str(value or "").strip()
    if not host or ".." in host or not _HOST_RE.match(host):
        return DEFAULT_PING_HOST
    return host


def normalize_settings(raw):
    """Merge user data over the defaults and validate every field."""
    settings = default_settings()
    if not isinstance(raw, dict):
        return settings
    settings["poll_seconds"] = _clamp(raw.get("poll_seconds"), 1.0, 10.0, settings["poll_seconds"])
    settings["gone_debounce_seconds"] = _clamp(
        raw.get("gone_debounce_seconds"), 0.0, 120.0, settings["gone_debounce_seconds"])
    settings["auto_launch_proton"] = bool(raw.get("auto_launch_proton", True))
    settings["auto_mode"] = bool(raw.get("auto_mode", True))
    settings["minimize_to_tray"] = bool(raw.get("minimize_to_tray", True))
    if raw.get("kill_switch_seen") in (True, False):
        settings["kill_switch_seen"] = raw["kill_switch_seen"]
    settings["start_with_windows"] = bool(raw.get("start_with_windows", False))
    settings["ping_proof"] = bool(raw.get("ping_proof", False))
    settings["ping_host"] = clean_ping_host(raw.get("ping_host"))
    if isinstance(raw.get("proton_path"), str):
        settings["proton_path"] = raw["proton_path"].strip()
    keywords = raw.get("adapter_keywords")
    if isinstance(keywords, list):
        cleaned = [str(k).strip().lower() for k in keywords if str(k).strip()]
        if cleaned:
            settings["adapter_keywords"] = cleaned
    games = raw.get("games")
    if isinstance(games, list):
        cleaned_games = []
        seen = set()
        for entry in games:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            patterns = entry.get("patterns")
            if not name or name.lower() in seen or not isinstance(patterns, list):
                continue
            pats = [str(p).strip().lower() for p in patterns if str(p).strip()]
            if not pats:
                continue
            seen.add(name.lower())
            cleaned_games.append({
                "name": name,
                "patterns": pats,
                "enabled": bool(entry.get("enabled", True)),
                "builtin": bool(entry.get("builtin", False)),
            })
        if cleaned_games:
            settings["games"] = cleaned_games
    return settings


def load_settings(path=None):
    path = path or settings_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return normalize_settings(json.load(handle))
    except (OSError, ValueError):
        return default_settings()


def save_settings(settings, path=None):
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(normalize_settings(settings), handle, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Game process matching
# ---------------------------------------------------------------------------

_pattern_cache = {}


def _compiled_pattern(pattern):
    """fnmatch.translate + re.compile, cached per pattern string."""
    regex = _pattern_cache.get(pattern)
    if regex is None:
        regex = re.compile(fnmatch.translate(pattern))
        if len(_pattern_cache) > 512:
            _pattern_cache.clear()
        _pattern_cache[pattern] = regex
    return regex


def match_games(process_names, games):
    """Return the set of enabled game names whose patterns match a process."""
    lowered = {str(p).lower() for p in process_names if p}
    running = set()
    for game in games:
        if not game.get("enabled", True):
            continue
        for pattern in game.get("patterns", []):
            regex = _compiled_pattern(str(pattern).lower())
            if any(regex.match(name) for name in lowered):
                running.add(game["name"])
                break
    return running


# ---------------------------------------------------------------------------
# Connection-state inference
# ---------------------------------------------------------------------------

def detect_vpn_state(ifaces, gateway, gateway_reachable, adapter_keywords=("proton",)):
    """Classify the connection from plain observations.

    ifaces: {interface_name: is_up}; gateway: default gateway IP or None;
    gateway_reachable: True/False, or None when it was not probed.

    protected — a Proton tunnel adapter is up.
    bare      — no tunnel, but the LAN gateway answers: plain internet works,
                so the kill switch is not blocking (off or standard).
    blocked   — no tunnel and the gateway does not answer: the Advanced
                kill switch's persistent filters are blocking everything.
    unknown   — not enough information to tell.
    """
    keywords = [str(k).lower() for k in adapter_keywords if str(k).strip()] or ["proton"]
    for name, is_up in (ifaces or {}).items():
        if is_up and any(k in str(name).lower() for k in keywords):
            return "protected"
    if gateway is None or gateway_reachable is None:
        return "unknown"
    return "bare" if gateway_reachable else "blocked"


# ---------------------------------------------------------------------------
# System probes (Windows-first, every failure degrades to "unknown")
# ---------------------------------------------------------------------------

def running_process_names():
    """Names of running processes, via psutil when available, else tasklist."""
    try:
        import psutil
        names = []
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info.get("name")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if name:
                names.append(name)
        return names
    except ImportError:
        pass
    try:
        out = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        names = []
        for line in out.splitlines():
            parts = line.split('","')
            if parts:
                names.append(parts[0].strip(' "'))
        return names
    except (OSError, subprocess.SubprocessError):
        return []


def interface_states():
    """{interface_name: is_up} via psutil; {} when unavailable."""
    try:
        import psutil
        return {name: bool(stats.isup) for name, stats in psutil.net_if_stats().items()}
    except (ImportError, OSError):
        return {}


def default_gateway():
    """Default IPv4 gateway from `route print`, or None."""
    try:
        out = subprocess.run(
            ["route", "print", "-4"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "0.0.0.0" and fields[1] == "0.0.0.0":
            gateway = fields[2]
            if gateway.count(".") == 3:
                return gateway
    return None


def ping_host(host, timeout_ms=700, attempts=2):
    """One ICMP echo to a LAN host; True/False, None when ping cannot run.

    A single dropped echo is common (home routers rate-limit ICMP, a
    Wi-Fi hiccup), and one lost packet used to flip the app to
    "blocked" for a whole poll tick — a false kill-switch warning and
    a spurious blocked_midway event. So a no-reply is retried once
    before it counts as unreachable. An echo that answers on the
    first try costs nothing extra; the retry only runs on the failure
    path, inside the background watcher thread. When ping cannot run
    at all the answer stays None (unknown), never a guess, and is
    not retried — retrying a missing binary would prove nothing."""
    if not host:
        return None
    attempts = max(1, int(attempts))
    for _ in range(attempts):
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", str(timeout_ms), host],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode == 0:
            return True
    return False


# ---------------------------------------------------------------------------
# Ping proof: the average round-trip to a chosen host, measured once
# Game Mode is on, so the improvement is visible instead of claimed.
# Off by default (it contacts the host). A host that does not answer
# is reported as None — never a guess, never a stale number.
# ---------------------------------------------------------------------------

def parse_ping_output(text):
    """Average round-trip ms from ping output, or None.

    Windows: 'Average = 12ms' ('Average = <1ms' -> 0).
    Linux:   'rtt min/avg/max/mdev = 0.123/12.345/20.0/1.2 ms'.
    A run with no replies (or no output at all) has no average
    line, so it is None."""
    if not text:
        return None
    match = re.search(r"Average\s*=\s*(<?)(\d+)\s*ms", text)
    if match:
        # "Average = <1ms" means sub-millisecond: report 0, not 1
        return 0 if match.group(1) == "<" else int(match.group(2))
    match = re.search(
        r"rtt min/avg/max/mdev\s*=\s*[\d.]+/([\d.]+)/[\d.]+/[\d.]+\s*ms", text)
    if match:
        try:
            return int(round(float(match.group(1))))
        except ValueError:
            return None
    return None


def measure_ping(host, count=3, timeout_ms=1000):
    """Average ping to `host` in ms, or None when the host does not
    answer / ping cannot run. Sends `count` echoes; the average
    smooths a single slow packet. A host that fails validation is
    refused (None) — the probe never pings a different host than
    the one it was asked for. Never raises."""
    host = str(host or "").strip()
    if not host or ".." in host or not _HOST_RE.match(host):
        return None
    count = max(1, int(count))
    if sys.platform == "win32":
        cmd = ["ping", "-n", str(count), "-w",
               str(max(1, int(timeout_ms))), host]
    else:
        cmd = ["ping", "-c", str(count), "-W",
               str(max(1, math.ceil(timeout_ms / 1000.0))), host]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return parse_ping_output(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return None


PROTON_BASE_DIRS = [
    r"C:\Program Files\Proton\VPN",
    r"C:\Program Files (x86)\Proton\VPN",
]

# Proton 5.x installs into a versioned folder (e.g. VPN\v5.1.10) and
# the main executable is ProtonVPN.Client.exe; older versions used a
# flat ProtonVPN.exe. Both names are searched, newest version wins.
PROTON_EXE_NAMES = ("ProtonVPN.Client.exe", "ProtonVPN.exe")


def _version_key(folder_name):
    """'v5.1.10' -> (5, 1, 10); unparseable -> (-1,)."""
    text = folder_name.strip().lower().lstrip("v")
    parts = []
    for chunk in text.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            return (-1,)
        parts.append(int(digits))
    return tuple(parts) or (-1,)


def find_proton_exe(settings=None, bases=None, winreg_module=None):
    """Locate the Proton client: settings override first, then the
    versioned install folders (newest version wins), then flat paths,
    then the Add/Remove Programs registry keys as a last resort."""
    override = (settings or {}).get("proton_path", "")
    if override and os.path.isfile(override):
        return override
    best = None  # (version_key, -name_rank, path)
    for base in (PROTON_BASE_DIRS if bases is None else bases):
        try:
            entries = os.listdir(base)
        except OSError:
            entries = []
        folders = [("", base)] + [(name, os.path.join(base, name)) for name in entries
                                  if _version_key(name) != (-1,)]
        for folder_name, folder in folders:
            for rank, exe_name in enumerate(PROTON_EXE_NAMES):
                path = os.path.join(folder, exe_name)
                if os.path.isfile(path):
                    key = (_version_key(folder_name) if folder_name else (0,), -rank)
                    if best is None or key > best[0]:
                        best = (key, path)
    if best is not None:
        return best[1]
    for candidate in PROTON_EXE_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return find_proton_exe_via_uninstall_key(winreg_module)


# Registry fallback for Proton's location: if a future Proton update
# changes the install layout so the folder scan above finds nothing,
# the uninstall entry still names the real install folder. Read-only,
# Windows-only, and it never guesses — a path is returned only when
# the exe file really exists there. Any registry problem degrades to
# None, and non-Windows platforms (no winreg) always return None.
_UNINSTALL_KEY_PATHS = (
    ("HKEY_LOCAL_MACHINE",
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKEY_LOCAL_MACHINE",
     r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKEY_CURRENT_USER",
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)


def _folder_from_registry_value(raw):
    """Turn an InstallLocation / DisplayIcon / UninstallString value
    into the install folder: a folder stays a folder, a file yields
    its folder (DisplayIcon may carry an ',0' icon index)."""
    if not isinstance(raw, str):
        return None
    text = raw.strip().strip('"').strip()
    if "," in text:
        head, _, tail = text.rpartition(",")
        if tail.strip().isdigit():
            text = head.strip().strip('"').strip()
    if not text:
        return None
    if os.path.isfile(text):
        return os.path.dirname(text)
    if os.path.isdir(text):
        return text
    return None


def _registry_install_dirs(winreg_module):
    """Yield install folders claimed by Proton VPN uninstall entries.

    Only entries whose DisplayName names Proton VPN count; anything
    else is skipped, so another app's folder can never be mistaken
    for Proton's. Never raises.
    """
    for hive_name, subkey in _UNINSTALL_KEY_PATHS:
        try:
            hive = getattr(winreg_module, hive_name)
            key = winreg_module.OpenKey(hive, subkey)
        except (OSError, AttributeError, ValueError):
            continue
        try:
            index = 0
            while True:
                try:
                    name = winreg_module.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                try:
                    sub = winreg_module.OpenKey(key, name)
                except OSError:
                    continue
                try:
                    try:
                        display, _ = winreg_module.QueryValueEx(sub, "DisplayName")
                    except OSError:
                        display = ""
                    if (isinstance(display, str)
                            and "proton" in display.lower()
                            and "vpn" in display.lower()):
                        for value_name in ("InstallLocation", "DisplayIcon",
                                           "UninstallString"):
                            try:
                                raw, _ = winreg_module.QueryValueEx(sub, value_name)
                            except OSError:
                                continue
                            folder = _folder_from_registry_value(raw)
                            if folder:
                                yield folder
                finally:
                    try:
                        winreg_module.CloseKey(sub)
                    except OSError:
                        pass
        finally:
            try:
                winreg_module.CloseKey(key)
            except OSError:
                pass


def _scan_proton_install_folder(folder):
    """Best Proton exe in a folder: flat first, then its versioned
    subfolders, newest version first, Client name first."""
    for exe_name in PROTON_EXE_NAMES:
        path = os.path.join(folder, exe_name)
        if os.path.isfile(path):
            return path
    try:
        entries = os.listdir(folder)
    except OSError:
        return None
    versioned = sorted(
        (name for name in entries if _version_key(name) != (-1,)),
        key=_version_key, reverse=True)
    for name in versioned:
        for exe_name in PROTON_EXE_NAMES:
            path = os.path.join(folder, name, exe_name)
            if os.path.isfile(path):
                return path
    return None


def find_proton_exe_via_uninstall_key(winreg_module=None):
    """Last-resort Proton lookup through the uninstall registry keys.
    Pass a fake winreg module in tests; on real Windows the module is
    imported lazily. Returns an existing exe path, or None."""
    if winreg_module is None:
        try:
            import winreg as winreg_module
        except ImportError:
            return None
    try:
        folders = _registry_install_dirs(winreg_module)
        for folder in folders:
            found = _scan_proton_install_folder(folder)
            if found:
                return found
    except Exception:
        return None
    return None


def launch_proton(settings=None):
    """Start the Proton app (or bring it to the front). Returns the path used."""
    path = find_proton_exe(settings)
    if not path:
        return None
    try:
        subprocess.Popen([path], close_fds=True)
    except OSError:
        return None
    return path


# ---------------------------------------------------------------------------
# Proton auto control via UI Automation
#
# Proton's Windows app has no CLI/API, and its tunnel is held by a
# Windows service, so closing the app window does NOT disconnect the
# VPN. The one clean way to work the app itself is UI Automation —
# the same accessibility layer screen readers use: find Proton's own
# Disconnect / Connect button and invoke it, exactly like a click.
# Every failure returns (False, reason) so the caller can fall back
# to the guided steps; this layer never raises and never guesses.
# ---------------------------------------------------------------------------

AUTO_BUTTONS = {
    "disconnect": ("Disconnect",),
    "connect": ("Quick Connect", "Connect"),
}

PROTON_PROCESS_NAMES = ("protonvpn.client.exe", "protonvpn.exe")


class _PywinautoBackend:
    """Real backend over pywinauto's UIA tree (imported lazily)."""

    def __init__(self):
        from pywinauto import Application  # ImportError if unavailable
        self._application_cls = Application

    def window(self, timeout=12.0):
        import psutil

        deadline = time.monotonic() + timeout
        while True:
            pid = None
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if (proc.info.get("name") or "").lower() in PROTON_PROCESS_NAMES:
                        pid = proc.info["pid"]
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            if pid is not None:
                try:
                    app = self._application_cls(backend="uia").connect(
                        process=pid, timeout=5)
                    win = _pick_main_window(app.windows())
                    if win is not None:
                        # A minimized or tray-hidden main window
                        # exposes no clickable buttons; surface it.
                        try:
                            if not win.is_visible():
                                win.restore()
                        except Exception:
                            pass
                        return win
                except Exception:
                    pass
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)

    def buttons(self, window):
        """(name, control, control_type) for every named control in
        the window: real Buttons first, then everything else —
        Proton's Avalonia tree does not always expose its buttons
        with the Button control type."""
        found = []
        seen_ids = set()

        def collect(controls):
            for ctrl in controls:
                try:
                    if id(ctrl) in seen_ids:
                        continue
                    seen_ids.add(id(ctrl))
                    name = ctrl.window_text() or ""
                    if name.strip():
                        ctype = ctrl.element_info.control_type or ""
                        found.append((name, ctrl, ctype))
                except Exception:
                    continue

        try:
            collect(window.descendants(control_type="Button"))
        except Exception:
            pass
        try:
            collect(window.descendants())
        except Exception:
            pass
        return found

    def invoke(self, control):
        try:
            control.invoke()
        except Exception:
            control.click_input()

    def close_window(self, window):
        """Close Proton's window — the X button, not the app.
        Proton keeps running in the tray and its service holds the
        tunnel state; the window is only the UI. If closing is
        refused, minimizing is the fallback."""
        try:
            window.close()
        except Exception:
            window.minimize()


def _pick_button(buttons, wanted_names):
    """Exact (case-insensitive) name match wins — 'Connect' must
    never match the 'Disconnect' button, so substring matching is
    banned. Controls of type Button are preferred; any other type
    with the exact name is accepted as a fallback, because Proton's
    Avalonia tree does not always type its buttons as Buttons."""
    cleaned = [(name.strip(), ctrl, ctype) for name, ctrl, ctype in buttons
               if name and name.strip()]
    for wanted in wanted_names:
        for name, ctrl, ctype in cleaned:
            if name.lower() == wanted.lower() and ctype == "Button":
                return name, ctrl
    for wanted in wanted_names:
        for name, ctrl, ctype in cleaned:
            if name.lower() == wanted.lower():
                return name, ctrl
    return None, None


def _pick_main_window(windows):
    """Proton's process owns several top-level windows (the main
    UI, popups, notification shells); the main window is the one
    exposing the most controls. top_window() proved unreliable on
    Ariya's machine: it handed back a window with no usable
    buttons while Proton's real window sat hidden, and the first
    restore attempt failed with 'window was not found'. Pure
    selection over duck-typed windows so tests can drive it."""
    best = None
    best_count = -1
    for win in windows or []:
        try:
            count = len(win.descendants())
        except Exception:
            count = 0
        if count > best_count:
            best, best_count = win, count
    return best


def auto_proton_action(action, backend=None, timeout=25.0):
    """Click Proton's own button for `action` ('disconnect'/'connect').

    The window and its controls are re-scanned until the timeout:
    Proton may still be starting when the first scan runs, and its
    button only appears once the UI has loaded. Returns
    (ok, detail); ok=False always carries the reason — including
    the control names that WERE seen — and the caller falls back
    to the guided steps. Auto mode is an accelerator, never a
    single point of failure."""
    wanted = AUTO_BUTTONS.get(action)
    if not wanted:
        return (False, f"unknown action {action!r}")
    if backend is None:
        try:
            backend = _PywinautoBackend()
        except Exception as exc:
            return (False, f"auto control unavailable ({type(exc).__name__})")
    deadline = time.monotonic() + timeout
    win_seen = False
    saw_names = []
    while True:
        try:
            win = backend.window(timeout=2.0)
        except Exception as exc:
            return (False, f"could not reach Proton's window ({type(exc).__name__})")
        if win is not None:
            win_seen = True
            try:
                buttons = backend.buttons(win)
            except Exception as exc:
                return (False, f"could not read Proton's controls ({type(exc).__name__})")
            names = [name.strip() for name, _ctrl, _ctype in buttons
                     if name and name.strip()]
            if names:
                saw_names = names
            name, ctrl = _pick_button(buttons, wanted)
            if ctrl is not None:
                try:
                    backend.invoke(ctrl)
                except Exception as exc:
                    return (False, f"clicking {name} failed ({type(exc).__name__})")
                # The click is delivered. Give Proton a beat to
                # register it, then close its window again: Ariya
                # wants Proton's UI to flash for a moment only and
                # never linger next to the game. Closing is cosmetic
                # (the tunnel state lives in Proton's service), so
                # it must never fail a click that already worked.
                time.sleep(0.5)
                close_window = getattr(backend, "close_window", None)
                if close_window is not None:
                    try:
                        close_window(win)
                    except Exception:
                        pass
                return (True, f"clicked {name} in Proton")
        if time.monotonic() >= deadline:
            break
        time.sleep(0.7)
    if not win_seen:
        return (False, "Proton's window was not found")
    if saw_names:
        shown = ", ".join(sorted(set(saw_names))[:12])
        return (False, f"the {wanted[0]} button was not found in Proton (saw: {shown})")
    return (False, f"the {wanted[0]} button was not found in Proton "
                   "(no named controls were visible)")


class SnapshotCache:
    """The gateway rarely changes; probing `route print` every poll is waste."""

    def __init__(self, gateway_ttl=20.0):
        self.gateway_ttl = gateway_ttl
        self._gateway = None
        self._gateway_at = -1e18

    def gateway(self, now):
        if now - self._gateway_at >= self.gateway_ttl:
            self._gateway = default_gateway()
            self._gateway_at = now
        return self._gateway


def collect_snapshot(settings, cache, now=None):
    """One observation round: (running_games:set, vpn_state:str)."""
    now = time.monotonic() if now is None else now
    names = running_process_names()
    running = match_games(names, settings["games"])
    ifaces = interface_states()
    state = detect_vpn_state(ifaces, None, None, settings["adapter_keywords"])
    if state != "protected":
        gateway = cache.gateway(now)
        reachable = ping_host(gateway) if gateway else None
        state = detect_vpn_state(ifaces, gateway, reachable, settings["adapter_keywords"])
    return running, state


# ---------------------------------------------------------------------------
# Self-update helpers (GitHub channel, same design as Disk Cleaner)
# ---------------------------------------------------------------------------

UPDATE_FILES = ("gamemode_vpn_app.py", "gamemode_core.py", "build.bat", "gamemode_icon.ico")
UPDATE_PY_SOURCES = ("gamemode_vpn_app.py", "gamemode_core.py")


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


def validate_update_files(files):
    """Every update file present and non-empty, and both Python
    sources compile — checked before anything on disk is touched."""
    if not files:
        return False
    for name in UPDATE_FILES:
        if not files.get(name):
            return False
    for name in UPDATE_PY_SOURCES:
        try:
            compile(files[name].decode("utf-8"), name, "exec")
        except Exception:
            return False
    return True


def whats_new_path(directory=None):
    return os.path.join(directory or data_dir(), "whats_new.json")


def save_whats_new(info, directory=None):
    """Remember the incoming version + patch notes so the new build
    can show them once, right after the update lands."""
    notes = info.get("patch_notes") or ""
    if isinstance(notes, list):
        notes = "\n".join(str(line) for line in notes)
    payload = {"version": str(info.get("version", "")), "patch_notes": str(notes)}
    path = whats_new_path(directory)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except OSError:
        pass


def pop_whats_new(current_version, directory=None):
    """Return the saved {'version', 'patch_notes'} if it matches the
    running version, else None. The file is always removed once read,
    so the notes show exactly once and a stale file cannot stick."""
    path = whats_new_path(directory)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    try:
        os.remove(path)
    except OSError:
        pass
    if not isinstance(data, dict):
        return None
    if parse_version(data.get("version", "")) != parse_version(current_version):
        return None
    return data


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_line(text, path=None, stamp=None):
    path = path or log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        stamp = stamp or time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {text}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# The session state machine
# ---------------------------------------------------------------------------

class Engine:
    """Turns (games running, vpn state) observations into modes and events.

    Modes:
      idle           — no game; nothing to do.
      action_needed  — a game is up but the VPN is not bare yet.
      gaming         — a game is up and the connection is bare. Session live.
      restore_needed — the game closed and the VPN was on before; restore it.

    Events are short strings the GUI logs and reacts to; update() returns
    the events produced by that observation round.
    """

    def __init__(self, settings, now=time.monotonic):
        self.settings = settings
        self._now = now
        self.mode = "idle"
        self.vpn_state = "unknown"
        self.active_games = set()
        self.was_protected = False
        self.session_start = None
        self.session_start_wall = None  # wall-clock "YYYY-MM-DD HH:MM" for history
        self.session_games = set()
        self.session_ping_ms = None  # ping proof measured for this session
        self._session_states_seen = set()
        self.completed_session = None   # record dict once a session ends
        self.game_mode_start = None
        self._gone_since = None
        self._last_blocked = False
        # Kill-switch learning: a session that passes through
        # "blocked" proves the kill switch is on; a protected session
        # that reaches "bare" without ever blocking proves it is off.
        # While unknown (None) the steps show the full kill-switch
        # version; once learned False they shorten to the plain
        # Disconnect / Connect pair.
        self.ks_seen = settings.get("kill_switch_seen")
        self._session_blocked = False
        self._session_was_protected = False

    # -- helpers -----------------------------------------------------------

    def session_seconds(self):
        if self.session_start is None:
            return 0.0
        return max(0.0, self._now() - self.session_start)

    def game_mode_seconds(self):
        if self.game_mode_start is None:
            return 0.0
        return max(0.0, self._now() - self.game_mode_start)

    def note_ping(self, ms):
        """Record the ping measured for the live session (int ms, or
        None to clear). Ignored when no session is live, so a late
        result can never attach to the wrong session."""
        if self.session_start is None:
            return
        if ms is None:
            self.session_ping_ms = None
            return
        try:
            self.session_ping_ms = max(0, int(ms))
        except (TypeError, ValueError):
            self.session_ping_ms = None

    def _build_session_record(self, vpn_state):
        """The finished session, for history: games, wall-clock start,
        length, how long Game Mode was on, and the best state reached
        ('peak'): gaming > bare > blocked > protected > unknown.
        Built while session_start is still set, so the durations are
        real; returns None when no session was live."""
        if self.session_start is None:
            return None
        if self.game_mode_start is not None:
            peak = "gaming"
        elif "bare" in self._session_states_seen:
            peak = "bare"
        elif "blocked" in self._session_states_seen:
            peak = "blocked"
        elif "protected" in self._session_states_seen:
            peak = "protected"
        else:
            peak = "unknown"
        return {
            "games": sorted(self.session_games),
            "started_at": self.session_start_wall or "",
            "duration_seconds": int(self.session_seconds()),
            "game_mode_seconds": int(self.game_mode_seconds()),
            "game_mode_on": self.game_mode_start is not None,
            "was_protected": self.was_protected,
            "restore_needed": bool(self.was_protected and vpn_state != "protected"),
            "peak_state": peak,
            "ping_ms": self.session_ping_ms,
        }

    # -- main entry --------------------------------------------------------

    def update(self, running_games, vpn_state):
        events = []
        now = self._now()
        self.vpn_state = vpn_state
        running_games = set(running_games)

        started = running_games - self.active_games
        self.active_games = running_games

        if running_games:
            self._gone_since = None
            self.session_games |= running_games
            self._session_states_seen.add(vpn_state)
            if self.mode in ("idle", "restore_needed"):
                self.mode = "action_needed"
                self.session_start = now
                self.session_start_wall = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime())
                self.session_games = set(running_games)
                self.session_ping_ms = None
                self._session_states_seen = {vpn_state}
                self.completed_session = None
                self.game_mode_start = None
                self.was_protected = (vpn_state == "protected")
                self._session_blocked = False
                self._session_was_protected = (vpn_state == "protected")
                for name in sorted(started or running_games):
                    events.append(f"game_started:{name}")
                events.append("action_needed")
            if self.mode in ("action_needed", "gaming"):
                if vpn_state == "protected":
                    self._session_was_protected = True
                if vpn_state == "blocked":
                    self._session_blocked = True
                    self.ks_seen = True
            if self.mode == "action_needed" and vpn_state == "bare":
                self.mode = "gaming"
                self.game_mode_start = now
                if self._session_was_protected:
                    self.ks_seen = self._session_blocked
                events.append("game_mode_on")
            if vpn_state == "blocked" and not self._last_blocked and self.mode == "action_needed":
                events.append("blocked_midway")
        else:
            if self.mode in ("gaming", "action_needed"):
                if self._gone_since is None:
                    self._gone_since = now
                debounce = float(self.settings.get("gone_debounce_seconds", 10.0))
                if now - self._gone_since >= debounce:
                    events.append("game_ended")
                    self.completed_session = self._build_session_record(vpn_state)
                    self.session_start = None
                    self.session_start_wall = None
                    self.game_mode_start = None
                    self._gone_since = None
                    if self.was_protected and vpn_state != "protected":
                        self.mode = "restore_needed"
                        events.append("restore_needed")
                    else:
                        self.mode = "idle"
                        self.was_protected = False
            elif self.mode == "restore_needed" and vpn_state == "protected":
                self.mode = "idle"
                self.was_protected = False
                events.append("protected_restored")

        self._last_blocked = (vpn_state == "blocked")
        return events

    # -- step list for the action panel ------------------------------------

    def current_steps(self):
        """[(text, state)] with state in done | current | next | warn."""
        if self.mode == "action_needed":
            if self.vpn_state == "protected":
                if self.ks_seen is False:
                    return [
                        ("In Proton: click Disconnect", "current"),
                        ("Game Mode turns on by itself once you are bare", "next"),
                    ]
                return [
                    ("In Proton: Settings > Connection > Kill switch — set it to Off", "current"),
                    ("Then click Disconnect in Proton", "next"),
                    ("Game Mode turns on by itself once you are bare", "next"),
                ]
            if self.vpn_state == "blocked":
                return [
                    ("You disconnected — good", "done"),
                    ("But the Advanced Kill Switch is still ON, so the internet is blocked (expected mid-step)", "warn"),
                    ("In Proton: set Kill Switch to Off, and stay disconnected", "current"),
                    ("Game Mode turns on by itself once you are bare", "next"),
                ]
            if self.vpn_state == "bare":
                return [("You are bare — Game Mode is on", "done")]
            return [
                ("Open Proton, turn the Kill Switch Off, then Disconnect", "current"),
                ("Waiting to verify your connection state…", "next"),
            ]
        if self.mode == "restore_needed":
            if self.vpn_state == "blocked":
                return [
                    ("The Kill Switch is back On — good", "done"),
                    ("Now click Connect in Proton (Quick Connect)", "current"),
                    ("Protection restores by itself once the tunnel is up", "next"),
                ]
            if self.ks_seen is False:
                return [
                    ("In Proton: click Connect (Quick Connect)", "current"),
                    ("Protection restores by itself once the tunnel is up", "next"),
                ]
            return [
                ("In Proton: click Connect (Quick Connect)", "current"),
                ("Then set Kill Switch back to Advanced and click Apply", "next"),
                ("Protection restores by itself once the tunnel is up", "next"),
            ]
        return []


# ---------------------------------------------------------------------------
# Exe icon (build-time only)
# ---------------------------------------------------------------------------

ICON_SIZES = ((16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))


def write_app_icon(path):
    """Draw the branded exe icon and save it as a multi-size .ico.

    Violet rounded square (the app's dark gaming look) with a cyan
    lightning bolt — Game Mode on. Pillow is imported lazily: this is
    build tooling, called by build.bat when gamemode_icon.ico is
    missing, and the updater ships the generated file. The drawing
    is deterministic, so regenerating it gives byte-identical output.
    Returns the path written.
    """
    from PIL import Image, ImageDraw

    size = 256
    top = (124, 58, 237)      # violet #7C3AED
    bottom = (76, 29, 149)    # deep violet #4C1D95
    bolt_fill = (34, 211, 238, 255)  # cyan #22D3EE

    # Vertical violet gradient.
    column = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        column.putpixel((0, y), tuple(
            int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    gradient = column.resize((size, size))

    # Rounded-square mask, then the gradient through it.
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=56, fill=255)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    image.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(image)
    # Subtle lighter inner edge so the square reads on dark taskbars.
    draw.rounded_rectangle([5, 5, size - 6, size - 6], radius=52,
                           outline=(167, 139, 250, 110), width=3)
    # Cyan lightning bolt, centred.
    bolt = [(148, 26), (92, 142), (126, 142),
            (104, 230), (166, 112), (132, 112)]
    draw.polygon(bolt, fill=bolt_fill)

    image.save(path, format="ICO", sizes=list(ICON_SIZES))
    return path
