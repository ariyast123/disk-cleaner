"""Round 24: the tick that starts a session is its first sample.

Before this fix the starting tick was dropped: the session
began on that tick but its temperatures, fan reading and
source never reached the peaks, the series, the fan range
or the sample count, so a hot start tick never showed up
in the peak or the graph. The start tick now counts, with
its over-line clock at zero — the gap since the previous
idle poll is not over-line time.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def make():
    return core.SessionTracker(warn_cpu=95, warn_gpu=85,
                               debounce_seconds=10.0)


def test_start_tick_is_a_sample():
    tracker = make()
    events = tracker.update(0, ["Rust"], 70, 55, "LHM web", fan=1500.0)
    assert events == [("started", "Rust")], events
    current = tracker.current()
    assert current["samples"] == 1, current
    assert current["peak_cpu"] == 70 and current["peak_gpu"] == 55
    assert current["fan_low"] == 1500.0
    assert current["fan_peak"] == 1500.0
    assert current["series"] == [[0.0, 70, 55]], current["series"]
    assert current["sources"] == ["LHM web"]
    print("PASS the start tick counts: peak, series, fan, source")


def test_hot_start_tick_is_not_lost():
    tracker = make()
    tracker.update(0, ["Rust"], 99, 88, "LHM web")
    tracker.update(3, ["Rust"], 80, 60, "LHM web")
    tracker.update(6, ["Rust"], 82, 61, "LHM web")
    current = tracker.current()
    assert current["peak_cpu"] == 99 and current["peak_gpu"] == 88, \
        current
    assert current["series"][0] == [0.0, 99, 88], current["series"]
    print("PASS a hot start tick survives as the session peak")


def test_start_tick_adds_no_over_line_time():
    tracker = make()
    tracker.update(0, [], 60, 50, "LHM web")
    # The game starts an hour later, already over the line:
    # the idle gap is not session time, so nothing is added.
    tracker.update(3600, ["Rust"], 99, 88, "LHM web")
    current = tracker.current()
    assert current["sec_above_cpu"] == 0.0, current
    assert current["sec_above_gpu"] == 0.0, current
    tracker.update(3603, ["Rust"], 99, 88, "LHM web")
    current = tracker.current()
    assert current["sec_above_cpu"] == 3.0, current
    assert current["sec_above_gpu"] == 3.0, current
    print("PASS the start tick's over-line clock starts at zero")


def test_start_tick_without_temps():
    tracker = make()
    events = tracker.update(0, ["Rust"], None, None, "none")
    assert events == [("started", "Rust")], events
    current = tracker.current()
    assert current["samples"] == 1, current
    assert current["peak_cpu"] is None and current["peak_gpu"] is None
    assert current["series"] == [[0.0, None, None]], current["series"]
    print("PASS a start tick with no source still counts as a sample")


def test_start_tick_in_finished_record():
    tracker = make()
    tracker.update(0, ["Rust"], 70, 55, "LHM web", fan=1500.0)
    tracker.update(3, ["Rust"], 80, 60, "LHM web", fan=2000.0)
    tracker.update(6, [], 80, 60, "LHM web")
    events = tracker.update(16, [], 80, 60, "LHM web")
    assert len(events) == 1 and events[0][0] == "ended", events
    record = events[0][1]
    assert record["samples"] == 4, record
    assert record["series"][0] == [0.0, 70, 55], record["series"]
    assert record["peak_cpu"] == 80 and record["peak_gpu"] == 60
    assert record["fan_low"] == 1500 and record["fan_peak"] == 2000
    assert record["duration_s"] == 16.0, record
    print("PASS the finished record keeps the start tick")


def main():
    test_start_tick_is_a_sample()
    test_hot_start_tick_is_not_lost()
    test_start_tick_adds_no_over_line_time()
    test_start_tick_without_temps()
    test_start_tick_in_finished_record()
    print("ROUND 24 ALL PASS")


if __name__ == "__main__":
    main()
