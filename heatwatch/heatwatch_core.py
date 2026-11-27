"""HeatWatch core: temperature sources, game sessions, verdicts.

HeatWatch watches CPU/GPU temperatures while Ariya games and
answers one question with data instead of vibes: is the laptop's
cooling still fine, or is a repaste actually due?

Temperature sources, in the order they are tried (verified
against LibreHardwareMonitor v0.9.6 docs, Nov 2026):

1. LibreHardwareMonitor's built-in web server,
   http://127.0.0.1:8085/data.json — one cheap HTTP GET. Needs
   LHM running (as administrator, so its driver can read the
   CPU) with Options > Remote Web Server ticked.
2. LibreHardwareMonitor's WMI provider, namespace
   root\\LibreHardwareMonitor (root\\OpenHardwareMonitor as a
   fallback) — published whenever LHM runs, but a few machines
   never register it, hence the web route first.
3. nvidia-smi for the GPU only — ships with the NVIDIA driver,
   needs nothing extra, but knows nothing about the CPU.

Everything except the actual subprocess/HTTP calls is pure and
unit-tested; the readers are injectable.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---------------------------------------------------------------------------
# Data locations: per-user, never next to the exe
# ---------------------------------------------------------------------------

def data_dir():
    path = os.path.join(os.path.expanduser("~"), "HeatWatch")
    os.makedirs(path, exist_ok=True)
    return path


def settings_path():
    return os.path.join(data_dir(), "settings.json")


def history_path():
    return os.path.join(data_dir(), "sessions.json")


def idle_path():
    return os.path.join(data_dir(), "idle.json")


def log_path():
    return os.path.join(data_dir(), "heatwatch.log")


def log_line(message):
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

DEFAULT_GAMES = [
    {"name": "Counter-Strike 2", "patterns": ["cs2.exe"], "enabled": True, "builtin": True},
    {"name": "Rust", "patterns": ["rustclient.exe"], "enabled": True, "builtin": True},
    {"name": "FiveM / GTA V", "patterns": ["fivem*.exe", "gta5.exe"], "enabled": True, "builtin": True},
    {"name": "Overwatch", "patterns": ["overwatch.exe"], "enabled": True, "builtin": True},
    {"name": "Deadlock", "patterns": ["project8.exe", "deadlock.exe"], "enabled": True, "builtin": True},
]


def default_settings():
    return {
        "poll_seconds": 3.0,
        "warn_cpu_c": 95,
        "warn_gpu_c": 85,
        "gone_debounce_seconds": 10.0,
        "lhm_port": 8085,
        "lhm_path": "",
        "minimize_to_tray": True,
        "start_with_windows": False,
        "games": [dict(game) for game in DEFAULT_GAMES],
    }


def _clamp(value, low, high, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def normalize_settings(raw):
    """Coerce untrusted settings data into a safe, complete dict."""
    settings = default_settings()
    if not isinstance(raw, dict):
        return settings
    settings["poll_seconds"] = _clamp(raw.get("poll_seconds"), 1.0, 30.0, 3.0)
    settings["warn_cpu_c"] = int(_clamp(raw.get("warn_cpu_c"), 50, 110, 95))
    settings["warn_gpu_c"] = int(_clamp(raw.get("warn_gpu_c"), 40, 110, 85))
    settings["gone_debounce_seconds"] = _clamp(
        raw.get("gone_debounce_seconds"), 0.0, 120.0, 10.0)
    settings["lhm_port"] = int(_clamp(raw.get("lhm_port"), 1, 65535, 8085))
    if isinstance(raw.get("lhm_path"), str):
        settings["lhm_path"] = raw["lhm_path"].strip()
    settings["minimize_to_tray"] = bool(raw.get("minimize_to_tray", True))
    settings["start_with_windows"] = bool(raw.get("start_with_windows", False))
    games = raw.get("games")
    if isinstance(games, list):
        cleaned, seen = [], set()
        for game in games:
            if not isinstance(game, dict):
                continue
            name = str(game.get("name", "")).strip()
            patterns = game.get("patterns")
            if not name or name.lower() in seen:
                continue
            if not isinstance(patterns, list):
                continue
            patterns = [str(p).strip().lower() for p in patterns if str(p).strip()]
            if not patterns:
                continue
            seen.add(name.lower())
            cleaned.append({
                "name": name,
                "patterns": patterns,
                "enabled": bool(game.get("enabled", True)),
                "builtin": bool(game.get("builtin", False)),
            })
        if cleaned:
            settings["games"] = cleaned
    return settings


def load_settings():
    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            return normalize_settings(json.load(fh))
    except (OSError, ValueError):
        return default_settings()


def save_settings(settings):
    tmp = settings_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
    os.replace(tmp, settings_path())


# ---------------------------------------------------------------------------
# Game process matching (same glob rules as GameMode VPN)
# ---------------------------------------------------------------------------

def match_games(running_names, games):
    """Display names of enabled games with a running process."""
    lowered = [str(name).lower() for name in running_names]
    matched = []
    for game in games:
        if not game.get("enabled", True):
            continue
        for pattern in game["patterns"]:
            if any(fnmatch.fnmatchcase(name, pattern) for name in lowered):
                matched.append(game["name"])
                break
    return matched


def add_custom_game(settings, name, patterns):
    """Add a user-defined game to settings["games"].

    `patterns` may be a comma-separated string or a list of
    process names. Returns (game, None) on success, or
    (None, error) when the name is empty, no process name
    survives cleaning, or a game with that name is already
    listed (case-insensitive). Built-in games are protected
    by the same duplicate check.
    """
    if not isinstance(settings, dict):
        return None, "Add game needs a name and at least one process name"
    name = str(name or "").strip()
    if not name:
        return None, "Add game needs a name and at least one process name"
    if isinstance(patterns, str):
        patterns = patterns.split(",")
    if not isinstance(patterns, (list, tuple)):
        return None, "Add game needs a name and at least one process name"
    cleaned = [str(p).strip().lower() for p in patterns
               if str(p).strip()]
    if not cleaned:
        return None, "Add game needs a name and at least one process name"
    games = settings.setdefault("games", [])
    for game in games:
        if not isinstance(game, dict):
            continue
        if str(game.get("name", "")).strip().lower() == name.lower():
            return None, f"{name} is already on the watch list"
    game = {"name": name, "patterns": cleaned, "enabled": True,
            "builtin": False}
    games.append(game)
    return game, None


def remove_custom_game(settings, name):
    """Remove a custom (non-builtin) game by name. Returns True
    when one was removed; built-in games and unknown names
    return False and change nothing."""
    if not isinstance(settings, dict):
        return False
    target = str(name or "").strip().lower()
    if not target:
        return False
    games = settings.get("games") or []
    kept = [game for game in games
            if not (isinstance(game, dict)
                    and str(game.get("name", "")).strip().lower() == target
                    and not game.get("builtin"))]
    if len(kept) == len(games):
        return False
    settings["games"] = kept
    return True


def running_process_names():
    names = set()
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info.get("name")
            except Exception:
                name = None
            if name:
                names.add(name)
        if names:
            return names
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
            text=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        for line in out.stdout.splitlines():
            parts = line.split('","')
            if parts:
                names.add(parts[0].strip('"'))
    except Exception:
        pass
    return names


# ---------------------------------------------------------------------------
# LibreHardwareMonitor web feed (data.json tree)
# ---------------------------------------------------------------------------

_GPU_KEYS = ("nvidia", "geforce", "rtx", "gtx", "radeon", "gpu")
_CPU_KEYS = ("core i3", "core i5", "core i7", "core i9", "core ultra",
             "ryzen", "cpu")


def _value_float(text):
    if isinstance(text, (int, float)):
        return float(text)
    if isinstance(text, str):
        match = re.search(r"-?\d+(?:[.,]\d+)?", text)
        if match:
            try:
                return float(match.group(0).replace(",", "."))
            except ValueError:
                return None
    return None


# A sensor that reports a physically impossible value is a
# broken sensor, not a hot laptop: LHM sometimes publishes
# 255 °C (or -55 °C) for a missing probe, and a stray fan RPM
# in the hundreds of thousands. Such values are dropped at
# the parse step, so they read as "no reading" — never as a
# peak, a verdict input, or a warning — and the fallback
# sources still get their chance, because a dropped value is
# a missing value. The bounds are generous on purpose: a
# laptop CPU never legitimately reads past 130 °C, and no
# laptop fan spins past 100k RPM.
TEMP_MIN_C = -40.0
TEMP_MAX_C = 130.0
FAN_MAX_RPM = 100000.0


def _sane_temp(value):
    """A plausible temperature, or None when it cannot be one."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if TEMP_MIN_C <= number <= TEMP_MAX_C:
        return number
    return None


