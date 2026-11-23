"""Round 8 — stress, soak and filesystem robustness."""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-stress-")


def test_match_performance():
    games = core.default_settings()["games"]
    names = [f"process_{i}.exe" for i in range(5000)] + ["cs2.exe", "FiveM_b2545_GTAProcess.exe"]
    start = time.perf_counter()
    for _ in range(20):
        running = core.match_games(names, games)
    elapsed = time.perf_counter() - start
    assert running == {"Counter-Strike 2", "FiveM / GTA V"}
    assert elapsed < 2.0, f"matching too slow: {elapsed:.2f}s for 20x5000"
    print(f"PASS match performance (20x5002 processes in {elapsed:.2f}s)")


def test_engine_soak():
    settings = core.default_settings()
    tick = [0.0]
    eng = core.Engine(settings, now=lambda: tick[0])
    states = ["protected", "bare", "blocked", "unknown"]
    total_events = 0
    for i in range(20000):
        tick[0] += 1.0
        games = {"Rust"} if (i // 50) % 2 == 0 else set()
        events = eng.update(games, states[i % 4])
        assert isinstance(events, list)
        total_events += len(events)
    assert eng.mode in ("idle", "action_needed", "gaming", "restore_needed")
    print(f"PASS engine soak: 20000 updates, {total_events} events, mode={eng.mode}")


def test_settings_path_is_directory():
    assert core.load_settings(TMP) == core.default_settings()  # OSError -> defaults
    print("PASS settings path is a directory")


def test_find_proton_exe():
    real = os.path.join(TMP, "ProtonVPN.exe")
    with open(real, "w") as fh:
        fh.write("fake")
    assert core.find_proton_exe({"proton_path": real}) == real
    assert core.find_proton_exe({"proton_path": os.path.join(TMP, "missing.exe")}) is None
    assert core.find_proton_exe({}) is None  # no candidates exist in the sandbox
    assert core.find_proton_exe() is None
    print("PASS find_proton_exe override + fallback")


def test_log_line_appends():
    target = os.path.join(TMP, "deep", "gamemode.log")
    core.log_line("first", path=target, stamp="2026-01-01 00:00:00")
    core.log_line("second", path=target, stamp="2026-01-01 00:01:00")
    with open(target, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert lines == ["[2026-01-01 00:00:00] first", "[2026-01-01 00:01:00] second"]
    print("PASS log_line creates dirs and appends")


def test_save_normalizes_junk():
    target = os.path.join(TMP, "junk.json")
    junk = {"poll_seconds": "fast", "games": [{"name": "X", "patterns": ["x.exe"]}, 42]}
    core.save_settings(junk, target)
    with open(target, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["poll_seconds"] == 2.0
    assert [g["name"] for g in saved["games"]] == ["X"]
    print("PASS save normalizes junk input")


if __name__ == "__main__":
    test_match_performance()
    test_engine_soak()
    test_settings_path_is_directory()
    test_find_proton_exe()
    test_log_line_appends()
    test_save_normalizes_junk()
    print("ROUND 8: ALL PASS")
