"""Round 4 — connection-state inference + step lists + snapshot cache."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core


def test_detect_matrix():
    d = core.detect_vpn_state
    # tunnel adapter up -> protected regardless of gateway facts
    assert d({"ProtonVPN": True, "Wi-Fi": True}, "192.168.1.1", True) == "protected"
    assert d({"ProtonVPN": True}, None, None) == "protected"
    # adapter present but DOWN -> not protected
    assert d({"ProtonVPN": False, "Wi-Fi": True}, "192.168.1.1", True) == "bare"
    # TAP-style names also carry the keyword
    assert d({"TAP-ProtonVPN Windows Adapter V9": True}, None, None) == "protected"
    # bare vs blocked hinges on gateway reachability
    assert d({"Wi-Fi": True}, "192.168.1.1", True) == "bare"
    assert d({"Wi-Fi": True}, "192.168.1.1", False) == "blocked"
    # not enough info -> unknown
    assert d({"Wi-Fi": True}, None, None) == "unknown"
    assert d({"Wi-Fi": True}, "192.168.1.1", None) == "unknown"
    assert d({}, None, None) == "unknown"
    assert d(None, None, None) == "unknown"
    print("PASS detect matrix")


def test_detect_custom_keywords():
    d = core.detect_vpn_state
    assert d({"Mullvad": True}, None, None, ("mullvad",)) == "protected"
    assert d({"Mullvad": True}, "192.168.1.1", True, ("proton",)) == "bare"
    # empty keyword list falls back to proton
    assert d({"ProtonVPN": True}, None, None, ()) == "protected"
    print("PASS custom keywords")


def make_engine(mode_state):
    settings = core.default_settings()
    eng = core.Engine(settings, now=lambda: 0.0)
    eng.mode, eng.vpn_state = mode_state
    return eng


def test_steps():
    steps = make_engine(("action_needed", "protected")).current_steps()
    assert len(steps) == 3 and steps[0][1] == "current" and "Kill switch" in steps[0][0]

    steps = make_engine(("action_needed", "blocked")).current_steps()
    states = [s for _, s in steps]
    assert states[0] == "done" and "warn" in states and "current" in states

    steps = make_engine(("action_needed", "unknown")).current_steps()
    assert steps and steps[0][1] == "current"

    steps = make_engine(("restore_needed", "bare")).current_steps()
    assert steps[0][1] == "current" and "Connect" in steps[0][0]

    steps = make_engine(("restore_needed", "blocked")).current_steps()
    assert steps[0][1] == "done"

    assert make_engine(("idle", "protected")).current_steps() == []
    assert make_engine(("gaming", "bare")).current_steps() == []
    print("PASS step lists")


def test_snapshot_cache_ttl():
    calls = []
    original = core.default_gateway
    core.default_gateway = lambda: (calls.append(1), "10.0.0.1")[1]
    try:
        cache = core.SnapshotCache(gateway_ttl=20.0)
        assert cache.gateway(100.0) == "10.0.0.1"
        assert cache.gateway(110.0) == "10.0.0.1"
        assert len(calls) == 1          # cached inside the TTL
        assert cache.gateway(121.0) == "10.0.0.1"
        assert len(calls) == 2          # refreshed after the TTL
    finally:
        core.default_gateway = original
    print("PASS snapshot cache TTL")


def test_collect_snapshot_wiring():
    settings = core.default_settings()
    originals = (core.running_process_names, core.interface_states,
                 core.default_gateway, core.ping_host)
    core.running_process_names = lambda: ["cs2.exe", "chrome.exe"]
    core.interface_states = lambda: {"Wi-Fi": True}
    core.default_gateway = lambda: "192.168.1.1"
    core.ping_host = lambda host: True
    try:
        running, state = core.collect_snapshot(settings, core.SnapshotCache(), now=0.0)
        assert running == {"Counter-Strike 2"}, running
        assert state == "bare", state
        core.ping_host = lambda host: False
        running, state = core.collect_snapshot(settings, core.SnapshotCache(), now=100.0)
        assert state == "blocked", state
        core.interface_states = lambda: {"ProtonVPN": True}
        running, state = core.collect_snapshot(settings, core.SnapshotCache(), now=200.0)
        assert state == "protected", state
    finally:
        (core.running_process_names, core.interface_states,
         core.default_gateway, core.ping_host) = originals
    print("PASS collect_snapshot wiring")


if __name__ == "__main__":
    test_detect_matrix()
    test_detect_custom_keywords()
    test_steps()
    test_snapshot_cache_ttl()
    test_collect_snapshot_wiring()
    print("ROUND 4: ALL PASS")
