"""Round 20: the update restart can no longer stall on a dialog
or a lingering process (v1.2.9).

Found in the code while Ariya's updates kept needing a manual
finish_update run: _update_downloaded started the helper FIRST
and then showed a modal "will now close" dialog — the helper
waited for the app to exit while the app waited for an OK click
that might sit unseen behind other windows. The dialog is gone
from the frozen path (a tray notification covers the hidden
case), and a 3-second timer guarantees the process exit the
helper is waiting for, whatever else is still running. The
helper also speaks on the console now (a manual run was a black
window even while it worked) and its wait cap drops to ~30 s.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-gui20-")
core.data_dir = lambda: TMP
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.log_path = lambda: os.path.join(TMP, "gamemode.log")

import gamemode_vpn_app as gui


class FakeTimer:
    started = []

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args

    def start(self):
        FakeTimer.started.append(self)


def test_helper_speaks_and_caps():
    lines = gui.update_helper_lines(r"C:\proj", r"C:\proj\dist\GameModeVPN.exe")
    body = "\n".join(lines)
    assert "if %WAITS% GEQ 10 goto proceed" in body
    assert "taskkill /F /IM GameModeVPN.exe" in body
    assert body.index("taskkill /F /IM GameModeVPN.exe") < \
        body.index(":waitloop")
    assert "echo GameMode VPN update: closing any running copies..." in body
    assert "echo GameMode VPN update: building" in body
    print("PASS helper kills first, narrates, verifies gone briefly")


def test_update_downloaded_no_modal_guaranteed_exit():
    app = gui.GameModeApp()
    try:
        app._stop.set()
        while not app.msg_queue.empty():
            app.msg_queue.get_nowait()

        calls = {"showinfo": 0, "helper": 0, "close": 0, "apply": 0}
        real = {
            "showinfo": gui.messagebox.showinfo,
            "apply": gui.apply_update_files,
            "timer": gui.threading.Timer,
            "frozen": getattr(sys, "frozen", None),
        }
        gui.messagebox.showinfo = lambda *a, **k: calls.__setitem__(
            "showinfo", calls["showinfo"] + 1)
        gui.apply_update_files = lambda proj, files: calls.__setitem__(
            "apply", calls["apply"] + 1)
        gui.threading.Timer = FakeTimer
        FakeTimer.started.clear()
        sys.frozen = True
        app._write_update_helper = lambda: calls.__setitem__(
            "helper", calls["helper"] + 1)
        app._on_close = lambda: calls.__setitem__(
            "close", calls["close"] + 1)
        app.update_info = {"version": "9.9.9", "patch_notes": "x"}
        try:
            app._update_downloaded({"gamemode_vpn_app.py": b"# x"})
        finally:
            gui.messagebox.showinfo = real["showinfo"]
            gui.apply_update_files = real["apply"]
            gui.threading.Timer = real["timer"]
            if real["frozen"] is None:
                del sys.frozen
            else:
                sys.frozen = real["frozen"]

        assert calls["apply"] == 1 and calls["helper"] == 1
        assert calls["showinfo"] == 0, "no modal may block the restart"
        assert calls["close"] == 1
        assert app._update_pending is True
        assert len(FakeTimer.started) == 1
        timer = FakeTimer.started[0]
        assert timer.interval == 1.0 and timer.function is os._exit
        assert timer.args == (0,)
        print("PASS frozen update: no modal, helper started, exit guaranteed")
    finally:
        app._stop.set()
        app.destroy()


def main():
    test_helper_speaks_and_caps()
    test_update_downloaded_no_modal_guaranteed_exit()
    print("ROUND 20 ALL PASS")


if __name__ == "__main__":
    main()
