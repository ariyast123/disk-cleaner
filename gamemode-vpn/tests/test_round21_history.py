"""Round 21 — Session history: engine records + JSON storage."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def make_engine(clock, **overrides):
    settings = core.default_settings()
    settings.update(overrides)
    return core.Engine(settings, now=clock)


def end_session(eng, clock, state):
    """Close the game and run the debounce out; return the events."""
    eng.update(set(), state)
    clock.advance(11)
    return eng.update(set(), state)


def test_full_session_record():
    clock = Clock()
    eng = make_engine(clock)
    eng.update({"Counter-Strike 2"}, "protected")
    eng.update({"Counter-Strike 2"}, "blocked")
    eng.update({"Counter-Strike 2"}, "bare")
    assert eng.mode == "gaming"
    clock.advance(3600)
    events = end_session(eng, clock, "bare")
    assert "game_ended" in events
    assert "restore_needed" in events
    rec = eng.completed_session
    assert rec is not None
    assert rec["games"] == ["Counter-Strike 2"]
    assert rec["started_at"], "wall-clock start must be recorded"
    assert rec["duration_seconds"] == 3611, rec["duration_seconds"]
    assert rec["game_mode_seconds"] == 3611, rec["game_mode_seconds"]
    assert rec["game_mode_on"] is True
    assert rec["was_protected"] is True
    assert rec["restore_needed"] is True
    assert rec["peak_state"] == "gaming"
    print("PASS full session record")


def test_bare_session_record():
    clock = Clock()
    eng = make_engine(clock)
    eng.update({"Rust"}, "bare")
    assert eng.mode == "gaming"
    clock.advance(90)
    events = end_session(eng, clock, "bare")
    assert "game_ended" in events
    assert "restore_needed" not in events
    rec = eng.completed_session
    assert rec["games"] == ["Rust"]
    assert rec["duration_seconds"] == 101, rec["duration_seconds"]
    assert rec["game_mode_on"] is True
    assert rec["was_protected"] is False
    assert rec["restore_needed"] is False
    assert rec["peak_state"] == "gaming"
    print("PASS bare session record")


def test_session_never_reached_game_mode():
    clock = Clock()
    eng = make_engine(clock)
    eng.update({"Overwatch"}, "protected")
    assert eng.mode == "action_needed"
    clock.advance(30)
    events = end_session(eng, clock, "protected")
    assert "game_ended" in events
    assert "restore_needed" not in events  # still protected: nothing to restore
    rec = eng.completed_session
    assert rec["games"] == ["Overwatch"]
    assert rec["duration_seconds"] == 41, rec["duration_seconds"]
    assert rec["game_mode_on"] is False
    assert rec["game_mode_seconds"] == 0
    assert rec["peak_state"] == "protected"
    print("PASS session that never reached Game Mode")


def test_multi_game_session():
    clock = Clock()
    eng = make_engine(clock)
    eng.update({"Counter-Strike 2"}, "bare")
    clock.advance(10)
    eng.update({"Counter-Strike 2", "Rust"}, "bare")
    clock.advance(10)
    end_session(eng, clock, "bare")
    rec = eng.completed_session
    assert rec["games"] == ["Counter-Strike 2", "Rust"], rec["games"]
    print("PASS multi-game session lists every game played")


def test_history_storage_roundtrip():
    tmp = tempfile.mkdtemp(prefix="gmvpn-hist-")
    path = os.path.join(tmp, "history.json")
    assert core.load_history(path) == []  # missing file -> empty
    record = {
        "games": ["Counter-Strike 2"], "started_at": "2026-11-22 19:40",
        "duration_seconds": 3611, "game_mode_seconds": 3600,
        "game_mode_on": True, "was_protected": True,
        "restore_needed": True, "peak_state": "gaming",
    }
    assert core.append_history(record, path) is True
    assert not os.path.exists(path + ".tmp"), "no tmp file left behind"
    loaded = core.load_history(path)
    assert len(loaded) == 1 and loaded[0] == record, loaded
    print("PASS history storage round-trip")


def test_history_tolerates_bad_files():
    tmp = tempfile.mkdtemp(prefix="gmvpn-hist-")
    path = os.path.join(tmp, "history.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert core.load_history(path) == []
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"not": "a list"}, fh)
    assert core.load_history(path) == []
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([
            {"games": ["Rust"], "duration_seconds": 5},
            {"games": []},
            "junk",
            {"games": ["Overwatch"], "started_at": "x", "duration_seconds": "bad"},
            {"games": ["Counter-Strike 2"], "duration_seconds": 60,
             "game_mode_on": True, "peak_state": "gaming"},
        ], fh)
    loaded = core.load_history(path)
    assert [e["games"] for e in loaded] == [["Rust"], ["Counter-Strike 2"]], loaded
    assert loaded[0]["game_mode_on"] is False  # missing fields get honest defaults
    print("PASS history tolerates corrupt and malformed files")


def test_history_caps_at_fifty():
    tmp = tempfile.mkdtemp(prefix="gmvpn-hist-")
    path = os.path.join(tmp, "history.json")
    for i in range(55):
        assert core.append_history({
            "games": ["Rust"], "started_at": f"2026-11-22 00:{i:02d}",
            "duration_seconds": i, "game_mode_seconds": i,
            "game_mode_on": True, "was_protected": False,
            "restore_needed": False, "peak_state": "gaming",
        }, path) is True
    loaded = core.load_history(path)
    assert len(loaded) == 50, len(loaded)
    assert loaded[0]["duration_seconds"] == 5, "oldest five dropped"
    assert loaded[-1]["duration_seconds"] == 54
    print("PASS history caps at 50 entries, oldest first out")


def test_invalid_record_rejected():
    tmp = tempfile.mkdtemp(prefix="gmvpn-hist-")
    path = os.path.join(tmp, "history.json")
    assert core.append_history({}, path) is False
    assert core.append_history({"games": []}, path) is False
    assert core.append_history("not a dict", path) is False
    assert not os.path.exists(path), "rejected records must not create the file"
    print("PASS invalid records rejected without touching disk")


if __name__ == "__main__":
    test_full_session_record()
    test_bare_session_record()
    test_session_never_reached_game_mode()
    test_multi_game_session()
    test_history_storage_roundtrip()
    test_history_tolerates_bad_files()
    test_history_caps_at_fifty()
    test_invalid_record_rejected()
    print("ROUND 21: ALL PASS")
