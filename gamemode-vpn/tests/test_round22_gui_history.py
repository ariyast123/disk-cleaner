"""Round 22 — Session history in the GUI (needs Xvfb)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-gui-hist-")
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


def history_text(app):
    return app.history_box.get("1.0", "end")


def test_empty_history_message():
    app = make_app()
    try:
        assert "No sessions yet" in history_text(app)
        print("PASS empty history message")
    finally:
        app.destroy()


def test_session_appears_after_game_ends():
    app = make_app()
    try:
        app.settings["gone_debounce_seconds"] = 0
        app._apply_snapshot({"Counter-Strike 2"}, "protected")
        app._apply_snapshot({"Counter-Strike 2"}, "bare")
        assert app.engine.mode == "gaming"
        app._apply_snapshot(set(), "bare")
        app.update_idletasks()
        assert app.engine.mode == "restore_needed"
        entries = core.load_history()
        assert len(entries) == 1, entries
        assert entries[0]["games"] == ["Counter-Strike 2"]
        assert entries[0]["game_mode_on"] is True
        assert entries[0]["restore_needed"] is True
        text = history_text(app)
        assert "Counter-Strike 2" in text, text
        assert "Game Mode on" in text, text
        assert "restore needed" in text, text
        print("PASS session appears in history after the game ends")
    finally:
        app.destroy()


def test_history_survives_restart():
    # a fresh history file, so earlier tests' sessions cannot leak in
    tmp = tempfile.mkdtemp(prefix="gmvpn-gui-hist2-")
    core.history_path = lambda: os.path.join(tmp, "history.json")
    app = make_app()
    try:
        app.settings["gone_debounce_seconds"] = 0
        app._apply_snapshot({"Rust"}, "bare")
        app._apply_snapshot(set(), "bare")
        app.update_idletasks()
        assert len(core.load_history()) == 1
    finally:
        app.destroy()
    # a fresh launch reads the saved file back
    app = make_app()
    try:
        text = history_text(app)
        assert "Rust" in text, text
        assert "no restore needed" in text, text
        print("PASS history survives an app restart")
    finally:
        app.destroy()


if __name__ == "__main__":
    test_empty_history_message()
    test_session_appears_after_game_ends()
    test_history_survives_restart()
    print("ROUND 22: ALL PASS")
