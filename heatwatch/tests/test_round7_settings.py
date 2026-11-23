"""Round 7: settings normalization + persistence."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-set-")
core.data_dir = lambda: TMP


def test_defaults_on_garbage():
    for junk in (None, "x", 42, [], {"poll_seconds": "abc"}):
        settings = core.normalize_settings(junk)
        assert settings["poll_seconds"] == 3.0
        assert settings["warn_cpu_c"] == 95
        assert len(settings["games"]) == 5
    print("PASS garbage settings fall back to sane defaults")


def test_clamps():
    settings = core.normalize_settings({
        "poll_seconds": 999, "warn_cpu_c": 500, "warn_gpu_c": -3,
        "lhm_port": 0, "gone_debounce_seconds": -1})
    assert settings["poll_seconds"] == 30.0
    assert settings["warn_cpu_c"] == 110
    assert settings["warn_gpu_c"] == 40
    assert settings["lhm_port"] == 1
    assert settings["gone_debounce_seconds"] == 0.0
    print("PASS every numeric setting is clamped to its range")


def test_games_validation():
    settings = core.normalize_settings({"games": [
        {"name": "My Game", "patterns": ["MyGame.EXE "], "enabled": True},
        {"name": "my game", "patterns": ["dupe.exe"]},
        {"name": "", "patterns": ["x.exe"]},
        {"name": "NoPatterns", "patterns": []},
        {"name": "BadPatterns", "patterns": "cs2.exe"},
        "not a dict",
    ]})
    assert len(settings["games"]) == 1, settings["games"]
    game = settings["games"][0]
    assert game["patterns"] == ["mygame.exe"], game
    print("PASS games: deduped, patterns lowered/trimmed, junk dropped")


def test_round_trip():
    settings = core.default_settings()
    settings["warn_cpu_c"] = 97
    core.save_settings(settings)
    loaded = core.load_settings()
    assert loaded["warn_cpu_c"] == 97
    assert loaded["games"][0]["name"] == "Counter-Strike 2"
    print("PASS settings survive a save/load round trip")


def test_missing_file():
    os.remove(core.settings_path())
    assert core.load_settings()["warn_cpu_c"] == 95
    print("PASS a missing settings file loads defaults")


def main():
    test_defaults_on_garbage()
    test_clamps()
    test_games_validation()
    test_round_trip()
    test_missing_file()
    print("ROUND 7 ALL PASS")


if __name__ == "__main__":
    main()
