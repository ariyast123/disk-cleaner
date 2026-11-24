"""Round 19: the idle baseline — record, window, cooldown, label."""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-idle-")
core.data_dir = lambda: TMP

IdleBaseline = core.IdleBaseline


def test_record_throttles_to_one_per_minute():
    base = IdleBaseline()
    assert base.record(1000.0, 48.0, 41.0) is True
    assert base.record(1030.0, 49.0, 42.0) is False  # too soon
    assert base.record(1059.0, 49.0, 42.0) is False  # still too soon
    assert base.record(1060.0, 49.0, 42.0) is True
    assert len(base.samples) == 2
    print("PASS idle samples are throttled to one per minute")


def test_none_samples_never_stored():
    base = IdleBaseline()
    assert base.record(1000.0, None, None) is False
    assert len(base.samples) == 0
    assert base.record(1000.0, 48.0, None) is True  # CPU only: kept
    assert base.record(1060.0, None, 41.0) is True  # GPU only: kept
    assert base.baseline(now=2000.0) == {
        "cpu": 48.0, "gpu": 41.0, "samples": 2}
    print("PASS a missing source stays 'none' — half samples keep "
          "their gap, empty ticks are dropped")


def test_cooldown_blocks_recording():
    base = IdleBaseline()
    assert base.record(1000.0, 48.0, 41.0,
                       blocked_until=1300.0) is False
    assert base.record(1300.0, 48.0, 41.0,
                       blocked_until=1300.0) is True
    assert len(base.samples) == 1
    print("PASS the five minutes after a session are not idle data")


def test_baseline_median_and_window():
    base = IdleBaseline()
    for offset, cpu, gpu in ((0, 46.0, 40.0), (60, 48.0, 41.0),
                             (120, 50.0, 42.0), (180, 44.0, 39.0)):
        assert base.record(100000.0 + offset, cpu, gpu)
    # An old sample, outside the 24 h window, must not move it.
    base.samples.insert(0, [100000.0 - 90000.0, 90.0, 90.0])
    result = base.baseline(now=100000.0 + 180)
    assert result == {"cpu": 47.0, "gpu": 40.5, "samples": 4}, result
    assert IdleBaseline().baseline(now=1000.0) == {
        "cpu": None, "gpu": None, "samples": 0}
    print("PASS the baseline is the 24 h median; old samples and "
          "empty baselines behave")


def test_prune_old_samples_and_cap():
    old = [[1000.0 + 60 * i, 48.0, 41.0] for i in range(5)]
    base = IdleBaseline(old)
    assert base.record(1000.0 + 8 * 86400, 47.0, 40.0) is True
    assert len(base.samples) == 1  # week-old points pruned
    many = [[2000.0 + 60 * i, 48.0, 41.0]
            for i in range(core.IDLE_MAX_SAMPLES + 10)]
    base = IdleBaseline(many)
    assert base.record(2000.0 + 60 * (core.IDLE_MAX_SAMPLES + 10),
                       47.0, 40.0) is True
    assert len(base.samples) == core.IDLE_MAX_SAMPLES
    print("PASS samples older than a week are pruned and the store "
          "stays capped")


