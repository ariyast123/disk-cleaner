"""Round 11: GUI actions — settings form, game toggles, verdict."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-gui11-")
core.data_dir = lambda: TMP
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.history_path = lambda: os.path.join(TMP, "sessions.json")
core.log_path = lambda: os.path.join(TMP, "heatwatch.log")
core.collect_temps = lambda port=8085: {"cpu": None, "gpu": None,
                                        "source": "none"}
core.running_process_names = lambda: set()

import heatwatch_app as gui


def set_entry(entry, text):
    entry.delete(0, "end")
    entry.insert(0, text)


def main():
    app = gui.HeatWatchApp()
    try:
        app._stop.set()
        set_entry(app.warn_cpu_entry, "97")
        set_entry(app.warn_gpu_entry, "88")
        set_entry(app.poll_entry, "5")
        set_entry(app.port_entry, "9999")
        app._save_settings_form()
        assert app.settings["warn_cpu_c"] == 97
        assert app.settings["warn_gpu_c"] == 88
        assert app.settings["poll_seconds"] == 5.0
        assert app.settings["lhm_port"] == 9999
        assert app.tracker.warn_cpu == 97 and app.warner.warn_c == 97
        saved = core.load_settings()
        assert saved["warn_cpu_c"] == 97 and saved["lhm_port"] == 9999
        print("PASS settings form persists and retunes the engine")

        set_entry(app.warn_cpu_entry, "banana")
        app._save_settings_form()
        assert app.settings["warn_cpu_c"] == 97
        print("PASS garbage form input keeps the current value")

        before = [g for g in app.settings["games"]
                  if g["name"] == "Rust"][0]["enabled"]
        app._toggle_game("Rust")
        after = [g for g in app.settings["games"]
                 if g["name"] == "Rust"][0]["enabled"]
        assert after == (not before)
        assert core.load_settings()["games"][1]["enabled"] == after
        print("PASS game toggle flips and persists")

        app.history = [{"game": "Rust", "start": 0, "duration_s": 1800,
                        "peak_cpu": 99.0, "peak_gpu": 80.0,
                        "sec_above_cpu": 60.0}] * 3
        app._refresh_history()
        assert "Repaste is due" in app.verdict_title.cget("text"), \
            app.verdict_title.cget("text")
        print("PASS verdict card shows repaste-due on hot history")

        record = {"game": "Rust", "start": 1700000000,
                  "duration_s": 900, "peak_cpu": 99.0, "peak_gpu": 80.0,
                  "sec_above_cpu": 60.0, "warn_cpu": 95, "warn_gpu": 85,
                  "series": [[0.0, 70.0, 60.0], [300.0, 99.0, 80.0],
                             [600.0, 90.0, 75.0], [900.0, 85.0, 70.0]]}
        app.history = [record]
        app._refresh_history()
        buttons = []
        for row in app.history_frame.winfo_children():
            for child in row.winfo_children():
                if isinstance(child, gui.ctk.CTkButton):
                    buttons.append(child)
        assert len(buttons) == 1
        assert buttons[0].cget("text") == "Graph"
        buttons[0].invoke()
        app.update()
        graphs = [w for w in app.winfo_children()
                  if isinstance(w, gui.ctk.CTkToplevel)]
        assert len(graphs) == 1
        graph = graphs[0]
        import tkinter as tk
        canvases = [w for w in graph.winfo_children()
                    if isinstance(w, tk.Canvas)]
        assert len(canvases) == 1
        assert len(canvases[0].find_all()) > 5  # grid + warn + curves
        graph.destroy()
        print("PASS Graph button opens a window with the drawn curves")

        app._show_session_graph({"game": "Rust", "start": 0,
                                 "duration_s": 600, "peak_cpu": 90.0,
                                 "peak_gpu": 70.0})
        app.update()
        graphs = [w for w in app.winfo_children()
                  if isinstance(w, gui.ctk.CTkToplevel)]
        assert len(graphs) == 1
        labels = [w.cget("text") for w in graphs[0].winfo_children()
                  if isinstance(w, gui.ctk.CTkLabel)]
        assert any("No temperature samples" in text for text in labels)
        graphs[0].destroy()
        print("PASS a pre-graph session says so instead of drawing "
              "nothing")

        app.history = [dict(record, series=None)]
        app._refresh_history()
        buttons = [child for row in app.history_frame.winfo_children()
                   for child in row.winfo_children()
                   if isinstance(child, gui.ctk.CTkButton)]
        assert buttons == []
        print("PASS a session without a series gets no Graph button")
    finally:
        app._stop.set()
        app.destroy()
    print("ROUND 11 ALL PASS")


if __name__ == "__main__":
    main()
