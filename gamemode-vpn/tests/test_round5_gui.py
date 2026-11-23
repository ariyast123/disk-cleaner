"""Round 5 — GUI smoke + simulated session flow (needs Xvfb)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-gui-")
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.log_path = lambda: os.path.join(TMP, "gamemode.log")

import gamemode_vpn_app as gui


def make_app():
    app = gui.GameModeApp()
    app._stop.set()                      # freeze the real watcher
    while not app.msg_queue.empty():
        app.msg_queue.get_nowait()
    app.update_idletasks()
    return app


def test_build_and_rows():
    app = make_app()
    try:
        assert app.title() == "GameMode VPN"
        rows = app.games_holder.winfo_children()
        assert len(rows) == 4, len(rows)  # the four built-in games
        assert app.status_headline.cget("text") in (
            "CHECKING…", "PROTECTED", "UNPROTECTED", "BLOCKED")
        print("PASS build + game rows")
    finally:
        app.destroy()


def test_simulated_session():
    app = make_app()
    try:
        app.settings["gone_debounce_seconds"] = 0
        app._apply_snapshot({"Counter-Strike 2"}, "protected")
        app.update_idletasks()
        assert app.engine.mode == "action_needed"
        assert app.status_headline.cget("text") == "ACTION NEEDED"
        assert len(app.action_steps.winfo_children()) == 3
        assert app.info_rows["vpn"].cget("text") == "Connected"
        assert app.info_rows["ks"].cget("text") == "On (Advanced)"

        app._apply_snapshot({"Counter-Strike 2"}, "blocked")
        assert len(app.action_steps.winfo_children()) == 4  # blocked step list

        app._apply_snapshot({"Counter-Strike 2"}, "bare")
        app.update_idletasks()
        assert app.engine.mode == "gaming"
        assert app.status_headline.cget("text") == "GAME MODE"
        assert len(app.action_steps.winfo_children()) == 0  # panel cleared

        app._apply_snapshot(set(), "bare")
        app.update_idletasks()
        assert app.engine.mode == "restore_needed"
        assert app.status_headline.cget("text") == "RESTORE VPN"
        assert len(app.action_steps.winfo_children()) == 3

        app._apply_snapshot(set(), "protected")
        app.update_idletasks()
        assert app.engine.mode == "idle"
        assert app.status_headline.cget("text") == "PROTECTED"
        assert any("Protected again" in line for line in app._log_lines)
        print("PASS simulated session flow")
    finally:
        app.destroy()


def test_manual_restore():
    app = make_app()
    try:
        app._apply_snapshot(set(), "bare")
        app.update_idletasks()
        assert app.status_headline.cget("text") == "UNPROTECTED"
        app._restore_clicked()   # Proton is absent in the sandbox: launch logs a miss, harmless
        app.update_idletasks()
        assert app.manual_restore is True
        assert app.status_headline.cget("text") == "RESTORE VPN"
        assert len(app.action_steps.winfo_children()) == 3
        app._apply_snapshot(set(), "protected")
        app.update_idletasks()
        assert app.manual_restore is False
        assert app.status_headline.cget("text") == "PROTECTED"
        print("PASS manual restore flow")
    finally:
        app.destroy()


if __name__ == "__main__":
    test_build_and_rows()
    test_simulated_session()
    test_manual_restore()
    print("ROUND 5: ALL PASS")
