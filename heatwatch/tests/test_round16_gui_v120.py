"""Round 16: GUI v1.2.0 — header state, chips, dots, verdict border."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-gui16-")
core.data_dir = lambda: TMP
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.history_path = lambda: os.path.join(TMP, "sessions.json")
core.log_path = lambda: os.path.join(TMP, "heatwatch.log")
core.collect_temps = lambda port=8085: {"cpu": None, "gpu": None,
                                        "source": "none"}
core.running_process_names = lambda: set()

import heatwatch_app as gui


def sample(cpu, gpu, source="LHM web", games=None, now=None):
    return {"temps": {"cpu": cpu, "gpu": gpu, "source": source},
            "games": games or [], "events": [], "warned": False,
            "now": now if now is not None else time.time()}


def main():
    app = gui.HeatWatchApp()
    try:
        app._stop.set()
        # No source: the header says so, in faint.
        app._apply_sample(sample(None, None, source="none"))
        assert app.state_label.cget("text") == "WAITING FOR SENSORS"
        assert str(app.state_label.cget("text_color")) == gui.FAINT
        print("PASS header waits for sensors when there is no source")

        # Idle with a source.
        app._apply_sample(sample(60.0, 50.0))
        assert app.state_label.cget("text") == "IDLE — WATCHING"
        print("PASS header idles with a live source")

        # In session: header names the game, its dot lights, chips fill.
        # (The tracker records peaks from the second tick onward.)
        now = time.time()
        app.tracker.update(now, ["Rust"], 97.0, 80.0, "LHM web")
        app.tracker.update(now + 3, ["Rust"], 97.0, 80.0, "LHM web")
        app._apply_sample(sample(97.0, 80.0, games=["Rust"], now=now))
        assert app.state_label.cget("text") == "IN SESSION — Rust"
        assert str(app.state_label.cget("text_color")) == gui.RED  # hot
        assert str(app.game_dots["Rust"].cget("text_color")) == \
            gui.GREEN
        assert str(app.game_dots["Deadlock"].cget("text_color")) == \
            gui.FAINT
        assert "97°" in app.chip_peak_cpu.cget("text")
        assert "80°" in app.chip_peak_gpu.cget("text")
        print("PASS session: header, running dot and chips all live")

        # Sparkline carries end labels for both lines. (Drain the
        # sampler's queue first so a stale tick cannot redraw over
        # the sample applied here.)
        while not app.msg_queue.empty():
            app.msg_queue.get()
        app._apply_sample(sample(97.0, 80.0, games=["Rust"], now=now))
        app.update()
        texts = [app.spark.itemcget(item, "text")
                 for item in app.spark.find_all()
                 if app.spark.type(item) == "text"]
        assert any(t.startswith("CPU") for t in texts), texts
        assert any(t.startswith("GPU") for t in texts), texts
        print("PASS sparkline labels the current CPU and GPU values")

        # Verdict border follows the verdict: five hot full sessions.
        app.history = [
            {"game": "Rust", "start": 1000 + i * 10000,
             "duration_s": 1800, "peak_cpu": 99.0, "peak_gpu": 80.0,
             "warn_cpu": 95, "sec_above_cpu": 60.0, "series": []}
            for i in range(5)]
        app._refresh_history()
        assert str(app.verdict_card.cget("border_color")) == gui.RED
        print("PASS verdict card border turns red when repaste is due")
    finally:
        app._stop.set()
        app.destroy()
    print("ROUND 16 ALL PASS")


if __name__ == "__main__":
    main()
