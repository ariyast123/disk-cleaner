"""Round 13: per-session temperature graph — series capture,
thinning, and the pure chart geometry the window draws from."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def make():
    return core.SessionTracker(warn_cpu=95, warn_gpu=85,
                               debounce_seconds=10.0)


def run_session(tracker, ticks):
    """ticks: [(ts, cpu, gpu)] with the first one starting it."""
    events = []
    for ts, cpu, gpu in ticks:
        events.extend(tracker.update(ts, ["Rust"], cpu, gpu, "LHM web"))
    return events


def test_series_recorded():
    tracker = make()
    run_session(tracker, [(0, 60, 50), (3, 70, 55), (6, 80, 60),
                          (9, 97, 70)])
    current = tracker.current()
    assert current["series"] == [[0.0, 60, 50], [3.0, 70, 55],
                                 [6.0, 80, 60], [9.0, 97, 70]], \
        current["series"]
    print("PASS series keeps [elapsed, cpu, gpu] per tick")


def test_series_none_is_a_gap():
    tracker = make()
    run_session(tracker, [(0, 60, 50), (3, None, 55), (6, 80, None)])
    current = tracker.current()
    assert current["series"] == [[0.0, 60, 50], [3.0, None, 55],
                                 [6.0, 80, None]]
    print("PASS a missing reading stays None in the series, not a guess")


def test_series_in_finished_record():
    tracker = make()
    run_session(tracker, [(0, 60, 50), (3, 70, 55), (6, 80, 60)])
    events = tracker.update(20, [], 80, 60, "LHM web")
    assert events == []  # debounce first
    events = tracker.update(30, [], 80, 60, "LHM web")
    assert events and events[0][0] == "ended"
    record = events[0][1]
    # the debounce ticks are still session ticks, so they are
    # in the series too, up to the moment the session ends
    assert record["series"] == [[0.0, 60, 50], [3.0, 70, 55],
                                [6.0, 80, 60], [20.0, 80, 60],
                                [30.0, 80, 60]], \
        record["series"]
    json.dumps(record)  # must survive the history file round trip
    print("PASS finished records carry a JSON-safe series")


def test_series_thinning():
    tracker = make()
    ticks = [(float(i * 3), 70 + (i % 30), 60 + (i % 20))
             for i in range(2000)]
    run_session(tracker, ticks)
    series = tracker.current()["series"]
    assert len(series) <= core.SessionTracker.MAX_SERIES_POINTS, \
        len(series)
    assert series[0][0] == 0.0, series[0]
    assert series[-1][0] >= 5900, series[-1]
    elapsed = [point[0] for point in series]
    assert elapsed == sorted(elapsed) and len(set(elapsed)) == len(elapsed)
    print(f"PASS 2000 ticks thin to {len(series)} points, "
          "shape kept, order kept")


def test_chart_points_basics():
    samples = [[0.0, 60.0, 50.0], [300.0, 99.0, 80.0],
               [600.0, 90.0, 70.0]]
    geo = core.chart_points(samples, 640, 280, 95, 85)
    assert len(geo["cpu"]) == 3 and len(geo["gpu"]) == 3
    xs = [point[0] for point in geo["cpu"]]
    assert xs[0] == 44.0 and xs[-1] == 640 - 12, xs
    # hotter = higher on the canvas (smaller y)
    cpu_ys = [point[1] for point in geo["cpu"]]
    assert cpu_ys[1] < cpu_ys[0] and cpu_ys[1] < cpu_ys[2], cpu_ys
    assert geo["t_max"] == 600.0
    assert 14 <= geo["warn_cpu_y"] <= 280 - 26
    assert 14 <= geo["warn_gpu_y"] <= 280 - 26
    assert geo["warn_cpu_y"] < geo["warn_gpu_y"]  # 95C line above 85C
    assert geo["grid"] and all(mark % 25 == 0 for mark, _ in geo["grid"])
    print("PASS chart geometry: x spans the canvas, hotter is higher, "
          "warn lines ordered")


def test_chart_points_gaps_and_single():
    samples = [[0.0, None, 50.0], [60.0, 90.0, None],
               [120.0, 95.0, 70.0]]
    geo = core.chart_points(samples, 640, 280, 95, 85)
    assert len(geo["cpu"]) == 2 and len(geo["gpu"]) == 2
    single = core.chart_points([[0.0, 80.0, 70.0]], 640, 280, 95, 85)
    assert len(single["cpu"]) == 1 and single["t_max"] == 1.0
    print("PASS None leaves a gap per line; one sample cannot crash it")


def test_chart_points_hostile_and_empty():
    for junk in (None, [], {}, "nope", 42, [[1, 2]], [[0, "x", 1]],
                 [[-5, 80, 70]], [[0, None, None]]):
        geo = core.chart_points(junk, 640, 280, 95, 85)
        assert geo["cpu"] == [] and geo["gpu"] == [], junk
    old_record = {"game": "Rust", "peak_cpu": 99.0}  # pre-graph session
    geo = core.chart_points(old_record.get("series") or [], 640, 280,
                            95, 85)
    assert geo["cpu"] == [] and geo["t_max"] == 0.0
    print("PASS hostile and missing series yield an empty chart, "
          "never a raise")


def main():
    test_series_recorded()
    test_series_none_is_a_gap()
    test_series_in_finished_record()
    test_series_thinning()
    test_chart_points_basics()
    test_chart_points_gaps_and_single()
    test_chart_points_hostile_and_empty()
    print("ROUND 13 ALL PASS")


if __name__ == "__main__":
    main()