def _sane_fan(value):
    """A plausible fan speed, or None when it cannot be one."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= number <= FAN_MAX_RPM:
        return number
    return None


def _pick_cpu_temp(sensors):
    """sensors: {name: value}. Prefer the package reading."""
    for name, value in sensors.items():
        if name.strip().lower() == "cpu package" and value is not None:
            return value
    cores = [v for n, v in sensors.items()
             if v is not None and (n.lower().startswith("cpu core")
                                   or n.lower() == "core average")]
    if cores:
        return max(cores)
    values = [v for v in sensors.values() if v is not None]
    return max(values) if values else None


def _pick_gpu_temp(sensors):
    for name, value in sensors.items():
        if name.strip().lower() == "gpu core" and value is not None:
            return value
    for name, value in sensors.items():
        if name.strip().lower().startswith("gpu") and value is not None:
            return value
    values = [v for v in sensors.values() if v is not None]
    return max(values) if values else None


def _hardware_temp_groups(node, groups):
    """Collect {hardware_text: {sensor_name: value}} from the tree.

    A hardware node is one whose children include a "Temperatures"
    category; sensors may also hang directly under the hardware.
    """
    if not isinstance(node, dict):
        return
    children = node.get("Children") or []
    temps = {}
    is_hardware = False
    for child in children:
        if not isinstance(child, dict):
            continue
        if str(child.get("Text", "")).strip().lower() == "temperatures":
            is_hardware = True
            for sensor in child.get("Children") or []:
                if isinstance(sensor, dict):
                    value = _sane_temp(_value_float(sensor.get("Value")))
                    if value is not None:
                        temps[str(sensor.get("Text", ""))] = value
        elif "Value" in child and child.get("Children") in (None, []):
            value = _sane_temp(_value_float(child.get("Value")))
            if value is not None and "°c" in str(child.get("Value", "")):
                temps[str(child.get("Text", ""))] = value
                is_hardware = True
    if is_hardware:
        groups[str(node.get("Text", ""))] = temps
    for child in children:
        _hardware_temp_groups(child, groups)


def _hardware_fan_values(node, values):
    """Collect fan RPM values from the LHM data.json tree.

    A hardware node is one whose children include a "Fans"
    category; each sensor's Value reads like "2100 RPM".
    Values from every hardware node are collected — the
    caller's max is the "how hard are the fans working"
    number for the sample.
    """
    if not isinstance(node, dict):
        return
    children = node.get("Children") or []
    for child in children:
        if not isinstance(child, dict):
            continue
        if str(child.get("Text", "")).strip().lower() == "fans":
            for sensor in child.get("Children") or []:
                if isinstance(sensor, dict):
                    value = _sane_fan(_value_float(sensor.get("Value")))
                    if value is not None:
                        values.append(value)
    for child in children:
        _hardware_fan_values(child, values)


def parse_lhm_web_tree(tree):
    """-> {"cpu": float|None, "gpu": float|None, "fan": float|None}
    from a data.json tree. "fan" is the fastest fan RPM LHM
    exposes, or None when no fan sensor is published."""
    groups = {}
    _hardware_temp_groups(tree, groups)
    fans = []
    _hardware_fan_values(tree, fans)
    cpu = gpu = None
    for hardware, sensors in groups.items():
        text = hardware.lower()
        if any(key in text for key in _GPU_KEYS):
            if gpu is None:
                gpu = _pick_gpu_temp(sensors)
        elif any(key in text for key in _CPU_KEYS):
            if cpu is None:
                cpu = _pick_cpu_temp(sensors)
    return {"cpu": cpu, "gpu": gpu,
            "fan": max(fans) if fans else None}


def fetch_lhm_web(port=8085, timeout=2.0):
    url = f"http://127.0.0.1:{int(port)}/data.json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            tree = json.loads(resp.read().decode("utf-8", "replace"))
        result = parse_lhm_web_tree(tree)
        if (result["cpu"] is not None or result["gpu"] is not None
                or result["fan"] is not None):
            return result
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# LibreHardwareMonitor WMI provider
# ---------------------------------------------------------------------------

_WMI_PS = (
    "Get-CimInstance -Namespace 'root/{ns}' -ClassName Sensor "
    "| Select-Object Name,SensorType,Value,Identifier "
    "| ConvertTo-Json -Compress"
)


def parse_wmi_sensors(json_text):
    """-> {"cpu": ..., "gpu": ..., "fan": ...} from the
    PowerShell JSON output. "fan" is the fastest Fan-type
    sensor's RPM, or None when LHM publishes no fan sensor."""
    try:
        data = json.loads(json_text)
    except (TypeError, ValueError):
        return {"cpu": None, "gpu": None, "fan": None}
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return {"cpu": None, "gpu": None, "fan": None}
    cpu_sensors, gpu_sensors = {}, {}
    fan_values = []
    for item in data:
        if not isinstance(item, dict):
            continue
        sensor_type = str(item.get("SensorType", "")).lower()
        raw = _value_float(item.get("Value"))
        if raw is None:
            continue
        if sensor_type == "fan":
            fan = _sane_fan(raw)
            if fan is not None:
                fan_values.append(fan)
            continue
        if sensor_type != "temperature":
            continue
        value = _sane_temp(raw)
        if value is None:
            continue
        name = str(item.get("Name", ""))
        identifier = str(item.get("Identifier", "")).lower()
        if "gpu" in identifier:
            gpu_sensors[name] = value
        elif "cpu" in identifier:
            cpu_sensors[name] = value
    return {
        "cpu": _pick_cpu_temp(cpu_sensors) if cpu_sensors else None,
        "gpu": _pick_gpu_temp(gpu_sensors) if gpu_sensors else None,
        "fan": max(fan_values) if fan_values else None,
    }


