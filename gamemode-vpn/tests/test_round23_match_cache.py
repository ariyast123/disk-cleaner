"""Round 23: match_games compiled-pattern cache — same answers,
no re-translation per tick."""
import fnmatch
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core


def reference(process_names, games):
    lowered = [str(p).lower() for p in process_names if p]
    running = set()
    for game in games:
        if not game.get("enabled", True):
            continue
        for pattern in game.get("patterns", []):
            pat = str(pattern).lower()
            if any(fnmatch.fnmatchcase(name, pat) for name in lowered):
                running.add(game["name"])
                break
    return running


GAMES = [
    {"name": "Counter-Strike 2", "patterns": ["cs2.exe"],
     "enabled": True, "builtin": True},
    {"name": "FiveM / GTA V",
     "patterns": ["fivem*.exe", "gta5.exe"],
     "enabled": True, "builtin": True},
    {"name": "Deadlock", "patterns": ["project8.exe", "deadlock.exe"],
     "enabled": True, "builtin": False},
    {"name": "Off Game", "patterns": ["off*.exe"],
     "enabled": False, "builtin": False},
]

CASES = [
    [],
    ["cs2.exe"],
    ["CS2.EXE", "steam.exe"],
    ["fivem.exe"], ["FiveM_GTAProcess.exe"], ["fivemchat.exe"],
    ["notfivem.exe"], ["gta.exe"], ["gta5.exe"],
    ["project8.exe"], ["deadlock.exe"], ["offgame.exe"],
    ["cs2.exe", "gta5.exe", "deadlock.exe", "chrome.exe"],
    [None, "", "cs2.exe"],
    ["cs2.exe.bak"], ["xcs2.exe"],
]


def test_equivalence():
    for names in CASES:
        got = core.match_games(names, GAMES)
        want = reference(names, GAMES)
        assert got == want, (names, got, want)
    print("PASS cached matcher == fnmatch reference on all cases")


def test_cache_reuse():
    core._pattern_cache.clear()
    core.match_games(["cs2.exe"], GAMES)
    size = len(core._pattern_cache)
    assert size == 5, size  # every enabled game's patterns, once
    for _ in range(50):
        core.match_games(["cs2.exe", "gta5.exe"], GAMES)
    assert len(core._pattern_cache) == size, len(core._pattern_cache)
    print("PASS the pattern cache fills once and stays put")


def test_speed_sanity():
    names = [f"proc{i}.exe" for i in range(5000)] + ["cs2.exe"]
    start = time.time()
    for _ in range(20):
        assert core.match_games(names, GAMES) == {"Counter-Strike 2"}
    elapsed = time.time() - start
    assert elapsed < 2.0, elapsed
    print(f"PASS 20 ticks x 5001 names in {elapsed:.2f}s")


def main():
    test_equivalence()
    test_cache_reuse()
    test_speed_sanity()
    print("ROUND 23 ALL PASS")


if __name__ == "__main__":
    main()
