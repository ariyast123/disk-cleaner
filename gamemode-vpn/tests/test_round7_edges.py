"""Round 7 — Engine edge cases with a fake clock."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core


class Clock:
    def __init__(self):
        self.t = 5000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def make(clock, **over):
    settings = core.default_settings()
    settings.update(over)
    return core.Engine(settings, now=clock)


def test_game_already_running_at_start():
    clock = Clock()
    eng = make(clock)
    events = eng.update({"Rust"}, "protected")
    assert eng.mode == "action_needed" and eng.was_protected is True
    assert "game_started:Rust" in events
    print("PASS game already running at first observation")


def test_two_games_one_closes():
    clock = Clock()
    eng = make(clock)
    eng.update({"Rust", "Overwatch"}, "bare")
    assert eng.mode == "gaming"
    events = eng.update({"Rust"}, "bare")     # Overwatch closed, Rust lives
    clock.advance(60)
    events += eng.update({"Rust"}, "bare")
    assert eng.mode == "gaming"
    assert "game_ended" not in events
    eng.update(set(), "bare")
    clock.advance(11)
    events = eng.update(set(), "bare")
    assert "game_ended" in events
    events = eng.update(set(), "bare")        # ended fires exactly once
    assert events == []
    print("PASS two games, one closes; end fires once")


def test_flap_inside_debounce():
    clock = Clock()
    eng = make(clock)
    eng.update({"Counter-Strike 2"}, "bare")
    start = eng.session_start
    eng.update(set(), "bare")
    clock.advance(5)                          # gone 5s < 10s debounce
    events = eng.update({"Counter-Strike 2"}, "bare")
    assert eng.mode == "gaming"
    assert eng.session_start == start         # same session, not a new one
    assert "game_started:Counter-Strike 2" not in events
    print("PASS flap inside debounce keeps the session")


def test_debounce_boundary():
    clock = Clock()
    eng = make(clock)
    eng.update({"Rust"}, "bare")
    eng.update(set(), "bare")                 # gone_since = t
    clock.advance(10)                         # exactly the debounce
    events = eng.update(set(), "bare")
    assert "game_ended" in events
    print("PASS debounce boundary (>=)")


def test_new_game_interrupts_restore():
    clock = Clock()
    eng = make(clock)
    eng.update({"Rust"}, "protected")
    eng.update({"Rust"}, "bare")
    eng.update(set(), "bare")
    clock.advance(11)
    eng.update(set(), "bare")
    assert eng.mode == "restore_needed"
    eng.update({"Overwatch"}, "bare")            # new game before restoring
    assert eng.mode == "gaming"                  # bare already: straight in
    assert eng.was_protected is False            # recomputed for the new session
    print("PASS new game interrupts restore")


def test_blocked_at_start_event_once():
    clock = Clock()
    eng = make(clock)
    events = eng.update({"Rust"}, "blocked")
    assert eng.mode == "action_needed"
    assert events.count("blocked_midway") == 1
    events = eng.update({"Rust"}, "blocked")
    assert "blocked_midway" not in events
    print("PASS blocked at start, event once")


def test_reconnect_midgame_then_close():
    clock = Clock()
    eng = make(clock)
    eng.update({"Rust"}, "protected")
    eng.update({"Rust"}, "bare")
    assert eng.mode == "gaming"
    eng.update({"Rust"}, "protected")            # he reconnects mid-game
    assert eng.mode == "gaming"                  # game still running: stay
    eng.update(set(), "protected")
    clock.advance(11)
    events = eng.update(set(), "protected")
    assert "game_ended" in events
    assert "restore_needed" not in events        # already protected
    assert eng.mode == "idle"
    print("PASS reconnect mid-game, clean close")


def test_unknown_state_never_gaming():
    clock = Clock()
    eng = make(clock)
    eng.update({"Rust"}, "unknown")
    assert eng.mode == "action_needed"
    clock.advance(300)
    events = eng.update({"Rust"}, "unknown")
    assert eng.mode == "action_needed"
    assert "game_mode_on" not in events
    print("PASS unknown state never claims game mode")


def test_session_clock_resets():
    clock = Clock()
    eng = make(clock)
    eng.update({"Rust"}, "bare")
    clock.advance(120)
    assert eng.session_seconds() == 120
    eng.update(set(), "bare")
    clock.advance(11)
    eng.update(set(), "bare")
    assert eng.session_seconds() == 0
    assert eng.game_mode_seconds() == 0
    print("PASS session clock resets after end")


if __name__ == "__main__":
    test_game_already_running_at_start()
    test_two_games_one_closes()
    test_flap_inside_debounce()
    test_debounce_boundary()
    test_new_game_interrupts_restore()
    test_blocked_at_start_event_once()
    test_reconnect_midgame_then_close()
    test_unknown_state_never_gaming()
    test_session_clock_resets()
    print("ROUND 7: ALL PASS")
