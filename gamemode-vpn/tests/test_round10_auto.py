"""Round 10 — Auto mode driver (fake UIA backend) + Proton exe search."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-auto-")


class FakeCtrl:
    def __init__(self, name, fail=False, ctype="Button"):
        self.name = name
        self.fail = fail
        self.ctype = ctype
        self.invoked = False


class FakeBackend:
    """buttons_script: optional list of name-lists, one per buttons()
    call (the last one repeats) — simulates a UI still loading."""

    def __init__(self, names, window_missing=False, buttons_script=None):
        self.ctrls = {n: FakeCtrl(n) for n in names}
        self.window_missing = window_missing
        self.buttons_script = buttons_script
        self.buttons_calls = 0

    def window(self, timeout=2.0):
        return None if self.window_missing else object()

    def buttons(self, window):
        self.buttons_calls += 1
        if self.buttons_script is not None:
            idx = min(self.buttons_calls - 1, len(self.buttons_script) - 1)
            names = self.buttons_script[idx]
            return [(n, self.ctrls.setdefault(n, FakeCtrl(n)), "Button") for n in names]
        return [(c.name, c, c.ctype) for c in self.ctrls.values()]

    def invoke(self, control):
        if control.fail:
            raise RuntimeError("invoke failed")
        control.invoked = True


def test_disconnect_picks_exact_button():
    backend = FakeBackend(["Connect", "Disconnect", "Settings"])
    ok, detail = core.auto_proton_action("disconnect", backend=backend)
    assert ok and "Disconnect" in detail
    states = {n: c.invoked for n, c in backend.ctrls.items()}
    assert states == {"Connect": False, "Disconnect": True, "Settings": False}
    print("PASS disconnect clicks Disconnect only")


def test_connect_never_clicks_disconnect():
    backend = FakeBackend(["Disconnect"])
    ok, detail = core.auto_proton_action("connect", backend=backend, timeout=1.0)
    assert not ok and "not found" in detail
    assert backend.ctrls["Disconnect"].invoked is False

    backend = FakeBackend(["Disconnect", "Connect"])
    ok, _ = core.auto_proton_action("connect", backend=backend)
    assert ok
    states = {n: c.invoked for n, c in backend.ctrls.items()}
    assert states == {"Disconnect": False, "Connect": True}

    backend = FakeBackend(["Connect", "Quick Connect"])
    ok, detail = core.auto_proton_action("connect", backend=backend)
    assert ok and "Quick Connect" in detail
    print("PASS connect prefers Quick Connect, never touches Disconnect")


def test_button_appearing_late_is_found():
    # Proton still loading: the first two scans see an empty window,
    # the Disconnect button only appears on the third scan
    backend = FakeBackend(["Disconnect"],
                          buttons_script=[[], [], ["Disconnect"]])
    ok, detail = core.auto_proton_action("disconnect", backend=backend, timeout=5.0)
    assert ok and backend.buttons_calls >= 3
    assert backend.ctrls["Disconnect"].invoked is True
    print("PASS a button that appears late is still clicked (retry scan)")


def test_non_button_control_type_fallback():
    backend = FakeBackend([])
    ctrl = FakeCtrl("Disconnect", ctype="Custom")
    backend.buttons = lambda window: [("Disconnect", ctrl, "Custom")]
    ok, _ = core.auto_proton_action("disconnect", backend=backend, timeout=2.0)
    assert ok and ctrl.invoked is True
    # ...but a real Button with the same name is preferred over it
    backend = FakeBackend([])
    custom = FakeCtrl("Disconnect", ctype="Custom")
    button = FakeCtrl("Disconnect", ctype="Button")
    backend.buttons = lambda window: [("Disconnect", custom, "Custom"),
                                      ("Disconnect", button, "Button")]
    ok, _ = core.auto_proton_action("disconnect", backend=backend, timeout=2.0)
    assert ok and button.invoked is True and custom.invoked is False
    print("PASS non-Button controls are a fallback, Buttons preferred")


def test_failures_are_reasons_not_exceptions():
    ok, detail = core.auto_proton_action(
        "disconnect", backend=FakeBackend([], window_missing=True), timeout=1.0)
    assert not ok and "window was not found" in detail
    ok, detail = core.auto_proton_action("explode", backend=FakeBackend([]), timeout=1.0)
    assert not ok and "unknown action" in detail
    backend = FakeBackend(["Disconnect"])
    backend.ctrls["Disconnect"].fail = True
    ok, detail = core.auto_proton_action("disconnect", backend=backend, timeout=2.0)
    assert not ok and "failed" in detail
    # a missing button reports the names that WERE seen, for diagnosis
    backend = FakeBackend(["Settings", "Servers"])
    ok, detail = core.auto_proton_action("disconnect", backend=backend, timeout=1.0)
    assert not ok and "saw:" in detail and "Settings" in detail
    # no backend at all: on this machine pywinauto is absent, and the
    # call must degrade cleanly instead of raising
    ok, detail = core.auto_proton_action("disconnect")
    assert not ok and detail
    print("PASS failures return reasons (with seen names), never raise")


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
    test_button_appearing_late_is_found()
    test_non_button_control_type_fallback()
    test_failures_are_reasons_not_exceptions()
    test_find_proton_exe_versioned()
    test_version_key()
    print("ROUND 10: ALL PASS")