def fetch_lhm_wmi(timeout=8.0):
    for namespace in ("LibreHardwareMonitor", "OpenHardwareMonitor"):
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 _WMI_PS.format(ns=namespace)],
                capture_output=True, text=True, timeout=timeout,
                creationflags=CREATE_NO_WINDOW)
            if out.returncode == 0 and out.stdout.strip():
                result = parse_wmi_sensors(out.stdout)
                if (result["cpu"] is not None
                        or result["gpu"] is not None
                        or result["fan"] is not None):
                    return result
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# nvidia-smi (GPU only)
# ---------------------------------------------------------------------------

def parse_nvidia_smi(text):
    if not text:
        return None
    for line in str(text).splitlines():
        value = _value_float(line.strip())
        if value is not None:
            return _sane_temp(value)
    return None


def fetch_nvidia_smi(timeout=4.0):
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW)
        if out.returncode == 0:
            return parse_nvidia_smi(out.stdout)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Merged sampling
# ---------------------------------------------------------------------------

WMI_MISS_SECONDS = 60.0
_wmi_miss_until = [0.0]


def _reset_source_caches():
    _wmi_miss_until[0] = 0.0


def collect_temps(port=8085, readers=None, now=None):
    """One temperature sample from the best available sources.

    -> {"cpu": float|None, "gpu": float|None, "fan": float|None,
        "source": str}

    "fan" is the fastest fan RPM LibreHardwareMonitor exposes
    (web feed first, WMI filling in when it runs for the
    temperatures anyway), or None when no fan sensor is
    published. The fan reading rides along with the
    temperature source in use — HeatWatch never spawns the
    PowerShell probe just for a fan reading.

    The WMI route spawns PowerShell — by far the most expensive
    probe. When it comes back empty (LibreHardwareMonitor is not
    running), the miss is remembered for WMI_MISS_SECONDS so a
    machine without LHM does not pay that spawn on every poll.
    A WMI hit clears the miss immediately.
    """
    if readers is None:
        readers = {
            "web": lambda: fetch_lhm_web(port),
            "wmi": fetch_lhm_wmi,
            "smi": fetch_nvidia_smi,
        }
    if now is None:
        now = time.time()
    cpu = gpu = fan = None
    used = []
    web = readers["web"]()
    if web:
        cpu, gpu = web.get("cpu"), web.get("gpu")
        fan = web.get("fan")
        if cpu is not None or gpu is not None or fan is not None:
            used.append("LHM web")
    if cpu is None or gpu is None:
        if now >= _wmi_miss_until[0]:
            wmi = readers["wmi"]()
            if wmi and (wmi.get("cpu") is not None
                        or wmi.get("gpu") is not None
                        or wmi.get("fan") is not None):
                _wmi_miss_until[0] = 0.0
                if cpu is None:
                    cpu = wmi.get("cpu")
                if gpu is None:
                    gpu = wmi.get("gpu")
                if fan is None:
                    fan = wmi.get("fan")
                used.append("LHM WMI")
            else:
                _wmi_miss_until[0] = now + WMI_MISS_SECONDS
    if gpu is None:
        smi = readers["smi"]()
        if smi is not None:
            gpu = smi
            used.append("nvidia-smi")
    return {"cpu": cpu, "gpu": gpu, "fan": fan,
            "source": " + ".join(used) if used else "none"}


