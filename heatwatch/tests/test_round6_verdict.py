"""Round 6: history persistence + the repaste verdict."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-hist-")
core.data_dir = lambda: TMP


def record(peak_cpu, duration=1800):
    return {"game": "Rust", "start": 0, "end": duration,
            "duration_s": duration, "peak_cpu": peak_cpu,
            "peak_gpu": 80.0, "sec_above_cpu": 0.0,
            "sec_above_gpu": 0.0, "samples": 100, "sources": []}


def test_append_and_load():
    assert core.load_history() == []
    core.append_history(record(90))
    core.append_history(record(99))
    history = core.load_history()
    assert [h["peak_cpu"] for h in history] == [90, 99]
    print("PASS history appends and reloads in order")


def test_corrupt_history():
    with open(core.history_path(), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert core.load_history() == []
    print("PASS a corrupt history file reads as empty, never raises")


def test_verdict_levels():
    assert core.verdict([])["level"] == "unknown"
    assert core.verdict([record(99, duration=300)])["level"] == "unknown"
    healthy = [record(88), record(91), record(90)]
    assert core.verdict(healthy)["level"] == "healthy"
    hot = [record(96), record(97), record(95)]
    result = core.verdict(hot)
    assert result["level"] == "hot" and result["median_peak_cpu"] == 96
    due = [record(99), record(100), record(98), record(99), record(97)]
    result = core.verdict(due)
    assert result["level"] == "repaste", result
    assert result["sessions_used"] == 5
    print("PASS verdict: unknown / healthy / hot / repaste boundaries")


def test_verdict_follows_warning_line():
    # The default line is 95: a 93 median stays healthy.
    assert core.verdict([record(93)])["level"] == "healthy"
    # Lower the line to 90 and the same peaks are judged harder:
    # at the line is hot, 3 past it is repaste.
    assert core.verdict([record(93)], warn_cpu=90)["level"] == "repaste"
    assert core.verdict([record(91)], warn_cpu=90)["level"] == "hot"
    assert core.verdict([record(90)], warn_cpu=90)["level"] == "hot"
    assert core.verdict([record(89)], warn_cpu=90)["level"] == "healthy"
    assert core.verdict([record(93)], warn_cpu=90)["warn_cpu"] == 90
    print("PASS verdict follows the user's CPU warning line")


def test_verdict_window():
    history = [record(100)] * 5 + [record(80)] * 5
    result = core.verdict(history)
    assert result["level"] == "healthy", result
    print("PASS the verdict judges the recent window, not old sins")


def main():
    test_append_and_load()
    test_corrupt_history()
    test_verdict_levels()
    test_verdict_follows_warning_line()
    test_verdict_window()
    print("ROUND 6 ALL PASS")


if __name__ == "__main__":
    main()
