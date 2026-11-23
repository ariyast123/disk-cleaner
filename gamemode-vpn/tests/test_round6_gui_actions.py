"""Round 6 — GUI interactions: add/remove/toggle games, toggles, log (Xvfb)."""
import os
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-gui2-")
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.log_path = lambda: os.path.join(TMP, "gamemode.log")
core.history_path = lambda: os.path.join(TMP, "history.json")

import gamemode_vpn_app as gui


def make_app():
    app = gui.GameModeApp()
    app._stop.set()
    while not app.msg_queue.empty():
        app.msg_queue.get_nowait()
    app.update_idletasks()
    return app


def test_add_and_remove_game():
    app = make_app()
    try:
        app.new_name.insert(0, "Valorant")
        app.new_exes.insert(0, "valorant.exe, VALORANT-Win64-Shipping.exe")
        app._add_game()
        names = [g["name"] for g in app.settings["games"]]
        assert "Valorant" in names
        saved = core.load_settings()
        valorant = [g for g in saved["games"] if g["name"] == "Valorant"][0]
        assert valorant["patterns"] == ["valorant.exe", "valorant-win64-shipping.exe"]
        assert len(app.games_holder.winfo_children()) == 5

        # duplicate is refused (entries keep their text on refusal,
        # so clear them first — insert() would append to the old text)
        app.new_name.delete(0, "end")
        app.new_exes.delete(0, "end")
        app.new_name.insert(0, "Valorant")
        app.new_exes.insert(0, "valorant.exe")
        app._add_game()
        assert [g["name"] for g in app.settings["games"]].count("Valorant") == 1

        # missing process names is refused
        app.new_name.delete(0, "end")
        app.new_exes.delete(0, "end")
        app.new_name.insert(0, "Empty")
        app._add_game()
        assert "Empty" not in [g["name"] for g in app.settings["games"]]

        game = [g for g in app.settings["games"] if g["name"] == "Valorant"][0]
        app._remove_game(game)
        assert "Valorant" not in [g["name"] for g in app.settings["games"]]
        assert len(app.games_holder.winfo_children()) == 4
        print("PASS add / duplicate / invalid / remove game")
    finally:
        app.destroy()


def test_toggles_persist():
    app = make_app()
    try:
        game = app.settings["games"][0]
        var = tk.BooleanVar(app, value=False)
        app._toggle_game(game, var)
        assert core.load_settings()["games"][0]["enabled"] is False

        app.auto_launch_var.set(False)
        app._save_toggles()
        assert core.load_settings()["auto_launch_proton"] is False
        print("PASS toggles persist to settings.json")
    finally:
        app.destroy()


def test_add_form_toggle_and_log_cap():
    app = make_app()
    try:
        assert app.add_form.winfo_manager() == ""
        app._toggle_add_form()
        assert app.add_form.winfo_manager() == "pack"
        app._toggle_add_form()
        assert app.add_form.winfo_manager() == ""
        for i in range(15):
            app._log(f"line {i}")
        assert len(app._log_lines) == 9
        assert app._log_lines[-1].endswith("line 14")
        print("PASS add-form toggle + log capped at 9")
    finally:
        app.destroy()


def test_fmt_duration():
    assert gui.fmt_duration(0) == "00:00"
    assert gui.fmt_duration(65) == "01:05"
    assert gui.fmt_duration(599) == "09:59"
    assert gui.fmt_duration(3661) == "1:01:01"
    assert gui.fmt_duration(36000) == "10:00:00"
    print("PASS fmt_duration")


if __name__ == "__main__":
    test_add_and_remove_game()
    test_toggles_persist()
    test_add_form_toggle_and_log_cap()
    test_fmt_duration()
    print("ROUND 6: ALL PASS")