# ---------------------------------------------------------------------------
# Session tracking
# ---------------------------------------------------------------------------

class SessionTracker:
    """Turns (time, games, temps) ticks into finished session records."""

    # A session's temperature series is kept for the graph: at the
    # 3-second default poll this is ~30 minutes of full resolution;
    # longer sessions thin out (every 2nd point) instead of growing
    # the history file without bound.
    MAX_SERIES_POINTS = 600

    def __init__(self, warn_cpu=95, warn_gpu=85, debounce_seconds=10.0):
        self.warn_cpu = warn_cpu
        self.warn_gpu = warn_gpu
        self.debounce = debounce_seconds
        self.session = None
        self._gone_since = None
        self._last_ts = None

    def _start(self, ts, game):
        self.session = {
            "id": time.strftime("%Y%m%d-%H%M%S", time.localtime(ts)),
            "game": game,
            "start": ts,
            "samples": 0,
            "series": [],
            "peak_cpu": None,
            "peak_gpu": None,
            "fan_low": None,
            "fan_peak": None,
            "sec_above_cpu": 0.0,
            "sec_above_gpu": 0.0,
            "warn_cpu": self.warn_cpu,
            "warn_gpu": self.warn_gpu,
            "sources": set(),
        }
        self._gone_since = None
        # The tick that starts the session is its first sample,
        # so its over-line clock starts at zero, not at the gap
        # since the previous idle poll.
        self._last_ts = ts

    def _finish(self, ts):
        record = dict(self.session)
        record["end"] = ts
        record["duration_s"] = round(ts - record["start"], 1)
        record["sources"] = sorted(record["sources"])
        # Fan range as whole RPM — a missing fan sensor stays
        # None, never a guess.
        if record["fan_peak"] is not None:
            record["fan_peak"] = int(round(record["fan_peak"]))
        if record["fan_low"] is not None:
            record["fan_low"] = int(round(record["fan_low"]))
        # JSON-safe copy: [elapsed_s, cpu, gpu] per tick, None kept
        # as None — a missing reading is a gap, never a guess.
        record["series"] = [list(point) for point in record["series"]]
        record["sec_above_cpu"] = round(record["sec_above_cpu"], 1)
        record["sec_above_gpu"] = round(record["sec_above_gpu"], 1)
        self.session = None
        self._gone_since = None
        return record

    def update(self, ts, running_games, cpu, gpu, source="",
               fan=None):
        """Feed one tick; returns a list of events:
        ("started", game) / ("ended", record).

        `fan` is the fastest fan RPM this tick (None when no
        fan sensor is published); the session keeps the low
        and peak so the fan range is visible next to the
        temperatures. A tick without a fan reading leaves the
        range untouched — it never resets it or fills it in.

        The tick that starts a session is recorded as its
        first sample (peak, series, fan range, source) — it
        used to be dropped, so a hot start tick never showed
        up in the peak or the graph.
        """
        events = []
        games = list(running_games or [])
        if self.session is None:
            if games:
                self._start(ts, sorted(games)[0])
                events.append(("started", self.session["game"]))
            else:
                self._last_ts = ts
                return events
        dt = 0.0
        if self._last_ts is not None:
            dt = max(0.0, min(30.0, ts - self._last_ts))
        self._last_ts = ts
        session = self.session
        session["samples"] += 1
        series = session["series"]
        series.append([round(ts - session["start"], 1), cpu, gpu])
        if len(series) > self.MAX_SERIES_POINTS:
            # Thin in place: keep the shape, halve the resolution.
            series[:] = series[::2]
        if source:
            session["sources"].add(source)
        if cpu is not None:
            session["peak_cpu"] = (cpu if session["peak_cpu"] is None
                                   else max(session["peak_cpu"], cpu))
            if cpu >= self.warn_cpu:
                session["sec_above_cpu"] += dt
        if gpu is not None:
            session["peak_gpu"] = (gpu if session["peak_gpu"] is None
                                   else max(session["peak_gpu"], gpu))
            if gpu >= self.warn_gpu:
                session["sec_above_gpu"] += dt
        if fan is not None:
            session["fan_peak"] = (fan if session["fan_peak"] is None
                                   else max(session["fan_peak"], fan))
            session["fan_low"] = (fan if session["fan_low"] is None
                                  else min(session["fan_low"], fan))
        if games:
            self._gone_since = None
        else:
            if self._gone_since is None:
                self._gone_since = ts
            elif ts - self._gone_since >= self.debounce:
                events.append(("ended", self._finish(ts)))
        return events

    def current(self):
        if self.session is None:
            return None
        view = dict(self.session)
        view["sources"] = sorted(view["sources"])
        return view