def test_persistence_round_trip_and_hostile():
    base = IdleBaseline()
    base.record(1000.0, 48.0, 41.0)
    base.record(1060.0, 49.0, 42.0)
    core.save_idle_baseline(base)
    loaded = core.load_idle_baseline()
    assert loaded.samples == [[1000.0, 48.0, 41.0],
                              [1060.0, 49.0, 42.0]], loaded.samples
    # Garbage file -> an empty baseline, never a raise.
    with open(core.idle_path(), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert core.load_idle_baseline().samples == []
    # Malformed entries are skipped, good ones kept.
    with open(core.idle_path(), "w", encoding="utf-8") as fh:
        json.dump({"samples": [[1000.0, 48.0, 41.0], "junk",
                               [1000.0], [2000.0, "hot", None],
                               [-5.0, 48.0, 41.0]]}, fh)
    loaded = core.load_idle_baseline()
    assert loaded.samples == [[1000.0, 48.0, 41.0]], loaded.samples
    print("PASS idle data survives a save/load round trip; hostile "
          "files degrade to empty")


def test_format_idle_baseline():
    assert core.format_idle_baseline(
        {"cpu": None, "gpu": None, "samples": 0}) == \
        "Idle baseline: not enough idle data yet"
    text = core.format_idle_baseline(
        {"cpu": 48.0, "gpu": 41.0, "samples": 212})
    assert text == ("Idle baseline (last 24 h): CPU 48°C · GPU 41°C "
                    "(212 samples)"), text
    text = core.format_idle_baseline(
        {"cpu": 48.0, "gpu": None, "samples": 3})
    assert "CPU 48°C" in text and "GPU —" in text, text
    print("PASS the verdict-card line reads right, with and "
          "without data")


def test_gui_idle_recording_and_cooldown():
    """Idle ticks land in the baseline; post-game heat does not."""
    import tkinter as tk
    try:
        # The pure tests above saved idle data to this temp data
        # dir; reset it so the GUI starts with an empty baseline.
        core.save_idle_baseline(core.IdleBaseline())
        # No temperatures from the background thread: its ticks
        # must not plant idle samples of their own.
        core.collect_temps = lambda port=8085: {
            "cpu": None, "gpu": None, "source": "none"}
        core.running_process_names = lambda: set()
        import heatwatch_app as gui
        app = gui.HeatWatchApp()
    except tk.TclError:
        print("SKIP GUI part: no display available")
        return
    try:
        app.update()
        app._stop.set()
        time.sleep(0.2)
        app.update()
        assert "not enough idle data" in app.idle_label.cget("text")

        def idle_payload(now, cpu=48.0, gpu=41.0, events=None):
            return {"temps": {"cpu": cpu, "gpu": gpu,
                             "source": "LHM web"},
                    "games": [], "events": events or [],
                    "warned": False, "now": now}

        # Real-clock timestamps: the label's 24 h window is
        # measured against the wall clock.
        t0 = time.time()
        app._apply_sample(idle_payload(t0))
        app._apply_sample(idle_payload(t0 + 61))
        app._apply_sample(idle_payload(t0 + 122))
        assert len(app.idle.samples) == 3, app.idle.samples
        label = app.idle_label.cget("text")
        assert "CPU 48°C" in label and "(3 samples)" in label, label
        # 29 seconds after the last sample: throttled, not stored.
        app._apply_sample(idle_payload(t0 + 151))
        assert len(app.idle.samples) == 3

        record = {"game": "Rust", "start": t0, "end": t0 + 600.0,
                  "duration_s": 600.0, "samples": 1, "series": [],
                  "peak_cpu": 90.0, "peak_gpu": 80.0,
                  "sec_above_cpu": 0.0, "sec_above_gpu": 0.0,
                  "warn_cpu": 95, "warn_gpu": 85,
                  "sources": ["LHM web"]}
        app._apply_sample(idle_payload(t0 + 600, events=[
            ("ended", record)]))
        assert len(app.idle.samples) == 3  # the end tick is blocked
        # One minute after the session: still inside the cooldown.
        app._apply_sample(idle_payload(t0 + 660))
        assert len(app.idle.samples) == 3
        # Five minutes and a second after: idle again.
        app._apply_sample(idle_payload(t0 + 901))
        assert len(app.idle.samples) == 4
        assert "(4 samples)" in app.idle_label.cget("text")
        # The baseline survived a save/load round trip to disk.
        assert core.load_idle_baseline().samples == app.idle.samples
        print("PASS GUI: idle ticks build the baseline, the "
              "post-game cooldown keeps it clean")
    finally:
        app._stop.set()
        app.destroy()


def main():
    test_record_throttles_to_one_per_minute()
    test_none_samples_never_stored()
    test_cooldown_blocks_recording()
    test_baseline_median_and_window()
    test_prune_old_samples_and_cap()
    test_persistence_round_trip_and_hostile()
    test_format_idle_baseline()
    test_gui_idle_recording_and_cooldown()
    print("ROUND 19 ALL PASS")


if __name__ == "__main__":
    main()
