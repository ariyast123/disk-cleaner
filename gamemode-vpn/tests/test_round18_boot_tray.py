"""Round 18: boot launch starts in the tray + update notification
(v1.2.7).

Ariya's closing asks for GameMode: at boot the app must not open
its window — it stays minimized in the tray — and when an update
is available it should knock with a tray notification so he can
open the app himself. The Start-with-Windows entry now carries
--minimized; the entry is refreshed on every launch so older
entries gain the flag automatically. While hidden, the What's
New dialog also stays shut (the notes wait for a visible launch).
"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-gui18-")
core.data_dir = lambda: TMP
core.settings_path = lambda: os.path.join(TMP, "settings.json")
core.log_path = lambda: os.path.join(TMP, "gamemode.log")

import gamemode_vpn_app as gui

gui.fetch_update_info = lambda: None  # no network in tests


class FakeIcon:
    instances = []

    def __init__(self, name, image, title, menu=None):
        self.name, self.title, self.menu = name, title, menu
        self.notifications = []
        self.stopped = False
        FakeIcon.instances.append(self)

    def run_detached(self):
        pass

    def notify(self, message, title=None):
        self.notifications.append((message, title))

    def stop(self):
        self.stopped = True


class FakeMenuItem:
    def __init__(self, text, action=None, **kwargs):
        self.text = text


class FakeMenu:
    def __init__(self, *items):
        self.items = items


gui.pystray = types.SimpleNamespace(
    Icon=FakeIcon, Menu=FakeMenu, MenuItem=FakeMenuItem)
gui.TRAY_AVAILABLE = True


def make_app(**kwargs):
    app = gui.GameModeApp(**kwargs)
    app._stop.set()
    while not app.msg_queue.empty():
        app.msg_queue.get_nowait()
    app.update_idletasks()
    return app


def test_helpers():
    cmd = gui._startup_command(True, r"C:\Apps\GameModeVPN.exe", "ignored")
    assert cmd == r'"C:\Apps\GameModeVPN.exe" --minimized', cmd
    cmd = gui._startup_command(False, r"C:\Python\python.exe", r"C:\proj\app.py")
    assert cmd == r'"C:\Python\python.exe" "C:\proj\app.py" --minimized', cmd
    print("PASS startup command carries --minimized (frozen + script)")
    assert gui._wants_minimized(["app"]) is False
    assert gui._wants_minimized(["app", "--minimized"]) is True
    assert gui._wants_minimized(["app", "/minimized"]) is True
    assert gui._wants_minimized(["app", "--other"]) is False
    print("PASS --minimized flag parsing")


def test_boot_start_and_notify():
    FakeIcon.instances.clear()
    app = make_app(start_minimized=True)
    try:
        assert app._start_minimized is True
        assert app._hidden_in_tray is False
        app._start_in_tray()
        app.update_idletasks()
        assert app._hidden_in_tray is True
        assert app.winfo_viewable() == 0, "window must be withdrawn"
        assert len(FakeIcon.instances) == 1
        icon = FakeIcon.instances[0]
        print("PASS boot launch hides straight into the tray")

        app._show_update_banner({"version": "9.9.9", "notes": "test notes"})
        assert len(icon.notifications) == 1
        assert "9.9.9" in icon.notifications[0][0]
        print("PASS update while hidden knocks with a tray notification")

        core.save_whats_new({"version": gui.VERSION, "patch_notes": "shh"})
        app._maybe_show_whats_new()
        app.update_idletasks()
        toplevels = [w for w in app.winfo_children()
                     if w.__class__.__name__ == "CTkToplevel"]
        assert not toplevels, "no dialog may pop at a boot launch"
        assert os.path.isfile(core.whats_new_path()), "notes must be kept"
        print("PASS What's New stays shut (and saved) while hidden")

        app._show_from_tray()
        app.update_idletasks()
        assert app._hidden_in_tray is False
        assert app.winfo_viewable() == 1
        before = len(icon.notifications)
        app._show_update_banner({"version": "9.9.10", "notes": ""})
        assert len(icon.notifications) == before, "no knock when visible"
        print("PASS visible again: banner only, no notification")

        app._maybe_show_whats_new()
        app.update_idletasks()
        toplevels = [w for w in app.winfo_children()
                     if w.__class__.__name__ == "CTkToplevel"]
        assert len(toplevels) == 1, "notes show on the visible launch"
        toplevels[0].destroy()
        assert not os.path.isfile(core.whats_new_path())
        print("PASS What's New shows once the window is open")
    finally:
        app.destroy()


def test_default_launch_visible():
    app = make_app()
    try:
        assert app._start_minimized is False
        assert app._hidden_in_tray is False
        print("PASS manual launch unaffected")
    finally:
        app.destroy()


def main():
    test_helpers()
    test_boot_start_and_notify()
    test_default_launch_visible()
    print("ROUND 18 ALL PASS")


if __name__ == "__main__":
    main()
