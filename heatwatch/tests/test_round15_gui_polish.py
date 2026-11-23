"""Round 15: GUI polish — gauges, orb, sparkline, severity dots."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-gui15-")
core.data_dir = lambda: TMP
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.history_path = lambda: os.path.join(TMP, "sessions.json")
core.log_path = lambda: os.path.join(TMP, "heatwatch.log")
core.collect_temps = lambda port=8085: {"cpu": None, "gpu": None,
                                        "source": "none"}
core.running_process_names = lambda: set()

import heatwatch_app as gui


def sample(cpu, gpu, events=None, now=None):
    return {"temps": {"cpu": cpu, "gpu": gpu, "source": "LHM web"},
            "games": [], "events": events or [], "warned": False,
            "now": now if now is not None else time.time()}


def main():
    app = gui.HeatWatchApp()
    try:
        app._stop.set()
        # Gauges follow the sample and take its severity color.
        app._apply_sample(sample(97.0, 60.0))
        assert abs(app.cpu_gauge.get() - 97.0 / 110.0) < 0.01, \
            app.cpu_gauge.get()
        assert abs(app.gpu_gauge.get() - 60.0 / 110.0) < 0.01
        assert str(app.cpu_gauge.cget("progress_color")) == gui.RED
        assert str(app.gpu_gauge.cget("progress_color")) == gui.GREEN
        print("PASS gauges fill and color by severity")

        # The buffer grows and the sparkline actually draws lines.
        for i in range(6):
            app._apply_sample(sample(80.0 + i, 60.0 + i,
                                     now=time.time() + i))
        assert len(app.buffer) >= 6
        app.update()
        drawn = app.spark.find_all()
        assert len(drawn) >= 3, drawn  # warn line + CPU + GPU lines
        print("PASS sparkline draws the warn line and both curves")

        # Orb: no source is faint, hot is red, session is cyan ring.
        app.latest = {"cpu": None, "gpu": None, "source": "none"}
        assert app._orb_state()[0] == gui.FAINT
        app.latest = {"cpu": 99.0, "gpu": 70.0, "source": "LHM web"}
        assert app._orb_state()[0] == gui.RED
        app.tracker.update(time.time(), ["Rust"], 90, 70, "LHM web")
        app.latest = {"cpu": 90.0, "gpu": 70.0, "source": "LHM web"}
        assert app._orb_state()[0] == gui.CYAN
        print("PASS orb state: faint idle-none, red hot, cyan in session")

        # History rows carry a severity dot colored by the peak.
        app.history = [{"game": "Rust", "start": 0, "duration_s": 1800,
                        "peak_cpu": 99.0, "peak_gpu": 80.0,
                        "warn_cpu": 95, "sec_above_cpu": 60.0,
                        "series": []}]
        app._refresh_history()
        texts = []

        def walk(widget):
            for child in widget.winfo_children():
                try:
                    texts.append((child.cget("text"),
                                  str(child.cget("text_color"))))
                except Exception:
                    pass
                walk(child)

        walk(app.history_frame)
        dots = [color for text, color in texts if text == "●"]
        assert dots and dots[0] == gui.RED, texts
        print("PASS history severity dot is red for a 99-degree peak")
    finally:
        app._stop.set()
        app.destroy()
    print("ROUND 15 ALL PASS")


if __name__ == "__main__":
    main()
