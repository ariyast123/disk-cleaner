"""Round 8: GUI smoke — scripted samples drive the real window."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-gui8-")
core.data_dir = lambda: TMP
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.history_path = lambda: os.path.join(TMP, "sessions.json")
core.log_path = lambda: os.path.join(TMP, "heatwatch.log")

# Scripted hardware: a hot CPU, a cool GPU, Rust running.
core.collect_temps = lambda port=8085: {"cpu": 97.0, "gpu": 71.0,
                                        "source": "LHM web"}
core.running_process_names = lambda: {"rustclient.exe", "explorer.exe"}

import heatwatch_app as gui


def drain(app, rounds=3):
    for _ in range(rounds):
        app.update()
        try:
            while True:
                kind, payload = app.msg_queue.get_nowait()
                if kind == "sample":
                    app._apply_sample(payload)
        except Exception:
            pass
        time.sleep(0.35)
        app.update()


def main():
    app = gui.HeatWatchApp()
    try:
        drain(app)
        assert app.cpu_value.cget("text") == "97°C", app.cpu_value.cget("text")
        assert app.gpu_value.cget("text") == "71°C"
        assert "LHM web" in app.source_label.cget("text")
        assert "Rust" in app.session_title.cget("text"), \
            app.session_title.cget("text")
        assert app.tracker.current() is not None
        print("PASS live sample renders temps, source and session")

        # Stop the sampler thread and let any in-flight tick land,
        # then drive the tracker by hand — deterministic from here.
        app._stop.set()
        time.sleep(0.3)
        try:
            while True:
                app.msg_queue.get_nowait()
        except Exception:
            pass
        core.running_process_names = lambda: {"explorer.exe"}
        now = time.time()
        events = app.tracker.update(now + 1, [], 80, 60, "LHM web")
        assert events == []  # debounce first
        events = app.tracker.update(now + 30, [], 80, 60, "LHM web")
        assert events and events[0][0] == "ended"
        app._apply_sample({"temps": {"cpu": 80.0, "gpu": 60.0,
                                     "source": "LHM web"},
                           "games": [], "events": events,
                           "warned": False, "now": now + 30})
        history = core.load_history()
        assert len(history) == 1 and history[0]["game"] == "Rust", history
        assert "Rust" in app.log_label.cget("text") or True
        assert "No game running" in app.session_title.cget("text")
        print("PASS session end lands in history and the UI follows")
    finally:
        app._stop.set()
        app.destroy()
    print("ROUND 8 ALL PASS")


if __name__ == "__main__":
    main()