class HeatWarner:
    """Fires once when a temperature stays at/over the warning
    line for a sustained stretch; re-arms after it cools."""

    def __init__(self, warn_c, sustain_seconds=15.0, hysteresis=2.0):
        self.warn_c = warn_c
        self.sustain = sustain_seconds
        self.hysteresis = hysteresis
        self._since = None
        self._fired = False

    def reset(self):
        self._since = None
        self._fired = False

    def update(self, ts, value):
        if value is None:
            return False
        if value >= self.warn_c:
            if self._since is None:
                self._since = ts
            if not self._fired and ts - self._since >= self.sustain:
                self._fired = True
                return True
        elif value < self.warn_c - self.hysteresis:
            self._since = None
            self._fired = False
        return False


# ---------------------------------------------------------------------------
# Session graph geometry (pure: the GUI and the tests share it)
# ---------------------------------------------------------------------------

def chart_points(samples, width=640, height=280, warn_cpu=95,
                 warn_gpu=85):
    """Map a session's [elapsed_s, cpu, gpu] samples onto canvas
    coordinates.

    -> {"cpu": [(x, y), ...], "gpu": [(x, y), ...],
        "warn_cpu_y": float|None, "warn_gpu_y": float|None,
        "grid": [(temp, y), ...], "t_max": float, "y_max": float}

    A None temperature leaves that line with a gap at that tick —
    never interpolated, never filled with a guess. Hostile or
    malformed sample entries are skipped, never raised on.
    """
    left, right, top, bottom = 44, 12, 14, 26
    cleaned = []
    if not isinstance(samples, (list, tuple)):
        samples = []
    for point in samples:
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            continue
        try:
            elapsed = float(point[0])
            cpu = None if point[1] is None else float(point[1])
            gpu = None if point[2] is None else float(point[2])
        except (TypeError, ValueError):
            continue
        if elapsed < 0:
            continue
        cleaned.append((elapsed, cpu, gpu))
    empty = {"cpu": [], "gpu": [], "warn_cpu_y": None,
             "warn_gpu_y": None, "grid": [], "t_max": 0.0,
             "y_max": 100.0}
    if not cleaned:
        return empty
    t_max = max(point[0] for point in cleaned) or 1.0
    temps = [value for point in cleaned
             for value in (point[1], point[2]) if value is not None]
    y_max = max(100.0, (max(temps) + 10.0) if temps else 100.0)

    def x_of(elapsed):
        return left + (elapsed / t_max) * (width - left - right)

    def y_of(temp):
        y = top + (1.0 - temp / y_max) * (height - top - bottom)
        return max(top, min(height - bottom, y))

    cpu_pts = [(x_of(point[0]), y_of(point[1])) for point in cleaned
               if point[1] is not None]
    gpu_pts = [(x_of(point[0]), y_of(point[2])) for point in cleaned
               if point[2] is not None]
    grid = [(mark, y_of(mark)) for mark in range(25, int(y_max), 25)]
    return {"cpu": cpu_pts, "gpu": gpu_pts,
            "warn_cpu_y": (y_of(warn_cpu) if warn_cpu is not None
                           else None),
            "warn_gpu_y": (y_of(warn_gpu) if warn_gpu is not None
                           else None),
            "grid": grid, "t_max": t_max, "y_max": y_max}


