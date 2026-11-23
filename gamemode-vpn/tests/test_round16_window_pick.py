"""Round 16: restore-connect window acquisition + helper hardening
(v1.2.5).

On Ariya's machine the auto DISCONNECT worked, but the auto CONNECT
after the session failed with "Proton's window was not found": the
backend used top_window(), which can hand back a hidden shell
window. The backend now enumerates the Proton process's windows,
picks the one with the most controls (the main UI), and restores it
when hidden. Separately, the update helper no longer waits forever:
it logs every phase into update_build.log from the first line and,
after ~60 s, force-closes stale GameModeVPN copies and builds
anyway — the v1.2.3 update stalled silently exactly there.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import psutil  # noqa: E402

import gamemode_core as core  # noqa: E402
import gamemode_vpn_app as gui  # noqa: E402


class FakeWin:
    def __init__(self, count, visible=True, explode=False):
        self._count = count
        self._visible = visible
        self._explode = explode
        self.restored = False

    def descendants(self):
        if self._explode:
            raise RuntimeError("dead window")
        return [object()] * self._count

    def is_visible(self):
        return self._visible

    def restore(self):
        self.restored = True
        self._visible = True


def test_pick_main_window():
    small, big, mid = FakeWin(3), FakeWin(40), FakeWin(7)
    assert core._pick_main_window([small, big, mid]) is big
    print("PASS main window = most controls")
    broken = FakeWin(0, explode=True)
    assert core._pick_main_window([broken, mid]) is mid
    print("PASS broken window counts as zero, never crashes")
    assert core._pick_main_window([]) is None
    assert core._pick_main_window(None) is None
    print("PASS no windows -> None")


class FakeConnectedApp:
    def __init__(self, windows):
        self._windows = windows

    def windows(self):
        return self._windows


class FakeApplication:
    next_windows = []

    def __init__(self, backend=None):
        self._backend = backend

    def connect(self, process=None, timeout=None):
        assert isinstance(process, int) and process > 0
        return FakeConnectedApp(FakeApplication.next_windows)


def make_backend(windows):
    backend = object.__new__(core._PywinautoBackend)
    backend._application_cls = FakeApplication
    FakeApplication.next_windows = windows
    return backend


def test_backend_window():
    my_name = psutil.Process().name().lower()
    saved = core.PROTON_PROCESS_NAMES
    core.PROTON_PROCESS_NAMES = (my_name,)
    try:
        small = FakeWin(2, visible=True)
        big_hidden = FakeWin(50, visible=False)
        backend = make_backend([small, big_hidden])
        win = backend.window(timeout=5.0)
        assert win is big_hidden, "must pick the main window, not the first"
        assert big_hidden.restored, "hidden main window must be restored"
        print("PASS backend picks + restores the hidden main window")

        backend = make_backend([])
        assert backend.window(timeout=1.2) is None
        print("PASS no windows -> None after the timeout")
    finally:
        core.PROTON_PROCESS_NAMES = saved


def test_helper_lines():
    lines = gui.update_helper_lines(
        r"C:\Users\ariyast\Downloads\Gamemod VPN",
        r"C:\Users\ariyast\Downloads\Gamemod VPN\dist\GameModeVPN.exe")
    body = "\n".join(lines)
    assert 'echo [helper] update started' in body
    assert '> update_build.log' in body  # log exists from phase one
    assert 'call build.bat auto >> update_build.log 2>&1' in body
    assert 'taskkill /F /IM GameModeVPN.exe' in body
    assert 'goto forceclose' in body and 'WAITS' in body
    assert 'echo [helper] building >> update_build.log' in body
    print("PASS helper logs phases, caps the wait, force-closes stale copies")


def main():
    test_pick_main_window()
    test_backend_window()
    test_helper_lines()
    print("ROUND 16 ALL PASS")


if __name__ == "__main__":
    main()
