"""Round 21: GUI — the LHM autostart helper dialog."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-gui21-")
core.data_dir = lambda: TMP
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.history_path = lambda: os.path.join(TMP, "sessions.json")
core.log_path = lambda: os.path.join(TMP, "heatwatch.log")
core.collect_temps = lambda port=8085: {"cpu": None, "gpu": None,
                                        "source": "none"}
core.running_process_names = lambda: set()

import heatwatch_app as gui

FAKE_LHM = (r"C:\Program Files\LibreHardwareMonitor"
            r"\LibreHardwareMonitor.exe")


def find_button(root, text):
    for widget in root.winfo_children():
        if isinstance(widget, gui.ctk.CTkButton) \
                and widget.cget("text") == text:
            return widget
        found = find_button(widget, text)
        if found is not None:
            return found
    return None


def pump(app):
    """Let worker threads post, then drain the queue twice
    (setup results chain into a status re-check)."""
    time.sleep(0.4)
    app.update()
    app._drain_queue()
    time.sleep(0.4)
    app.update()
    app._drain_queue()


def main():
    real_is_windows = core.is_windows
    real_find = core.find_lhm_exe
    real_exists = core.lhm_task_exists
    real_create = core.create_lhm_task
    real_remove = core.remove_lhm_task
    state = {"exists": False}
    core.is_windows = lambda: True
    core.find_lhm_exe = lambda settings: FAKE_LHM
    core.lhm_task_exists = lambda runner=None: state["exists"]
    core.create_lhm_task = lambda exe, runner=None: (
        True, "LibreHardwareMonitor will now start at every sign-in")
    core.remove_lhm_task = lambda runner=None: (
        True, "LHM autostart removed")
    app = gui.HeatWatchApp()
    try:
        pump(app)
        assert app._lhm_autostart_label.cget("text") == \
            "LHM autostart: off", \
            app._lhm_autostart_label.cget("text")
        print("PASS settings card shows the autostart state at "
              "startup")

        button = find_button(app, "Set up LHM to start at boot…")
        assert button is not None
        button.invoke()
        pump(app)
        assert app._lhm_dialog is not None
        assert app._lhm_status_label.cget("text") == \
            "Status: not set up yet.", \
            app._lhm_status_label.cget("text")
        assert app._lhm_setup_button.cget("state") == "normal"
        assert app._lhm_remove_button.cget("state") == "disabled"
        print("PASS dialog opens and reports not-set-up with the "
              "right buttons enabled")

        state["exists"] = True
        app._lhm_setup_button.invoke()
        pump(app)
        assert "every sign-in" in app.log_label.cget("text")
        assert app._lhm_status_label.cget("text").startswith(
            "Status: set up"), app._lhm_status_label.cget("text")
        assert app._lhm_setup_button.cget("state") == "disabled"
        assert app._lhm_remove_button.cget("state") == "normal"
        assert app._lhm_autostart_label.cget("text") == \
            "LHM autostart: on"
        print("PASS setup flips the dialog and the settings label "
              "to on")

        state["exists"] = False
        app._lhm_remove_button.invoke()
        pump(app)
        assert app._lhm_status_label.cget("text") == \
            "Status: not set up yet."
        assert app._lhm_setup_button.cget("state") == "normal"
        assert app._lhm_remove_button.cget("state") == "disabled"
        assert app._lhm_autostart_label.cget("text") == \
            "LHM autostart: off"
        print("PASS remove flips everything back to off")

        app._close_lhm_dialog()
        core.find_lhm_exe = lambda settings: None
        button.invoke()
        app.update()
        assert "was not found" in app._lhm_status_label.cget("text")
        assert app._lhm_setup_button.cget("state") == "disabled"
        assert app._lhm_remove_button.cget("state") == "disabled"
        print("PASS without LHM installed the dialog says so and "
              "offers no dead buttons")
    finally:
        core.is_windows = real_is_windows
        core.find_lhm_exe = real_find
        core.lhm_task_exists = real_exists
        core.create_lhm_task = real_create
        core.remove_lhm_task = real_remove
        app._stop.set()
        app.destroy()
    print("ROUND 21 ALL PASS")


if __name__ == "__main__":
    main()
