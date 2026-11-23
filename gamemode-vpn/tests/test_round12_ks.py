"""Round 12 — kill-switch learning + shortened steps."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core


class Clock:
    def __init__(self):
        self.t = 9000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def make(clock, **over):
    settings = core.default_settings()
    settings.update(over)
    return core.Engine(settings, now=clock)


def test_direct_bare_learns_no_kill_switch():
    clock = Clock()
    eng = make(clock)
    assert eng.ks_seen is None
    eng.update({"Rust"}, "protected")
    assert len(eng.current_steps()) == 3  # full KS version while unknown
    eng.update({"Rust"}, "bare")
    assert eng.mode == "gaming"
    assert eng.ks_seen is False
    # next session: shortened steps, no kill-switch text anywhere
    eng.update(set(), "bare")
    clock.advance(11)
    eng.update(set(), "bare")
    assert eng.mode == "restore_needed"
    steps = eng.current_steps()
    assert len(steps) == 2
    assert all("kill switch" not in text.lower() for text, _ in steps)
    eng.update(set(), "protected")
    eng.update({"Rust"}, "protected")
    steps = eng.current_steps()
    assert len(steps) == 2
    assert steps[0][0] == "In Proton: click Disconnect"
    print("PASS direct-to-bare session learns: no kill switch, steps shorten")


def test_blocked_learns_kill_switch():
    clock = Clock()
    eng = make(clock)
    eng.update({"Rust"}, "protected")
    eng.update({"Rust"}, "blocked")
    assert eng.ks_seen is True  # learned the moment blocking is seen
    eng.update({"Rust"}, "bare")
    assert eng.mode == "gaming" and eng.ks_seen is True
    eng.update(set(), "bare")
    clock.advance(11)
    eng.update(set(), "bare")
    steps = eng.current_steps()
    assert len(steps) == 3
    assert any("Kill Switch" in text for text, _ in steps)
    print("PASS blocked session learns: kill switch on, full steps stay")


def test_bare_start_learns_nothing():
    clock = Clock()
    eng = make(clock)
    eng.update({"Rust"}, "bare")   # VPN was never on: nothing to learn
    assert eng.mode == "gaming"
    assert eng.ks_seen is None
    print("PASS bare-start session learns nothing")


def test_ks_setting_normalization():
    assert core.normalize_settings({"kill_switch_seen": True})["kill_switch_seen"] is True
    assert core.normalize_settings({"kill_switch_seen": False})["kill_switch_seen"] is False
    assert core.normalize_settings({"kill_switch_seen": "yes"})["kill_switch_seen"] is None
    assert core.normalize_settings({})["kill_switch_seen"] is None
    assert core.normalize_settings({})["auto_mode"] is True
    assert core.normalize_settings({})["minimize_to_tray"] is True
    assert core.normalize_settings({"auto_mode": False})["auto_mode"] is False
    print("PASS settings normalization for the new keys")


if __name__ == "__main__":
    test_direct_bare_learns_no_kill_switch()
    test_blocked_learns_kill_switch()
    test_bare_start_learns_nothing()
    test_ks_setting_normalization()
    print("ROUND 12: ALL PASS")
