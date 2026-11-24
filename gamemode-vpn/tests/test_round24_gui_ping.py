"""Round 24 (GUI) — Ping proof in the UI (needs Xvfb)."""
import os
import queue
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-gui-ping-")
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.log_path = lambda: os.path.join(TMP, "gamemode.log")
core.history_path = lambda: os.path.join(TMP, "history.json")

import gamemode_vpn_app as gui


def make_app():
    app = gui.GameModeApp()
    app._stop.set()                      # freeze the real watcher
    while not app.msg_queue.empty():
        app.msg_queue.get_nowait()
    app.update_idletasks()
    return app


def ping_text(app):
    return app.info_rows["ping"].cget("text")


def drain_ping_result(app, timeout=2.0):
    """Wait for the worker thread's ping_result, then run the drain."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            item = app.msg_queue.get_nowait()
        except queue.Empty:
            time.sleep(0.05)
            continue
        if item[0] == "ping_result":
            app._apply_ping_result(item[1])
            return item[1]
    raise AssertionError("no ping_result arrived from the worker thread")


def test_ping_row_off_by_default():
    app = make_app()
    try:
        assert "ping" in app.info_rows
        app._refresh_status()  # first render: before any snapshot the row is "—"
        assert ping_text(app) == "off"
        assert app.settings["ping_proof"] is False
        print("PASS ping row exists and reads 'off' by default")
    finally:
        app.destroy()


def test_ping_measured_when_game_mode_turns_on():
    app = make_app()
    try:
        app.settings["ping_proof"] = True
        app.settings["ping_host"] = "1.1.1.1"
        app.settings["gone_debounce_seconds"] = 0
        seen_hosts = []
        original_measure = core.measure_ping
        core.measure_ping = lambda host: seen_hosts.append(host) or 12
        try:
            app._apply_snapshot({"Counter-Strike 2"}, "protected")
            app._apply_snapshot({"Counter-Strike 2"}, "bare")
            assert app.engine.mode == "gaming"
            assert ping_text(app) == "measuring…", ping_text(app)
            assert drain_ping_result(app) == 12
            assert seen_hosts == ["1.1.1.1"], seen_hosts
            app.update_idletasks()
            assert ping_text(app) == "12 ms", ping_text(app)
            assert "12 ms" in app.status_sub.cget("text"), app.status_sub.cget("text")
            assert app.engine.session_ping_ms == 12
            print("PASS ping is measured at Game Mode on and shown in the sidebar")
        finally:
            core.measure_ping = original_measure
    finally:
        app.destroy()


def test_ping_no_answer():
    app = make_app()
    try:
        app.settings["ping_proof"] = True
        app.settings["gone_debounce_seconds"] = 0
        app._apply_snapshot({"Rust"}, "bare")
        assert app.engine.mode == "gaming"
        app._apply_ping_result(None)
        assert ping_text(app) == "no answer", ping_text(app)
        assert app.engine.session_ping_ms is None
        print("PASS an unanswered ping shows 'no answer', never a guess")
    finally:
        app.destroy()


def test_ping_saved_in_history():
    app = make_app()
    try:
        app.settings["ping_proof"] = True
        app.settings["gone_debounce_seconds"] = 0
        app._apply_snapshot({"Rust"}, "bare")
        app._apply_ping_result(9)
        app._apply_snapshot(set(), "bare")
        app.update_idletasks()
        entries = core.load_history()
        assert len(entries) == 1 and entries[0]["ping_ms"] == 9, entries
        text = app.history_box.get("1.0", "end")
        assert "ping 9 ms" in text, text
        # and the sidebar goes back to a dash once the session is over
        assert ping_text(app) == "—", ping_text(app)
        print("PASS ping lands in the session history and the row resets")
    finally:
        app.destroy()


def test_ping_settings_saved():
    app = make_app()
    try:
        app.ping_proof_var.set(True)
        app._save_toggles()
        app.ping_host_var.set("  1.1.1.1  ")
        app._save_ping_host()
        assert app.ping_host_var.get() == "1.1.1.1"  # cleaned back into the entry
        loaded = core.load_settings()
        assert loaded["ping_proof"] is True
        assert loaded["ping_host"] == "1.1.1.1"
        # a hostile host is cleaned to the default on save
        app.ping_host_var.set("8.8.8.8; evil")
        app._save_ping_host()
        assert core.load_settings()["ping_host"] == "8.8.8.8"
        print("PASS ping switch + host save and round-trip through settings")
    finally:
        app.destroy()


if __name__ == "__main__":
    test_ping_row_off_by_default()
    test_ping_measured_when_game_mode_turns_on()
    test_ping_no_answer()
    test_ping_saved_in_history()
    test_ping_settings_saved()
    print("ROUND 24 GUI: ALL PASS")