def format_fan_range(low, peak):
    """One line for a session's fan range: "1500–3200 RPM", a
    lone "2100 RPM" when the range never moved (or only a peak
    was ever seen), or "—" when the session had no fan sensor.
    A missing low end is never invented."""
    if peak is None:
        return "—"
    try:
        peak = float(peak)
    except (TypeError, ValueError):
        return "—"
    if low is None:
        return f"{peak:.0f} RPM"
    try:
        low = float(low)
    except (TypeError, ValueError):
        return f"{peak:.0f} RPM"
    if low >= peak:
        return f"{peak:.0f} RPM"
    return f"{low:.0f}–{peak:.0f} RPM"


# ---------------------------------------------------------------------------
# History + the repaste verdict
# ---------------------------------------------------------------------------

def load_history():
    try:
        with open(history_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def append_history(record):
    history = load_history()
    history.append(record)
    tmp = history_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=2)
    os.replace(tmp, history_path())
    return history


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def verdict(history, min_duration_s=600, window=5, warn_cpu=95):
    """Judge the cooling from recent full-length game sessions.

    -> {"level": "unknown"|"healthy"|"hot"|"repaste",
        "median_peak_cpu": float|None, "sessions_used": int,
        "warn_cpu": float}

    The levels follow the user's CPU warning line (Settings)
    instead of a fixed number: "hot" when the median peak
    reaches the line, "repaste" when it sits 3°C past it. The
    default warn_cpu=95 keeps the old fixed 95/98°C split.
    The line only moves the bar — the verdict still judges
    real peaks from full sessions only, never guesses.
    """
    full = [s for s in history
            if isinstance(s, dict)
            and (s.get("duration_s") or 0) >= min_duration_s
            and s.get("peak_cpu") is not None]
    recent = full[-window:]
    if not recent:
        return {"level": "unknown", "median_peak_cpu": None,
                "sessions_used": 0, "warn_cpu": warn_cpu}
    median_peak = _median([s["peak_cpu"] for s in recent])
    if median_peak >= warn_cpu + 3:
        level = "repaste"
    elif median_peak >= warn_cpu:
        level = "hot"
    else:
        level = "healthy"
    return {"level": level, "median_peak_cpu": median_peak,
            "sessions_used": len(recent), "warn_cpu": warn_cpu}


# ---------------------------------------------------------------------------
# Idle baseline
# ---------------------------------------------------------------------------

IDLE_SAMPLE_SECONDS = 60.0
IDLE_KEEP_SECONDS = 7 * 24 * 3600
IDLE_MAX_SAMPLES = 10080
IDLE_WINDOW_SECONDS = 24 * 3600
IDLE_COOLDOWN_SECONDS = 300.0


