"""Round 1 — Engine happy paths: full session life cycles."""
import os
import sys

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


def test_full_protected_session():
    clock = Clock()
    eng = make_engine(clock)
    assert eng.mode == "idle"

    events = eng.update({"Counter-Strike 2"}, "protected")
    assert eng.mode == "action_needed", eng.mode
    assert "game_started:Counter-Strike 2" in events
    assert "action_needed" in events
    assert eng.was_protected is True

    # still protected: no change, no repeated events
    events = eng.update({"Counter-Strike 2"}, "protected")
    assert eng.mode == "action_needed"
    assert events == []

    # he disconnects with KS still on -> blocked mid-step, event fires once
    events = eng.update({"Counter-Strike 2"}, "blocked")
    assert eng.mode == "action_needed"
    assert "blocked_midway" in events
    events = eng.update({"Counter-Strike 2"}, "blocked")
    assert "blocked_midway" not in events

    # KS off -> bare -> game mode
    events = eng.update({"Counter-Strike 2"}, "bare")
    assert eng.mode == "gaming"
    assert "game_mode_on" in events
    clock.advance(3600)
    assert eng.game_mode_seconds() == 3600

    # game closes: debounce first
    events = eng.update(set(), "bare")
    assert eng.mode == "gaming"
    assert events == []
    clock.advance(11)
    events = eng.update(set(), "bare")
    assert "game_ended" in events
    assert "restore_needed" in events
    assert eng.mode == "restore_needed"

    # he reconnects but KS not yet re-armed: still restore_needed
    events = eng.update(set(), "bare")
    assert eng.mode == "restore_needed"
    # tunnel up -> restored
    events = eng.update(set(), "protected")
    assert eng.mode == "idle"
    assert "protected_restored" in events
    print("PASS full protected session")


def test_bare_session_no_restore_nag():
    clock = Clock()
    eng = make_engine(clock)
    events = eng.update({"Rust"}, "bare")
    assert eng.mode == "gaming"           # straight in, nothing to undo
    assert "game_mode_on" in events
    assert eng.was_protected is False
    clock.advance(60)
    eng.update(set(), "bare")
    clock.advance(11)
    events = eng.update(set(), "bare")
    assert "game_ended" in events
    assert "restore_needed" not in events  # VPN was off before: no nagging
    assert eng.mode == "idle"
    print("PASS bare session, no restore nag")


def test_restore_via_blocked_state():
    # He re-arms the kill switch BEFORE reconnecting: state goes blocked,
    # which is fine — restore completes when the tunnel comes up.
    clock = Clock()
    eng = make_engine(clock)
    eng.update({"Overwatch"}, "protected")
    eng.update({"Overwatch"}, "bare")
    eng.update(set(), "bare")
    clock.advance(11)
    eng.update(set(), "bare")
    assert eng.mode == "restore_needed"
    events = eng.update(set(), "blocked")
    assert eng.mode == "restore_needed"
    steps = eng.current_steps()
    assert steps[0][1] == "done" and "Kill Switch" in steps[0][0]
    events = eng.update(set(), "protected")
    assert "protected_restored" in events
    assert eng.mode == "idle"
    print("PASS restore via blocked state")


if __name__ == "__main__":
    test_full_protected_session()
    test_bare_session_no_restore_nag()
    test_restore_via_blocked_state()
    print("ROUND 1: ALL PASS")
