"""Round 2 — process matching."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

GAMES = core.default_settings()["games"]


def test_exact_and_case():
    assert core.match_games(["cs2.exe"], GAMES) == {"Counter-Strike 2"}
    assert core.match_games(["CS2.EXE"], GAMES) == {"Counter-Strike 2"}
    assert core.match_games(["Cs2.Exe", "explorer.exe"], GAMES) == {"Counter-Strike 2"}
    print("PASS exact + case-insensitive")


def test_fivem_glob_variants():
    assert core.match_games(["FiveM.exe"], GAMES) == {"FiveM / GTA V"}
    assert core.match_games(["FiveM_b2545_GTAProcess.exe"], GAMES) == {"FiveM / GTA V"}
    assert core.match_games(["fivem_b3095_gtaprocess.exe"], GAMES) == {"FiveM / GTA V"}
    assert core.match_games(["GTA5.exe"], GAMES) == {"FiveM / GTA V"}
    # glob semantics: anything starting with "fivem" matches by design
    assert core.match_games(["fivemchat.exe"], GAMES) == {"FiveM / GTA V"}
    # near misses must not match
    assert core.match_games(["notfivem.exe"], GAMES) == set()
    assert core.match_games(["gta.exe"], GAMES) == set()
    print("PASS FiveM glob variants")


def test_all_defaults_and_multi():
    running = core.match_games(
        ["cs2.exe", "RustClient.exe", "Overwatch.exe", "steam.exe"], GAMES)
    assert running == {"Counter-Strike 2", "Rust", "Overwatch"}, running
    print("PASS multiple games at once")


def test_disabled_and_custom():
    games = [dict(g) for g in GAMES]
    games[0]["enabled"] = False
    assert core.match_games(["cs2.exe"], games) == set()
    games.append({"name": "Valorant", "patterns": ["valorant.exe"],
                  "enabled": True, "builtin": False})
    assert core.match_games(["VALORANT.exe"], games) == {"Valorant"}
    print("PASS disabled skipped, custom matched")


def test_empty_and_junk():
    assert core.match_games([], GAMES) == set()
    assert core.match_games([None, "", "svchost.exe"], GAMES) == set()
    print("PASS empty / junk input")


if __name__ == "__main__":
    test_exact_and_case()
    test_fivem_glob_variants()
    test_all_defaults_and_multi()
    test_disabled_and_custom()
    test_empty_and_junk()
    print("ROUND 2: ALL PASS")