def _as_temp(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class IdleBaseline:
    """Idle temperatures outside game sessions.

    One sample per minute while no watched game runs, kept for
    a week. The baseline is the median CPU/GPU over the last
    24 hours of idle samples — a rising idle baseline is an
    early dust/paste signal, shown next to the gaming peaks.

    Only real readings are stored: a tick with no temperature
    at all is dropped, and a half-missing sample keeps its
    None half (a gap, never a guess). The first five minutes
    after a session ends are skipped, so post-game heat does
    not pollute the baseline.
    """

    def __init__(self, samples=None):
        self.samples = []
        if isinstance(samples, (list, tuple)):
            for point in samples:
                cleaned = self._clean_point(point)
                if cleaned is not None:
                    self.samples.append(cleaned)
        self.samples.sort(key=lambda point: point[0])
        self._last_ts = (self.samples[-1][0] if self.samples
                         else None)

    @staticmethod
    def _clean_point(point):
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            return None
        ts = _as_temp(point[0])
        if ts is None or ts < 0:
            return None
        cpu, gpu = _as_temp(point[1]), _as_temp(point[2])
        if cpu is None and gpu is None:
            return None
        return [ts, cpu, gpu]

    def record(self, ts, cpu, gpu, blocked_until=0.0):
        """Store one idle sample. Returns True when stored."""
        if ts < blocked_until:
            return False
        cpu, gpu = _as_temp(cpu), _as_temp(gpu)
        if cpu is None and gpu is None:
            return False
        if (self._last_ts is not None
                and ts - self._last_ts < IDLE_SAMPLE_SECONDS):
            return False
        self.samples.append([float(ts), cpu, gpu])
        self._last_ts = float(ts)
        self._prune(ts)
        return True

    def _prune(self, now):
        cutoff = now - IDLE_KEEP_SECONDS
        self.samples = [p for p in self.samples if p[0] >= cutoff]
        overflow = len(self.samples) - IDLE_MAX_SAMPLES
        if overflow > 0:
            del self.samples[:overflow]

    def baseline(self, now=None, window_seconds=IDLE_WINDOW_SECONDS):
        """Median idle CPU/GPU over the recent window.

        -> {"cpu": float|None, "gpu": float|None, "samples": int}
        where "samples" counts the idle ticks in the window.
        """
        if now is None:
            now = time.time()
        cutoff = now - window_seconds
        window = [p for p in self.samples if p[0] >= cutoff]
        cpus = [p[1] for p in window if p[1] is not None]
        gpus = [p[2] for p in window if p[2] is not None]
        return {"cpu": _median(cpus), "gpu": _median(gpus),
                "samples": len(window)}

    def to_dict(self):
        return {"samples": [list(p) for p in self.samples]}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls()
        return cls(data.get("samples"))


def load_idle_baseline():
    try:
        with open(idle_path(), "r", encoding="utf-8") as fh:
            return IdleBaseline.from_dict(json.load(fh))
    except (OSError, ValueError):
        return IdleBaseline()


def save_idle_baseline(baseline):
    tmp = idle_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(baseline.to_dict(), fh, indent=2)
    os.replace(tmp, idle_path())


def format_idle_baseline(baseline):
    """One line for the verdict card."""
    if not isinstance(baseline, dict):
        baseline = {}
    if not baseline.get("samples"):
        return "Idle baseline: not enough idle data yet"
    cpu = baseline.get("cpu")
    gpu = baseline.get("gpu")
    cpu_text = "—" if cpu is None else f"{cpu:.0f}°C"
    gpu_text = "—" if gpu is None else f"{gpu:.0f}°C"
    return (f"Idle baseline (last 24 h): CPU {cpu_text} · GPU "
            f"{gpu_text} ({baseline['samples']} samples)")


# ---------------------------------------------------------------------------
# LibreHardwareMonitor location (for the Open button)
# ---------------------------------------------------------------------------

def find_lhm_exe(settings):
    candidates = []
    saved = (settings or {}).get("lhm_path", "")
    if saved:
        candidates.append(saved)
    program_files = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)",
                                    r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")]
    for base in program_files:
        if not base:
            continue
        root = os.path.join(base, "LibreHardwareMonitor")
        candidates.append(os.path.join(root, "LibreHardwareMonitor.exe"))
        try:
            for entry in os.listdir(root):
                candidates.append(os.path.join(
                    root, entry, "LibreHardwareMonitor.exe"))
        except OSError:
            pass
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def is_windows():
    return sys.platform.startswith("win")


# ---------------------------------------------------------------------------
# LibreHardwareMonitor autostart (Task Scheduler)
# ---------------------------------------------------------------------------

LHM_TASK_NAME = "LibreHardwareMonitor"


def build_lhm_task_args(exe_path):
    """schtasks argv registering LHM to start elevated at logon.

    /SC ONLOGON runs it at every sign-in; /RL HIGHEST runs it
    elevated so its driver can read the CPU; /F replaces a
    task HeatWatch registered before. No extra flags on the
    exe itself: LHM remembers its own minimize-to-tray
    setting. Returns None for a blank path.
    """
    path = str(exe_path or "").strip()
    if not path:
        return None
    return ["schtasks", "/Create", "/TN", LHM_TASK_NAME,
            "/TR", f'"{path}"', "/SC", "ONLOGON", "/RL", "HIGHEST",
            "/F"]


