"""Round 17: Proton's window closes itself after an auto click
(v1.2.6).

Ariya's ask: when a game starts or ends, GameMode stays minimized
and Proton's window should appear only for the moment of the
click, then close itself — the window, not the app (Proton's
service holds the tunnel state). So after a successful invoke the
auto driver now closes the window it used; a failure to close is
cosmetic and must never turn a worked click into a failure, and
on failure paths the window stays open (he needs it for the
guided steps). GameMode's own window is never raised by the
session flow — the only deiconify in the app is the tray menu.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import gamemode_core as core  # noqa: E402


class FakeCtrl:
    def __init__(self, name):
        self.name = name
        self.invoked = False


class FakeBackend:
    def __init__(self, with_button=True, close_explodes=False):
        self._with_button = with_button
        self._close_explodes = close_explodes
        self.ctrl = FakeCtrl("Disconnect")
        self.closed = []

    def window(self, timeout=2.0):
        return object()

    def buttons(self, win):
        if not self._with_button:
            return [("Settings", FakeCtrl("Settings"), "Button")]
        return [("Disconnect", self.ctrl, "Button")]

    def invoke(self, ctrl):
        ctrl.invoked = True

    def close_window(self, win):
        if self._close_explodes:
            raise RuntimeError("cannot close")
        self.closed.append(win)


class BareBackend:
    """A backend with no close_window at all (older fakes)."""

    def __init__(self):
        self.ctrl = FakeCtrl("Disconnect")

    def window(self, timeout=2.0):
        return object()

    def buttons(self, win):
        return [("Disconnect", self.ctrl, "Button")]

    def invoke(self, ctrl):
        ctrl.invoked = True


class FakeWin:
    def __init__(self, close_explodes=False):
        self._close_explodes = close_explodes
        self.closed = False
        self.minimized = False

    def close(self):
        if self._close_explodes:
            raise RuntimeError("refused")
        self.closed = True

    def minimize(self):
        self.minimized = True


def main():
    backend = FakeBackend()
    ok, detail = core.auto_proton_action("disconnect", backend=backend, timeout=3)
    assert ok and backend.ctrl.invoked
    assert len(backend.closed) == 1
    print("PASS window closed after a successful click")

    backend = FakeBackend(with_button=False)
    ok, detail = core.auto_proton_action("disconnect", backend=backend, timeout=1.5)
    assert not ok and backend.closed == []
    print("PASS window left open when the click never happened")

    backend = FakeBackend(close_explodes=True)
    ok, detail = core.auto_proton_action("disconnect", backend=backend, timeout=3)
    assert ok and "clicked" in detail
    print("PASS a failed close never fails a worked click")

    backend = BareBackend()
    ok, detail = core.auto_proton_action("disconnect", backend=backend, timeout=3)
    assert ok and backend.ctrl.invoked
    print("PASS backends without close_window still work")

    real = object.__new__(core._PywinautoBackend)
    win = FakeWin()
    real.close_window(win)
    assert win.closed and not win.minimized
    win = FakeWin(close_explodes=True)
    real.close_window(win)
    assert win.minimized and not win.closed
    print("PASS real backend: close, with minimize as fallback")

    print("ROUND 17 ALL PASS")


if __name__ == "__main__":
    main()
