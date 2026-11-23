"""Round 13 — GUI: new toggles persist, tray decision, Auto wiring (Xvfb)."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-gui13-")
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.log_path = lambda: os.path.join(TMP, "gamemode.log")

import gamemode_vpn_app as gui

CALLS = []


def fake_auto(action, backend=None, timeout=12.0):
    CALLS.append(action)
    return (True, f"clicked {action} in Proton")


def make_app():
    app = gui.GameModeApp()
    app._stop.set()
    while not app.msg_queue.empty():
        app.msg_queue.get_nowait()
    app.update_idletasks()
    return app


def wait_for_calls(n, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(CALLS) >= n:
            return True
        time.sleep(0.05)
    return False


def test_new_toggles_persist():
    app = make_app()
    try:
        app.auto_mode_var.set(False)
        app.tray_var.set(False)
        app._save_toggles()
        saved = core.load_settings()
        assert saved["auto_mode"] is False
        assert saved["minimize_to_tray"] is False
        print("PASS auto-mode + tray toggles persist")
    finally:
        app.destroy()


def test_tray_hide_decision():
    app = make_app()
    try:
        original = gui.TRAY_AVAILABLE
        try:
            gui.TRAY_AVAILABLE = False
            assert app._should_tray_hide() is False  # no tray stack: close quits
            gui.TRAY_AVAILABLE = True
            app.tray_var.set(True)                   # earlier tests saved False
            app._save_toggles()
            assert app._should_tray_hide() is True   # toggle on + tray available
            app.tray_var.set(False)
            app._save_toggles()
            assert app._should_tray_hide() is False  # user turned it off
        finally:
            gui.TRAY_AVAILABLE = original
        print("PASS tray hide decision (setting x availability)")
    finally:
        app.destroy()


def test_auto_wiring():
    core.auto_proton_action = fake_auto
    core.launch_proton = lambda settings=None: "fake-proton"
    app = make_app()
    try:
        app.settings["gone_debounce_seconds"] = 0
        app.settings["auto_mode"] = True
        app._apply_snapshot({"DeadLock"}, "protected")
        assert wait_for_calls(1), "auto disconnect was not attempted"
        assert CALLS == ["disconnect"]
        app._apply_snapshot({"DeadLock"}, "protected")   # same session: no repeat
        time.sleep(0.3)
        assert CALLS == ["disconnect"]
        app._apply_snapshot({"DeadLock"}, "bare")        # gaming
        app._apply_snapshot(set(), "bare")               # restore needed
        assert wait_for_calls(2), "auto connect was not attempted"
        assert CALLS == ["disconnect", "connect"]
        app._apply_snapshot(set(), "protected")          # restored
        assert app.engine.mode == "idle"
        # auto result logging path
        app._auto_result("disconnect", True, "clicked Disconnect in Proton")
        assert any("Auto mode: clicked Disconnect" in line for line in app._log_lines)
        app._auto_result("connect", False, "the Connect button was not found in Proton")
        assert any("Auto mode could not connect" in line for line in app._log_lines)
        print("PASS auto wiring: disconnect once, connect once, results logged")
    finally:
        app.destroy()


def test_auto_off_means_no_calls():
    core.auto_proton_action = fake_auto
    core.launch_proton = lambda settings=None: "fake-proton"
    CALLS.clear()
    app = make_app()
    try:
        app.settings["auto_mode"] = False
        app._apply_snapshot({"DeadLock"}, "protected")
        time.sleep(0.3)
        assert CALLS == []
        print("PASS auto mode off: no auto clicks attempted")
    finally:
        app.destroy()


if __name__ == "__main__":
    test_new_toggles_persist()
    test_tray_hide_decision()
    test_auto_wiring()
    test_auto_off_means_no_calls()
    print("ROUND 13: ALL PASS")
