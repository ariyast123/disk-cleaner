"""Round 22: fan-speed capture — RPM from LHM, per-session range."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def readers(web=None, wmi=None, smi=None):
    return {"web": lambda: web, "wmi": lambda: wmi, "smi": lambda: smi}


def test_web_fan_wins_and_merges():
    core._reset_source_caches()
    sample = core.collect_temps(readers=readers(
        web={"cpu": 91.0, "gpu": 70.0, "fan": 2400.0},
        wmi={"cpu": 50.0, "gpu": 40.0, "fan": 999.0}, smi=30.0))
    assert sample["fan"] == 2400.0, sample
    assert sample["source"] == "LHM web", sample
    print("PASS web fan wins; no WMI probe when temps are complete")


def test_wmi_fills_fan_when_web_has_none():
    core._reset_source_caches()
    # Web gives temps but no fan sensor; WMI runs for a missing
    # GPU... no: GPU is present, so WMI never runs and the fan
    # stays None — the fan rides along, never spawns a probe.
    sample = core.collect_temps(readers=readers(
        web={"cpu": 91.0, "gpu": 70.0, "fan": None},
        wmi={"cpu": 50.0, "gpu": 40.0, "fan": 2200.0}, smi=None))
    assert sample["fan"] is None, sample
    assert sample["source"] == "LHM web", sample
    print("PASS no extra WMI probe just for a fan reading")


def test_wmi_fan_when_web_missing_gpu():
    core._reset_source_caches()
    sample = core.collect_temps(readers=readers(
        web={"cpu": 91.0, "gpu": None, "fan": None},
        wmi={"cpu": 50.0, "gpu": 40.0, "fan": 2200.0}, smi=None))
    assert sample == {"cpu": 91.0, "gpu": 40.0, "fan": 2200.0,
                      "source": "LHM web + LHM WMI"}, sample
    print("PASS WMI fills the GPU and the fan rides along with it")


def test_fan_only_web_still_fetches_temps():
    core._reset_source_caches()
    sample = core.collect_temps(readers=readers(
        web={"cpu": None, "gpu": None, "fan": 1800.0},
        wmi={"cpu": 88.0, "gpu": 65.0, "fan": 1900.0}, smi=None))
    assert sample["cpu"] == 88.0 and sample["gpu"] == 65.0, sample
    assert sample["fan"] == 1800.0, sample  # web fan kept
    assert sample["source"] == "LHM web + LHM WMI", sample
    print("PASS a fan-only web feed does not block WMI temperatures")


def test_tracker_fan_range():
    tracker = core.SessionTracker(warn_cpu=95, warn_gpu=85,
                                  debounce_seconds=10.0)
    # The starting tick is the session's first sample, so its
    # 1500 RPM enters the range as the low end.
    tracker.update(0, ["Rust"], 70, 55, "LHM web", fan=1500.0)
    tracker.update(3, ["Rust"], 80, 60, "LHM web", fan=2400.0)
    tracker.update(6, ["Rust"], 85, 62, "LHM web", fan=None)
    tracker.update(9, ["Rust"], 88, 64, "LHM web", fan=2100.0)
    current = tracker.current()
    assert current["fan_low"] == 1500.0, current
    assert current["fan_peak"] == 2400.0, current
    tracker.update(10, [], 80, 60, "LHM web", fan=2000.0)
    events = tracker.update(20, [], 80, 60, "LHM web")
    assert len(events) == 1 and events[0][0] == "ended", events
    record = events[0][1]
    assert record["fan_low"] == 1500 and record["fan_peak"] == 2400, \
        record
    assert isinstance(record["fan_peak"], int), record
    print("PASS tracker keeps the fan range; None ticks never reset it")


def test_tracker_no_fan_stays_none():
    tracker = core.SessionTracker(warn_cpu=95, warn_gpu=85,
                                  debounce_seconds=10.0)
    tracker.update(0, ["Rust"], 70, 55, "LHM web")
    tracker.update(3, ["Rust"], 80, 60, "LHM web")
    tracker.update(4, [], 80, 60, "LHM web")
    events = tracker.update(14, [], 80, 60, "LHM web")
    record = events[0][1]
    assert record["fan_low"] is None and record["fan_peak"] is None, \
        record
    print("PASS a session with no fan sensor records None, never a guess")


def test_format_fan_range():
    assert core.format_fan_range(None, None) == "—"
    assert core.format_fan_range(1500, 3200) == "1500–3200 RPM"
    assert core.format_fan_range(2100, 2100) == "2100 RPM"
    assert core.format_fan_range(None, 2600) == "2600 RPM"
    assert core.format_fan_range("junk", 2600) == "2600 RPM"
    assert core.format_fan_range(1500, None) == "—"
    print("PASS fan range formats: range, single value, missing -> em dash")


def main():
    test_web_fan_wins_and_merges()
    test_wmi_fills_fan_when_web_has_none()
    test_wmi_fan_when_web_missing_gpu()
    test_fan_only_web_still_fetches_temps()
    test_tracker_fan_range()
    test_tracker_no_fan_stays_none()
    test_format_fan_range()
    print("ROUND 22 ALL PASS")


if __name__ == "__main__":
    main()
