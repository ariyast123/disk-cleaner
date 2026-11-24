"""Round 7: What's New window after updating (roadmap item 3).

The note helpers are plain functions (tested with explicit paths);
the dialog, the startup hook and the update hook need a GUI, so this
file runs under Xvfb like rounds 3 and 5.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import customtkinter as ctk

import disk_cleaner_app as gui

# Same note as round 3: fixtures live inside the project folder, which
# the app protects as its own home - point "home" elsewhere for tests.
FAKE_HOME = os.path.join(HERE, "fake_app_home")
os.makedirs(FAKE_HOME, exist_ok=True)
gui.own_folders = lambda: [FAKE_HOME]

BASE = os.path.join(HERE, "fixtures7")
os.system(f"rm -rf {BASE}")
os.makedirs(BASE, exist_ok=True)

NOTE_PATH = os.path.join(BASE, "whats_new.json")
# Route the app's note file at the temp path for every GUI test.
gui.whats_new_path = lambda: NOTE_PATH


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.03)


def kill_app(app):
    """Cancel every pending after callback before destroying, or the
    interpreter reports bgerrors for callbacks that fire mid-destroy
    (Tk noise, not an app bug - the real app is destroyed once)."""
    try:
        for after_id in app.tk.call("after", "info"):
            try:
                app.after_cancel(after_id)
            except Exception:
                pass
    except Exception:
        pass
    app.destroy()


def find_child(win, kind, text=None):
    for child in win.winfo_children():
        if isinstance(child, kind):
            if text is None or child.cget("text") == text:
                return child
    return None


# --- 1) save / load roundtrip -------------------------------------------
def test_save_load_roundtrip():
    path = os.path.join(BASE, "note1.json")
    assert gui.save_whats_new("1.2.4", "First line.\nSecond line.", path)
    assert os.path.exists(path)
    info = gui.load_whats_new(path)
    assert info == {"version": "1.2.4", "notes": "First line.\nSecond line."}
    print("PASS save/load roundtrip keeps version and notes")


# --- 2) load rejects bad files ------------------------------------------
def test_load_rejects_bad_files():
    assert gui.load_whats_new(os.path.join(BASE, "missing.json")) is None
    bad_json = os.path.join(BASE, "bad.json")
    with open(bad_json, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert gui.load_whats_new(bad_json) is None
    for payload in ('{"version": 123, "notes": "x"}',
                    '{"version": "1.2.4"}',
                    '{"version": "1.2.4", "notes": ""}',
                    '{"version": "1.2.4", "notes": "   "}',
                    '["1.2.4", "notes"]',
                    '"just a string"'):
        p = os.path.join(BASE, "bad2.json")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(payload)
        assert gui.load_whats_new(p) is None, payload
    print("PASS load rejects missing, broken and empty notes")


# --- 3) save never raises, clear removes ---------------------------------
def test_save_never_raises_and_clear():
    blocker = os.path.join(BASE, "blocker")
    with open(blocker, "w", encoding="utf-8") as fh:
        fh.write("a file, not a folder")
    assert gui.save_whats_new("1.2.4", "x",
                               os.path.join(blocker, "n.json")) is False
    path = os.path.join(BASE, "note2.json")
    assert gui.save_whats_new("1.2.4", "x", path)
    gui.clear_whats_new(path)
    assert not os.path.exists(path)
    gui.clear_whats_new(path)  # clearing a missing file is fine
    gui.clear_whats_new(os.path.join(BASE, "never-there.json"))
    print("PASS save fails soft, clear removes and tolerates missing")


# --- 4) startup shows the window once for the running version ------------
def test_startup_shows_window_once():
    assert gui.save_whats_new(gui.VERSION, "Line one.\nLine two.")
    app = gui.DiskCleanerApp()
    try:
        pump(app, 1.2)  # the after(500) startup check fires
        win = app._whats_new_window
        assert win is not None, "no What's New window appeared"
        assert win.winfo_exists()
        assert gui.VERSION in win.title()
        box = find_child(win, ctk.CTkTextbox)
        assert box is not None
        assert "Line one." in box.get("1.0", "end-1c")
        assert "Line two." in box.get("1.0", "end-1c")
        assert not os.path.exists(NOTE_PATH), "note file must be gone"
        close = find_child(win, ctk.CTkButton, "Close")
        assert close is not None
        close.invoke()
        pump(app, 0.3)
        assert not win.winfo_exists(), "Close must destroy the window"
    finally:
        kill_app(app)
    print("PASS startup shows What's New once, Close dismisses it")


# --- 5) stale version: no window, file still cleaned up -------------------
def test_stale_version_shows_nothing():
    assert gui.save_whats_new("9.9.9", "Notes for a version not running.")
    app = gui.DiskCleanerApp()
    try:
        pump(app, 1.2)
        assert app._whats_new_window is None
        assert not os.path.exists(NOTE_PATH), "stale note must be gone"
    finally:
        kill_app(app)
    print("PASS stale note shows no window and is cleaned up")


# --- 6) the update hook saves the note; no notes -> no file --------------
def test_update_downloaded_saves_note():
    real_showinfo = gui.messagebox.showinfo
    gui.messagebox.showinfo = lambda *a, **k: None
    try:
        app = gui.DiskCleanerApp()
        try:
            files = {}
            for name in gui.UPDATE_FILES:
                with open(os.path.join(HERE, "..", name), "rb") as fh:
                    files[name] = fh.read()
            app.update_info = {
                "version": "1.2.6",
                "notes": "banner line",
                "patch_notes": "Hook line one.\nHook line two.",
            }
            app._update_downloaded(files)
            assert os.path.exists(NOTE_PATH)
            with open(NOTE_PATH, encoding="utf-8") as fh:
                saved = json.load(fh)
            assert saved["version"] == "1.2.6"
            assert saved["notes"] == "Hook line one.\nHook line two."
            # the files really landed in the project folder
            assert os.path.exists(
                os.path.join(FAKE_HOME, "disk_cleaner_app.py"))
            # matching version -> the startup check shows it, then
            # the file is gone
            pump(app, 1.2)
            assert app._whats_new_window is not None
            assert not os.path.exists(NOTE_PATH)
            app._whats_new_window.destroy()
            pump(app, 0.2)
            # a stale version is cleaned up without a window
            app.update_info = {"version": "9.9.9", "notes": "",
                               "patch_notes": "Stale notes."}
            app._update_downloaded(files)
            assert os.path.exists(NOTE_PATH)
            win_before = app._whats_new_window
            app._maybe_show_whats_new()
            assert app._whats_new_window is win_before
            assert not os.path.exists(NOTE_PATH)
            # no patch notes -> no file at all
            app.update_info = {"version": "1.2.4", "notes": "banner"}
            app._update_downloaded(files)
            assert not os.path.exists(NOTE_PATH)
        finally:
            kill_app(app)
    finally:
        gui.messagebox.showinfo = real_showinfo
    print("PASS update saves the note; empty notes save nothing")


def test_version():
    assert gui.VERSION == "1.2.6"
    print("PASS app version is 1.2.6")


def main():
    test_save_load_roundtrip()
    test_load_rejects_bad_files()
    test_save_never_raises_and_clear()
    test_startup_shows_window_once()
    test_stale_version_shows_nothing()
    test_update_downloaded_saves_note()
    test_version()
    print("ROUND 7 ALL PASS")


if __name__ == "__main__":
    main()
