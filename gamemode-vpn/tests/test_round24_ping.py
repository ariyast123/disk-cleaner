"""Round 24 — Ping proof: settings, parsing, measurement, session record."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def test_settings_defaults():
    s = core.default_settings()
    assert s["ping_proof"] is False, "ping proof is off by default (privacy)"
    assert s["ping_host"] == "8.8.8.8"
    assert core.normalize_settings({})["ping_proof"] is False
    assert core.normalize_settings({})["ping_host"] == "8.8.8.8"
    print("PASS ping settings default to off / 8.8.8.8")


def test_settings_normalization():
    s = core.normalize_settings({"ping_proof": True, "ping_host": " 1.1.1.1 "})
    assert s["ping_proof"] is True
    assert s["ping_host"] == "1.1.1.1"  # trimmed
    s = core.normalize_settings({"ping_proof": "yes", "ping_host": "dns.google"})
    assert s["ping_proof"] is True
    assert s["ping_host"] == "dns.google"  # hostnames allowed
    s = core.normalize_settings({"ping_proof": 0, "ping_host": ""})
    assert s["ping_proof"] is False
    assert s["ping_host"] == "8.8.8.8"  # empty -> default
    print("PASS ping settings normalization")


def test_clean_ping_host():
    assert core.clean_ping_host("8.8.8.8") == "8.8.8.8"
    assert core.clean_ping_host("  1.1.1.1  ") == "1.1.1.1"
    assert core.clean_ping_host("dns.google") == "dns.google"
    assert core.clean_ping_host("a") == "a"
    # anything that could smuggle shell syntax or a second host falls back
    for bad in ("", None, "8.8.8.8; rm -rf /", "host name", "a/b", "a|b",
                "a`b`", "a$(b)", "a..b", "-bad", ".bad", "a" * 300):
        assert core.clean_ping_host(bad) == "8.8.8.8", bad
    print("PASS clean_ping_host refuses hostile input")


WINDOWS_OK = (
    "Pinging 8.8.8.8 with 32 bytes of data:\r\n"
    "Reply from 8.8.8.8: bytes=32 time=11ms TTL=117\r\n"
    "Reply from 8.8.8.8: bytes=32 time=13ms TTL=117\r\n"
    "Reply from 8.8.8.8: bytes=32 time=12ms TTL=117\r\n"
    "\r\nPing statistics for 8.8.8.8:\r\n"
    "    Packets: Sent = 3, Received = 3, Lost = 0 (0% loss),\r\n"
    "Approximate round trip times in milli-seconds:\r\n"
    "    Minimum = 11ms, Maximum = 13ms, Average = 12ms\r\n"
)

WINDOWS_LOSS = (
    "Pinging 10.0.0.99 with 32 bytes of data:\r\n"
    "Request timed out.\r\nRequest timed out.\r\nRequest timed out.\r\n"
    "\r\nPing statistics for 10.0.0.99:\r\n"
    "    Packets: Sent = 3, Received = 0, Lost = 3 (100% loss),\r\n"
)

LINUX_OK = (
    "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
    "64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=11.2 ms\n"
    "64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=13.8 ms\n"
    "64 bytes from 8.8.8.8: icmp_seq=3 ttl=117 time=12.4 ms\n"
    "\n--- 8.8.8.8 ping statistics ---\n"
    "3 packets transmitted, 3 received, 0% packet loss, time 2004ms\n"
    "rtt min/avg/max/mdev = 11.234/12.478/13.812/1.055 ms\n"
)


def test_parse_ping_output():
    assert core.parse_ping_output(WINDOWS_OK) == 12
    assert core.parse_ping_output(LINUX_OK) == 12  # 12.478 rounds to 12
    # sub-millisecond Windows average
    assert core.parse_ping_output("Minimum = 0ms, Maximum = 0ms, Average = <1ms") == 0
    # no replies -> no average line -> honest None, never a guess
    assert core.parse_ping_output(WINDOWS_LOSS) is None
    assert core.parse_ping_output("") is None
    assert core.parse_ping_output(None) is None
    assert core.parse_ping_output("some unrelated text") is None
    assert core.parse_ping_output("rtt min/avg/max/mdev = 1/2/3 ms") is None  # malformed
    print("PASS parse_ping_output (Windows + Linux + no-answer)")


class FakeResult:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_measure_ping_linux_path():
    calls = []
    original_run = core.subprocess.run

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeResult(LINUX_OK)

    core.subprocess.run = fake_run
    try:
        assert core.measure_ping("8.8.8.8") == 12
        assert calls[0][:3] == ["ping", "-c", "3"], calls[0]
        assert calls[0][-1] == "8.8.8.8"
        # no reply at all -> None
        core.subprocess.run = lambda cmd, **kw: FakeResult(
            "3 packets transmitted, 0 received, 100% packet loss\n", 1)
        assert core.measure_ping("10.0.0.99") is None
        # ping binary missing / cannot run -> None, never raises
        def boom(cmd, **kw):
            raise OSError("no ping here")
        core.subprocess.run = boom
        assert core.measure_ping("8.8.8.8") is None
    finally:
        core.subprocess.run = original_run
    print("PASS measure_ping (Linux path, no-answer, missing binary)")


def test_measure_ping_windows_path():
    calls = []
    original_run = core.subprocess.run
    original_platform = core.sys.platform
    core.sys.platform = "win32"

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeResult(WINDOWS_OK)

    core.subprocess.run = fake_run
    try:
        assert core.measure_ping("8.8.8.8") == 12
        assert calls[0][:3] == ["ping", "-n", "3"], calls[0]
        assert "-w" in calls[0] and calls[0][-1] == "8.8.8.8"
    finally:
        core.subprocess.run = original_run
        core.sys.platform = original_platform
    print("PASS measure_ping (Windows path)")


def test_measure_ping_refuses_bad_host():
    called = []
    original_run = core.subprocess.run
    core.subprocess.run = lambda cmd, **kw: called.append(cmd) or FakeResult(WINDOWS_OK)
    try:
        assert core.measure_ping("8.8.8.8; evil") is None
        assert core.measure_ping("") is None
        assert core.measure_ping(None) is None
        assert called == [], "a bad host must never reach the ping command"
    finally:
        core.subprocess.run = original_run
    print("PASS measure_ping refuses a bad host without running ping")


def make_engine(clock):
    return core.Engine(core.default_settings(), now=clock)


def end_session(eng, clock, state):
    eng.update(set(), state)
    clock.advance(11)
    return eng.update(set(), state)


def test_engine_note_ping():
    clock = Clock()
    eng = make_engine(clock)
    # no session live -> ignored, can never attach to the wrong session
    eng.note_ping(12)
    assert eng.session_ping_ms is None
    eng.update({"Counter-Strike 2"}, "protected")
    eng.update({"Counter-Strike 2"}, "bare")
    assert eng.mode == "gaming"
    eng.note_ping(12)
    assert eng.session_ping_ms == 12
    eng.note_ping("bad")  # garbage clears instead of crashing
    assert eng.session_ping_ms is None
    eng.note_ping(9)
    end_session(eng, clock, "bare")
    rec = eng.completed_session
    assert rec["ping_ms"] == 9, rec
    # a new session starts with a clean ping slate
    eng.update({"Rust"}, "bare")
    assert eng.session_ping_ms is None
    end_session(eng, clock, "bare")
    assert eng.completed_session["ping_ms"] is None
    print("PASS engine records the session ping and clears it per session")


def test_history_ping_roundtrip():
    tmp = tempfile.mkdtemp(prefix="gmvpn-ping-hist-")
    path = os.path.join(tmp, "history.json")
    record = {
        "games": ["Rust"], "started_at": "2026-11-23 19:40",
        "duration_seconds": 600, "game_mode_seconds": 590,
        "game_mode_on": True, "was_protected": False,
        "restore_needed": False, "peak_state": "gaming", "ping_ms": 12,
    }
    assert core.append_history(record, path) is True
    loaded = core.load_history(path)
    assert len(loaded) == 1 and loaded[0]["ping_ms"] == 12, loaded
    # a bad ping_ms in the file is cleaned to absent, never a crash
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([dict(record, ping_ms="fast")], fh)
    assert core.load_history(path)[0].get("ping_ms") is None
    # and a record without ping_ms round-trips without the key
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([{k: v for k, v in record.items() if k != "ping_ms"}], fh)
    loaded = core.load_history(path)
    assert "ping_ms" not in loaded[0], loaded
    print("PASS history keeps ping_ms, cleans bad values, stays backward compatible")


if __name__ == "__main__":
    test_settings_defaults()
    test_settings_normalization()
    test_clean_ping_host()
    test_parse_ping_output()
    test_measure_ping_linux_path()
    test_measure_ping_windows_path()
    test_measure_ping_refuses_bad_host()
    test_engine_note_ping()
    test_history_ping_roundtrip()
    print("ROUND 24: ALL PASS")