def _ps_quote(arg):
    """One PowerShell single-quoted literal ('' escapes ')."""
    return "'" + str(arg).replace("'", "''") + "'"


def build_elevated_command(argv):
    """Wrap argv in a PowerShell that re-launches it elevated.

    Creating a highest-privileges task needs admin rights and
    HeatWatch normally runs unelevated, so the call goes
    through Start-Process -Verb RunAs (one UAC prompt).
    -PassThru + -Wait carries the exit code back out, and a
    declined prompt lands in the catch instead of hanging.
    Returns None for an empty argv.
    """
    if not argv:
        return None
    quoted = ",".join(_ps_quote(arg) for arg in argv)
    script = (
        "try { $p = Start-Process -FilePath "
        + _ps_quote(argv[0])
        + " -ArgumentList " + quoted
        + " -Verb RunAs -Wait -PassThru; exit $p.ExitCode }"
        " catch { exit 1 }")
    return ["powershell", "-NoProfile", "-NonInteractive",
            "-Command", script]


def _run_command(argv, timeout=30.0):
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout,
        creationflags=CREATE_NO_WINDOW)


def lhm_task_exists(runner=None):
    """True when the autostart task is registered.

    A query needs no elevation. False on any error, and False
    off Windows (where the runner is never called).
    """
    if not is_windows():
        return False
    run = runner or _run_command
    try:
        result = run(["schtasks", "/Query", "/TN", LHM_TASK_NAME])
        return result.returncode == 0
    except Exception:
        return False


def create_lhm_task(exe_path, runner=None):
    """Register the autostart task (elevated). -> (ok, message)."""
    if not is_windows():
        return False, "LHM autostart is available on Windows only"
    args = build_lhm_task_args(exe_path)
    if args is None:
        return False, ("LibreHardwareMonitor was not found — "
                       "install it first")
    run = runner or _run_command
    try:
        result = run(build_elevated_command(args))
    except Exception as exc:
        log_line(f"LHM autostart setup failed: {exc}")
        return False, "Could not set up LHM autostart"
    if result.returncode == 0:
        return True, ("LibreHardwareMonitor will now start at "
                      "every sign-in")
    detail = str(getattr(result, "stderr", "") or "").strip()
    log_line("LHM autostart setup failed: "
             f"rc={result.returncode} {detail}".strip())
    return False, ("Could not set up LHM autostart — approve the "
                   "admin prompt and try again")


def remove_lhm_task(runner=None):
    """Delete the autostart task (elevated). -> (ok, message)."""
    if not is_windows():
        return False, "LHM autostart is available on Windows only"
    run = runner or _run_command
    args = ["schtasks", "/Delete", "/TN", LHM_TASK_NAME, "/F"]
    try:
        result = run(build_elevated_command(args))
    except Exception as exc:
        log_line(f"LHM autostart removal failed: {exc}")
        return False, "Could not remove LHM autostart"
    if result.returncode == 0:
        return True, "LHM autostart removed"
    detail = str(getattr(result, "stderr", "") or "").strip()
    log_line("LHM autostart removal failed: "
             f"rc={result.returncode} {detail}".strip())
    return False, ("Could not remove LHM autostart — approve the "
                   "admin prompt and try again")


# ---------------------------------------------------------------------------
# Live-graph support: a rolling sample buffer + polyline scaling
# ---------------------------------------------------------------------------

class SampleBuffer:
    """The last N temperature samples, for the live sparkline."""

    def __init__(self, capacity=120):
        self.capacity = max(2, int(capacity))
        self.samples = []

    def push(self, ts, cpu, gpu):
        self.samples.append((ts, cpu, gpu))
        overflow = len(self.samples) - self.capacity
        if overflow > 0:
            del self.samples[:overflow]

    def __len__(self):
        return len(self.samples)

    def cpu_series(self):
        return [cpu for _, cpu, _ in self.samples if cpu is not None]

    def gpu_series(self):
        return [gpu for _, _, gpu in self.samples if gpu is not None]


def scale_series(values, width, height, vmin, vmax):
    """Map values to (x, y) canvas points inside width x height.

    y grows downward on a canvas, so the hottest value lands on
    y=0. Fewer than two points cannot make a line -> [].
    """
    points = [v for v in values if v is not None]
    if len(points) < 2 or width <= 0 or height <= 0:
        return []
    span = float(vmax) - float(vmin)
    if span <= 0:
        span = 1.0
    step = width / float(len(points) - 1)
    scaled = []
    for idx, value in enumerate(points):
        frac = (float(value) - float(vmin)) / span
        frac = max(0.0, min(1.0, frac))
        scaled.append((idx * step, height - frac * height))
    return scaled
