"""Round 10 — Auto mode driver (fake UIA backend) + Proton exe search."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-auto-")


class FakeCtrl:
    def __init__(self, name, fail=False):
        self.name = name
        self.fail = fail
        self.invoked = False


class FakeBackend:
    def __init__(self, names, window_missing=False):
        self.ctrls = [FakeCtrl(n) for n in names]
        self.window_missing = window_missing

    def window(self, timeout=12.0):
        return None if self.window_missing else object()

    def buttons(self, window):
        return [(c.name, c) for c in self.ctrls]

    def invoke(self, control):
        if control.fail:
            raise RuntimeError("invoke failed")
        control.invoked = True


def test_disconnect_picks_exact_button():
    backend = FakeBackend(["Connect", "Disconnect", "Settings"])
    ok, detail = core.auto_proton_action("disconnect", backend=backend)
    assert ok and "Disconnect" in detail
    states = {c.name: c.invoked for c in backend.ctrls}
    assert states == {"Connect": False, "Disconnect": True, "Settings": False}
    print("PASS disconnect clicks Disconnect only")


def test_connect_never_clicks_disconnect():
    backend = FakeBackend(["Disconnect"])
    ok, detail = core.auto_proton_action("connect", backend=backend)
    assert not ok and "not found" in detail
    assert backend.ctrls[0].invoked is False

    backend = FakeBackend(["Disconnect", "Connect"])
    ok, _ = core.auto_proton_action("connect", backend=backend)
    assert ok
    states = {c.name: c.invoked for c in backend.ctrls}
    assert states == {"Disconnect": False, "Connect": True}

    backend = FakeBackend(["Connect", "Quick Connect"])
    ok, detail = core.auto_proton_action("connect", backend=backend)
    assert ok and "Quick Connect" in detail
    print("PASS connect prefers Quick Connect, never touches Disconnect")


def test_failures_are_reasons_not_exceptions():
    ok, detail = core.auto_proton_action("disconnect", backend=FakeBackend([], window_missing=True))
    assert not ok and "not found" in detail
    ok, detail = core.auto_proton_action("explode", backend=FakeBackend([]))
    assert not ok and "unknown action" in detail
    backend = FakeBackend(["Disconnect"])
    backend.ctrls[0].fail = True
    ok, detail = core.auto_proton_action("disconnect", backend=backend)
    assert not ok and "failed" in detail
    # no backend at all: on this machine pywinauto is absent, and the
    # call must degrade cleanly instead of raising
    ok, detail = core.auto_proton_action("disconnect")
    assert not ok and detail
    print("PASS failures return reasons, never raise")


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("exe")


def test_find_proton_exe_versioned():
    base = os.path.join(TMP, "Proton", "VPN")
    _touch(os.path.join(base, "ProtonVPN.exe"))
    _touch(os.path.join(base, "v4.2.0", "ProtonVPN.exe"))
    client = os.path.join(base, "v5.1.10", "ProtonVPN.Client.exe")
    _touch(client)
    assert core.find_proton_exe({}, bases=[base]) == client
    os.remove(client)
    assert core.find_proton_exe({}, bases=[base]) == os.path.join(base, "v4.2.0", "ProtonVPN.exe")
    override = os.path.join(TMP, "custom.exe")
    _touch(override)
    assert core.find_proton_exe({"proton_path": override}, bases=[base]) == override
    assert core.find_proton_exe({"proton_path": override + ".missing"}, bases=[base]) \
        == os.path.join(base, "v4.2.0", "ProtonVPN.exe")
    assert core.find_proton_exe({}, bases=[os.path.join(TMP, "nope")]) is None
    print("PASS find_proton_exe: versioned folders, Client first, override wins")


def test_version_key():
    assert core._version_key("v5.1.10") == (5, 1, 10)
    assert core._version_key("v5.1.10") > core._version_key("v4.9.9")
    assert core._version_key("Assets") == (-1,)
    assert core._version_key("v5") == (5,)
    print("PASS _version_key")


if __name__ == "__main__":
    test_disconnect_picks_exact_button()
    test_connect_never_clicks_disconnect()
    test_failures_are_reasons_not_exceptions()
    test_find_proton_exe_versioned()
    test_version_key()
    print("ROUND 10: ALL PASS")
