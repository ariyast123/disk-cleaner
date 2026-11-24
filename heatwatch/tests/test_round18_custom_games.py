"""Round 18: custom games — add/remove in the UI, like GameMode has."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-custom-")
core.data_dir = lambda: TMP


def _fresh():
    return core.default_settings()


def test_add_valid():
    settings = _fresh()
    game, error = core.add_custom_game(
        settings, "Valorant", "valorant.exe, VALORANT-Win64-Shipping.exe")
    assert error is None, error
    assert game["name"] == "Valorant"
    assert game["patterns"] == ["valorant.exe",
                                "valorant-win64-shipping.exe"], game
    assert game["enabled"] is True and game["builtin"] is False
    assert len(settings["games"]) == 6
    assert core.match_games(["VALORANT.EXE"], settings["games"]) \
        == ["Valorant"]
    print("PASS a custom game is added, patterns lowered, and matched")


def test_add_rejects_bad_input():
    settings = _fresh()
    for name, patterns in (("", "x.exe"), ("   ", "x.exe"),
                           ("NoExe", ""), ("NoExe", " , , "),
                           ("NoExe", None), ("NoExe", 42)):
        game, error = core.add_custom_game(settings, name, patterns)
        assert game is None and error, (name, patterns, error)
    assert len(settings["games"]) == 5
    print("PASS empty names and empty process lists are rejected")


def test_add_rejects_duplicates():
    settings = _fresh()
    game, error = core.add_custom_game(settings, "rust", "rust.exe")
    assert game is None and "already on the watch list" in error, error
    game, error = core.add_custom_game(settings, "New Game", "a.exe")
    assert error is None, error
    game, error = core.add_custom_game(settings, "NEW GAME", "b.exe")
    assert game is None and "already on the watch list" in error, error
    assert len(settings["games"]) == 6
    print("PASS duplicate names (any case, incl. built-ins) rejected")


def test_remove_custom_only():
    settings = _fresh()
    core.add_custom_game(settings, "Valorant", "valorant.exe")
    assert core.remove_custom_game(settings, "valorant") is True
    assert len(settings["games"]) == 5
    assert core.remove_custom_game(settings, "Valorant") is False
    assert core.remove_custom_game(settings, "Rust") is False
    assert core.remove_custom_game(settings, "rust") is False
    assert core.remove_custom_game(settings, "") is False
    assert len(settings["games"]) == 5
    names = [g["name"] for g in settings["games"]]
    assert "Rust" in names and "Counter-Strike 2" in names
    print("PASS custom games remove; built-ins and unknown names stay")


def test_settings_round_trip():
    settings = _fresh()
    core.add_custom_game(settings, "Valorant", "valorant.exe")
    core.save_settings(settings)
    loaded = core.load_settings()
    custom = [g for g in loaded["games"] if g["name"] == "Valorant"]
    assert len(custom) == 1
    assert custom[0]["patterns"] == ["valorant.exe"]
    assert custom[0]["builtin"] is False
    assert all(g["builtin"] for g in loaded["games"]
               if g["name"] != "Valorant")
    print("PASS a custom game survives a save/load round trip")


def test_gui_add_and_remove():
    """Add form + remove button drive the real window."""
    import tkinter as tk
    try:
        # The round-trip test above saved a custom game to this
        # temp data dir; reset to defaults so the GUI starts clean.
        core.save_settings(core.default_settings())
        core.collect_temps = lambda port=8085: {
            "cpu": 60.0, "gpu": 55.0, "source": "LHM web"}
        core.running_process_names = lambda: set()
        import heatwatch_app as gui
        app = gui.HeatWatchApp()
    except tk.TclError:
        print("SKIP GUI part: no display available")
        return
    try:
        app.update()
        app._stop.set()
        time.sleep(0.2)
        app.update()
        names = [g["name"] for g in app.settings["games"]]
        assert len(names) == 5, names

        # The add form starts hidden; the button shows it.
        assert not app.add_form.winfo_ismapped()
        app._toggle_add_form()
        app.update()
        assert app.add_form.winfo_ismapped()

        app.new_name.insert(0, "Valorant")
        app.new_exes.insert(0, "valorant.exe")
        app._add_game()
        app.update()
        names = [g["name"] for g in app.settings["games"]]
        assert "Valorant" in names, names
        assert not app.add_form.winfo_ismapped()
        assert "Added Valorant" in app.log_label.cget("text")

        # A duplicate add is refused and logged, not added twice.
        app._toggle_add_form()
        app.new_name.insert(0, "Valorant")
        app.new_exes.insert(0, "valorant.exe")
        app._add_game()
        names = [g["name"] for g in app.settings["games"]]
        assert names.count("Valorant") == 1, names
        assert "already on the watch list" in app.log_label.cget("text")

        # Removing the custom game works; a built-in refuses.
        custom = next(g for g in app.settings["games"]
                      if g["name"] == "Valorant")
        app._remove_game(custom)
        names = [g["name"] for g in app.settings["games"]]
        assert "Valorant" not in names, names
        builtin = next(g for g in app.settings["games"]
                       if g["name"] == "Rust")
        app._remove_game(builtin)
        names = [g["name"] for g in app.settings["games"]]
        assert "Rust" in names, names
        print("PASS GUI: add form, duplicate refusal, custom "
              "remove, built-in protected")
    finally:
        app._stop.set()
        app.destroy()


def main():
    test_add_valid()
    test_add_rejects_bad_input()
    test_add_rejects_duplicates()
    test_remove_custom_only()
    test_settings_round_trip()
    test_gui_add_and_remove()
    print("ROUND 18 ALL PASS")


if __name__ == "__main__":
    main()
