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
import os
import subprocess
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
    }


def data_dir():
    """Per-user data folder: settings + log live here, never next to the exe."""
    return os.path.join(os.path.expanduser("~"), "GameModeVPN")


def settings_path():
    return os.path.join(data_dir(), "settings.json")


def log_path():
    return os.path.join(data_dir(), "gamemode.log")


# ---------------------------------------------------------------------------
# Settings: load / save / normalize
# ---------------------------------------------------------------------------

def _clamp(value, low, high, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


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

def match_games(process_names, games):
    """Return the set of enabled game names whose patterns match a process."""
    lowered = [str(p).lower() for p in process_names if p]
    running = set()
    for game in games:
        if not game.get("enabled", True):
            continue
        for pattern in game.get("patterns", []):
            pat = str(pattern).lower()
            if any(fnmatch.fnmatchcase(name, pat) for name in lowered):
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


def ping_host(host, timeout_ms=700):
    """One ICMP echo to a LAN host; True/False, None when ping cannot run."""
    if not host:
        return None
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), host],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
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


def find_proton_exe(settings=None, bases=None):
    """Locate the Proton client: settings override first, then the
    versioned install folders (newest version wins), then flat paths."""
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
                    app = self._application_cls(backend="uia").connect(process=pid)
                    win = app.top_window()
                    if win.exists(timeout=1):
                        return win
                except Exception:
                    pass
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)

    def buttons(self, window):
        found = []
        for ctrl in window.descendants(control_type="Button"):
            try:
                found.append((ctrl.window_text() or "", ctrl))
            except Exception:
                continue
        return found

    def invoke(self, control):
        try:
            control.invoke()
        except Exception:
            control.click_input()


def _pick_button(buttons, wanted_names):
    """Exact (case-insensitive) name match wins; 'Connect' must never
    match the 'Disconnect' button, so substring matching is banned."""
    cleaned = [(name.strip(), ctrl) for name, ctrl in buttons if name and name.strip()]
    for wanted in wanted_names:
        for name, ctrl in cleaned:
            if name.lower() == wanted.lower():
                return name, ctrl
    return None, None


def auto_proton_action(action, backend=None, timeout=12.0):
    """Click Proton's own button for `action` ('disconnect'/'connect').

    Returns (ok, detail). ok=False always carries the reason, and the
    caller falls back to the guided steps — auto mode is an
    accelerator, never a single point of failure."""
    wanted = AUTO_BUTTONS.get(action)
    if not wanted:
        return (False, f"unknown action {action!r}")
    if backend is None:
        try:
            backend = _PywinautoBackend()
        except Exception as exc:
            return (False, f"auto control unavailable ({type(exc).__name__})")
    try:
        win = backend.window(timeout=timeout)
    except Exception as exc:
        return (False, f"could not reach Proton's window ({type(exc).__name__})")
    if win is None:
        return (False, "Proton's window was not found")
    try:
        buttons = backend.buttons(win)
    except Exception as exc:
        return (False, f"could not read Proton's controls ({type(exc).__name__})")
    name, ctrl = _pick_button(buttons, wanted)
    if ctrl is None:
        return (False, f"the {wanted[0]} button was not found in Proton")
    try:
        backend.invoke(ctrl)
    except Exception as exc:
        return (False, f"clicking {name} failed ({type(exc).__name__})")
    return (True, f"clicked {name} in Proton")


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

UPDATE_FILES = ("gamemode_vpn_app.py", "gamemode_core.py", "build.bat")
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
            if self.mode in ("idle", "restore_needed"):
                self.mode = "action_needed"
                self.session_start = now
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
                    self.session_start = None
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
