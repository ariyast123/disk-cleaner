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


def find_proton_exe(settings=None):
    """Locate ProtonVPN.exe: settings override first, then known paths."""
    override = (settings or {}).get("proton_path", "")
    if override and os.path.isfile(override):
        return override
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
                for name in sorted(started or running_games):
                    events.append(f"game_started:{name}")
                events.append("action_needed")
            if self.mode == "action_needed" and vpn_state == "bare":
                self.mode = "gaming"
                self.game_mode_start = now
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
            return [
                ("In Proton: click Connect (Quick Connect)", "current"),
                ("Then set Kill Switch back to Advanced and click Apply", "next"),
                ("Protection restores by itself once the tunnel is up", "next"),
            ]
        return []
