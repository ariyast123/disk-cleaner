"""Round 12: stress + hostile inputs."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def test_tracker_stress():
    tracker = core.SessionTracker(95, 85, debounce_seconds=10.0)
    started = time.time()
    ts = 0.0
    for i in range(10000):
        ts += 3.0
        tracker.update(ts, ["Rust"] if i % 3 else ["Rust", "Overwatch"],
                       90 + (i % 12), 70 + (i % 20), "LHM web")
    elapsed = time.time() - started
    assert elapsed < 1.0, f"10k ticks took {elapsed:.2f}s"
    current = tracker.current()
    assert current["samples"] == 9999, current["samples"]
    assert current["peak_cpu"] == 101
    print(f"PASS 10k tracker ticks in {elapsed:.2f}s, peaks exact")


def test_matching_speed_and_rules():
    names = {f"process{i}.exe" for i in range(5000)} | {"cs2.exe"}
    games = core.default_settings()["games"]
    started = time.time()
    matched = core.match_games(names, games)
    elapsed = time.time() - started
    assert matched == ["Counter-Strike 2"], matched
    assert elapsed < 1.0
    # FiveM glob semantics, same rules as GameMode
    assert core.match_games({"fivemchat.exe"}, games) == ["FiveM / GTA V"]
    assert core.match_games({"notfivem.exe"}, games) == []
    assert core.match_games({"project8.exe"}, games) == ["Deadlock"]
    print("PASS game matching: fast, glob-exact, no false friends")


def test_parsers_never_raise():
    for junk in (None, "", "[]", "{}", 42, 4.5, b"bytes", ["x"]):
        core.parse_lhm_web_tree(junk)
        core.parse_wmi_sensors(junk)
        core.parse_nvidia_smi(junk)
    print("PASS all parsers swallow hostile input quietly")


def test_find_lhm_missing():
    assert core.find_lhm_exe({"lhm_path": r"Z:\nope\LHM.exe"}) is None
    assert core.find_lhm_exe({}) is None
    assert core.find_lhm_exe(None) is None
    print("PASS a missing LibreHardwareMonitor is a clean None")


def main():
    test_tracker_stress()
    test_matching_speed_and_rules()
    test_parsers_never_raise()
    test_find_lhm_missing()
    print("ROUND 12 ALL PASS")


if __name__ == "__main__":
    main()
