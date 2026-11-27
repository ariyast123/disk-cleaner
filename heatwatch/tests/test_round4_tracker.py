"""Round 4: the session tracker state machine."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def make():
    return core.SessionTracker(warn_cpu=95, warn_gpu=85,
                               debounce_seconds=10.0)


def test_full_session():
    tracker = make()
    assert tracker.update(0, [], 60, 50) == []
    events = tracker.update(1, ["Rust"], 70, 55, "LHM web")
    assert events == [("started", "Rust")], events
    tracker.update(4, ["Rust"], 97, 80, "LHM web")
    tracker.update(9, ["Rust"], 99, 90, "LHM web")
    tracker.update(19, ["Rust"], 90, 70, "LHM web")
    current = tracker.current()
    assert current["peak_cpu"] == 99 and current["peak_gpu"] == 90
    assert current["sec_above_cpu"] == 8.0, current
    assert current["sec_above_gpu"] == 5.0, current
    assert tracker.update(20, [], 80, 60) == []
    assert tracker.update(29, [], 80, 60) == []
    events = tracker.update(30, [], 80, 60)
    assert len(events) == 1 and events[0][0] == "ended", events
    record = events[0][1]
    assert record["game"] == "Rust"
    assert record["duration_s"] == 29.0, record
    assert record["peak_cpu"] == 99 and record["samples"] >= 4
    assert record["sources"] == ["LHM web"]
    assert tracker.current() is None
    print("PASS full session: start, peaks, over-line seconds, end")


def test_flap_inside_debounce():
    tracker = make()
    tracker.update(0, ["Rust"], 70, 50)
    tracker.update(5, [], 70, 50)
    events = tracker.update(8, ["Rust"], 71, 50)
    assert events == [], events
    assert tracker.current() is not None
    print("PASS a 3-second flap does not split the session")


def test_dt_cap():
    tracker = make()
    tracker.update(0, ["Rust"], 99, 50)
    tracker.update(3600, ["Rust"], 99, 50)
    current = tracker.current()
    assert current["sec_above_cpu"] == 30.0, current
    print("PASS a sleep gap cannot inflate over-line time (30 s cap)")


def test_no_temps_still_a_session():
    tracker = make()
    tracker.update(0, ["Rust"], None, None, "none")
    tracker.update(5, ["Rust"], None, None, "none")
    current = tracker.current()
    assert current["peak_cpu"] is None and current["samples"] == 2
    print("PASS sessions survive a missing temperature source")


def main():
    test_full_session()
    test_flap_inside_debounce()
    test_dt_cap()
    test_no_temps_still_a_session()
    print("ROUND 4 ALL PASS")


if __name__ == "__main__":
    main()
