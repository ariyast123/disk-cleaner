"""Round 15: single-instance guard (v1.2.4).

Ariya's PC ended up with FIVE GameModeVPN instances running at once
(some hidden in the tray); the updater waits for every GameModeVPN.exe
to exit, so the update stalled forever. The app now takes a named
Windows mutex at startup; a second launch backs off with a message.
The guard must fail OPEN: any error, and every non-Windows platform,
lets the app start.
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import gamemode_vpn_app as gui  # noqa: E402


class FakeKernel32:
    def __init__(self, handle=123, last_error=0, explode=False):
        self._handle = handle
        self._last_error = last_error
        self._explode = explode

    def CreateMutexW(self, attrs, initial, name):
        if self._explode:
            raise OSError("no mutex for you")
        assert name  # a name is required for cross-process visibility
        return self._handle

    def GetLastError(self):
        return self._last_error


def fake_ctypes(kernel32):
    mod = types.ModuleType("ctypes")
    mod.windll = types.SimpleNamespace(kernel32=kernel32)
    return mod


def with_platform(platform, kernel32):
    real_platform = sys.platform
    real_ctypes = sys.modules.get("ctypes")
    sys.platform = platform
    if kernel32 is not None:
        sys.modules["ctypes"] = fake_ctypes(kernel32)
    gui._mutex_handle = None
    try:
        return gui._first_instance()
    finally:
        sys.platform = real_platform
        if real_ctypes is not None:
            sys.modules["ctypes"] = real_ctypes
        gui._mutex_handle = None


def main():
    # Non-Windows: always the first instance, ctypes untouched.
    assert with_platform("linux", None) is True
    print("PASS non-Windows always proceeds")

    # Windows, mutex free: first instance, handle kept.
    assert with_platform("win32", FakeKernel32(handle=77, last_error=0)) is True
    print("PASS first Windows instance proceeds")

    # Windows, ERROR_ALREADY_EXISTS (183): second instance backs off.
    assert with_platform("win32", FakeKernel32(handle=78, last_error=183)) is False
    print("PASS second instance is refused")

    # Windows, mutex creation failed (NULL handle): fail open.
    assert with_platform("win32", FakeKernel32(handle=0, last_error=0)) is True
    print("PASS NULL mutex handle fails open")

    # Windows, ctypes blows up: fail open — the guard never blocks.
    assert with_platform("win32", FakeKernel32(explode=True)) is True
    print("PASS mutex exception fails open")

    print("ROUND 15 ALL PASS")


if __name__ == "__main__":
    main()
