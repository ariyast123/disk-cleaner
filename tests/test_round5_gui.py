"""Debug round 5: GUI interactions - cancel, real clean, clicks, layout."""
import os
import sys
import time
import types

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import cleaner_core as core
import disk_cleaner_app as gui

# Same note as round 3: fixtures live inside the project folder, which
# the app protects as its own home - point "home" elsewhere for tests.
gui.own_folders = lambda: [os.path.join(HERE, "fake_app_home")]

BASE = os.path.join(HERE, "fixtures5")
os.system(f"rm -rf {BASE}")
os.makedirs(BASE, exist_ok=True)
fails = []


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.03)


def wait_until(app, cond, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if cond():
            return True
        time.sleep(0.03)
    return cond()


app = gui.DiskCleanerApp()
app.update()
for var in app.folder_vars.values():
    var.set(False)
app.custom_folders = [BASE]
app.caches_var.set(False)
app.hogs_var.set(False)
app.dup_var.set(False)

# --- 1) cancel mid-scan + double-start guard (slow fake scan) -------------
real_scan = gui.core.scan
calls = {"n": 0}


def fake_scan(**kwargs):
    calls["n"] += 1
    kwargs["progress"](123)
    kwargs["cancel_event"].wait(timeout=15)
    return [core.FoundFile("/tmp/fake.bin", 2048, time.time(), core.CAT_LARGE, "", False)]


gui.core.scan = fake_scan
try:
    app._start_scan()
    app._start_scan()  # must be ignored while a scan is running
    pump(app, 0.6)
    if calls["n"] != 1:
        fails.append(f"double-start: worker spawned {calls['n']} times")
    if "123 files checked" not in app.status.cget("text"):
        fails.append(f"progress not shown: {app.status.cget('text')}")
    app._cancel()
    if not wait_until(app, lambda: not app.scanning):
        fails.append("cancel: scan never finished")
    status = app.status.cget("text")
    if not status.startswith("Cancelled"):
        fails.append(f"cancel: status should start with 'Cancelled', got: {status}")
    if str(app.scan_btn.cget("state")) != "normal":
        fails.append("cancel: Scan button not re-enabled")
    if len(app.file_iids) != 1:
        fails.append("cancel: partial results not shown in tree")
finally:
    gui.core.scan = real_scan

# --- 2) real clean flow through send2trash --------------------------------
CLEAN = os.path.join(BASE, "cleanme")
os.makedirs(CLEAN, exist_ok=True)
old = time.time() - 400 * 86400
targets = []
for name in ("a_old.txt", "b_old.txt", "c_old.txt"):
    p = os.path.join(CLEAN, name)
    with open(p, "w") as fh:
        fh.write("x" * 100)
    os.utime(p, (old, old))
    targets.append(p)
app.custom_folders = [CLEAN]
app._start_scan()
if not wait_until(app, lambda: not app.scanning and len(app.file_iids) == 3):
    fails.append(f"clean setup: expected 3 rows, got {len(app.file_iids)}")
app._select_all()
log_path = os.path.join(os.path.expanduser("~"), "DiskCleaner", "cleanup_log.txt")
log_before = ""
if os.path.exists(log_path):
    with open(log_path, encoding="utf-8") as fh:
        log_before = fh.read()
real_ask = gui.messagebox.askyesno
gui.messagebox.askyesno = lambda *a, **k: True
try:
    app._clean_selected()
    wait_until(app, lambda: str(app.clean_btn.cget("state")) == "normal", timeout=30)
finally:
    gui.messagebox.askyesno = real_ask
gone = [p for p in targets if not os.path.exists(p)]
still = [p for p in targets if os.path.exists(p)]
result_paths = {f.path for f in app.results}
for p in gone:
    if p in result_paths:
        fails.append(f"clean: trashed file still listed: {p}")
for p in still:  # send2trash unavailable in this VM -> file must stay listed
    if p not in result_paths:
        fails.append(f"clean: skipped file wrongly removed from list: {p}")
if not os.path.exists(log_path):
    fails.append("clean: log file was not written")
else:
    with open(log_path, encoding="utf-8") as fh:
        new_log = fh.read()[len(log_before):]
    if new_log.count("OK ") + new_log.count("SKIP ") != 3:
        fails.append(f"clean: log should record 3 files, got:\n{new_log}")
status = app.status.cget("text")
if "Moved" not in status or "Skipped" not in status:
    fails.append(f"clean: summary status missing: {status}")

# --- 3) hog copy action lands in the clipboard -----------------------------
hog = core.HogInfo("Hibernation file (hiberfil.sys)", "/x", 100, "d",
                   "Copy the command", "copy", "powercfg /hibernate off")
app._hog_action(hog)
app.update()
try:
    clip = app.clipboard_get()
except Exception:
    clip = ""
if clip != "powercfg /hibernate off":
    fails.append(f"clipboard: got {clip!r}")

# --- 4) real mouse-click simulation on the tree ----------------------------
# Own fixture profile (the suite must not depend on other rounds' files).
PROFILE5 = os.path.join(BASE, "profile")
_old = time.time() - 90 * 86400
os.makedirs(os.path.join(PROFILE5, "Downloads"), exist_ok=True)
os.makedirs(os.path.join(PROFILE5, "Documents"), exist_ok=True)
with open(os.path.join(PROFILE5, "Downloads", "movie.mp4"), "wb") as fh:
    fh.truncate(2 * 1024 * 1024)
_p = os.path.join(PROFILE5, "Downloads", "setup_old.exe")
with open(_p, "wb") as fh:
    fh.truncate(10_000)
os.utime(_p, (_old, _old))
for _name, _age in (("dup_a.bin", 3), ("dup_b.bin", 1)):
    _p = os.path.join(PROFILE5, "Documents", _name)
    with open(_p, "wb") as fh:
        fh.write(b"D" * 5000)
    _t = time.time() - _age * 86400
    os.utime(_p, (_t, _t))
app.custom_folders = [PROFILE5]
app.caches_var.set(False)
app.dup_var.set(True)
app.large_mb.delete(0, "end")
app.large_mb.insert(0, "1")
app._start_scan()
if not wait_until(app, lambda: not app.scanning and app.file_iids):
    fails.append("click setup: scan produced no rows")
else:
    parent = next(iter(app.cat_iids.values()))
    kids = app.tree.get_children(parent)
    bbox = app.tree.bbox(parent)
    if not bbox:
        fails.append("click: parent row has no bbox (not visible)")
    else:
        ev = types.SimpleNamespace(x=5, y=bbox[1] + 2)
        before = {app.file_iids[k].path in app.checked_paths for k in kids}
        app._on_tree_click(ev)
        after = {app.file_iids[k].path in app.checked_paths for k in kids}
        if before == after:
            fails.append("click: parent click did not toggle its children")
        # single file click toggles just that file
        kid = kids[0]
        kb = app.tree.bbox(kid)
        ev2 = types.SimpleNamespace(x=5, y=kb[1] + 2)
        one_before = app.file_iids[kid].path in app.checked_paths
        app._on_tree_click(ev2)
        if (app.file_iids[kid].path in app.checked_paths) == one_before:
            fails.append("click: file click did not toggle the file")

# --- 5) filter debounce populates without a manual call --------------------
app.filter_var.set("movie")
pump(app, 0.6)
visible = {os.path.basename(f.path) for f in app.file_iids.values()}
if visible != {"movie.mp4"}:
    fails.append(f"debounce: expected only movie.mp4 visible, got {visible}")
app.filter_var.set("")
pump(app, 0.6)

# --- 6) layout at minimum window size: Scan button fully visible -----------
app.geometry("1020x640")
pump(app, 0.5)
win_bottom = app.winfo_rooty() + app.winfo_height()
btn_bottom = app.scan_btn.winfo_rooty() + app.scan_btn.winfo_height()
if btn_bottom > win_bottom + 2:
    fails.append(f"layout: Scan button bottom {btn_bottom} beyond window bottom {win_bottom}")
app.geometry("1240x800")
pump(app, 0.3)
win_bottom = app.winfo_rooty() + app.winfo_height()
btn_bottom = app.scan_btn.winfo_rooty() + app.scan_btn.winfo_height()
if btn_bottom > win_bottom + 2:
    fails.append("layout: Scan button not visible at default size either")

# --- 7) double-click opens the file itself; reveal uses explorer /select ---
app.filter_var.set("")
pump(app, 0.5)
if app.file_iids:
    kid = next(iter(app.file_iids))
    target = app.file_iids[kid]
    opened = []
    had_startfile = hasattr(os, "startfile")
    real_startfile = getattr(os, "startfile", None)
    os.startfile = lambda p: opened.append(p)
    try:
        kb = app.tree.bbox(kid)
        app._on_tree_double_click(types.SimpleNamespace(x=100, y=kb[1] + 2))
        if opened != [target.path]:
            fails.append(f"open: double-click opened {opened}, expected [{target.path}]")
        opened.clear()
        gui.DiskCleanerApp._open_folder(target.path)
        if opened != [os.path.dirname(target.path)]:
            fails.append(f"open folder: got {opened}")
    finally:
        if had_startfile:
            os.startfile = real_startfile
        else:
            del os.startfile
    popen_calls = []
    real_popen = gui.subprocess.Popen
    gui.subprocess.Popen = lambda args, **kw: popen_calls.append(args)
    try:
        gui.DiskCleanerApp._reveal_in_explorer(target.path)
    finally:
        gui.subprocess.Popen = real_popen
    if popen_calls != [["explorer.exe", f"/select,{target.path}"]]:
        fails.append(f"reveal: wrong explorer command: {popen_calls}")
else:
    fails.append("open/reveal: no rows available to test")

# --- 8) custom folders are removable; full-scan defaults to off ------------
if app.full_var.get():
    fails.append("full system scan must default to OFF")
app.custom_folders = ["/some/path/A", "/some/path/B"]
app._refresh_custom_folders()
app.update()
rows_before = len(app.custom_frame.winfo_children())
app._remove_folder("/some/path/A")
if app.custom_folders != ["/some/path/B"]:
    fails.append(f"remove folder: list is {app.custom_folders}")
app.update()
if len(app.custom_frame.winfo_children()) >= rows_before:
    fails.append("remove folder: sidebar rows did not shrink")
app._remove_folder("/some/path/B")
if app.custom_folders != []:
    fails.append("remove folder: list not emptied")

# --- 9) Clear scan wipes results; a fresh rescan still works ---------------
app.custom_folders = [PROFILE5]
app.caches_var.set(False)
app.dup_var.set(False)
app._start_scan()
if not wait_until(app, lambda: not app.scanning and app.file_iids):
    fails.append("clear setup: scan produced no rows")
else:
    app._select_all()
    app._clear_scan()
    app.update()
    if app.results or app.file_iids or app.checked_paths:
        fails.append("clear: results/selection not emptied")
    if "No results yet" not in app.empty_label.cget("text"):
        fails.append("clear: empty-state text wrong after clear")
    if "Cleared" not in app.status.cget("text"):
        fails.append("clear: status not updated")
    app._start_scan()
    if not wait_until(app, lambda: not app.scanning and app.file_iids):
        fails.append("clear: rescan after clear produced no rows")

# --- 10) cleaning can be cancelled mid-way; the rest stay listed + ticked ---
CLEAN2 = os.path.join(BASE, "cleanme2")
os.makedirs(CLEAN2, exist_ok=True)
paths2 = []
for name in ("m1.txt", "m2.txt", "m3.txt", "m4.txt"):
    p = os.path.join(CLEAN2, name)
    with open(p, "w") as fh:
        fh.write("y" * 50)
    os.utime(p, (old, old))
    paths2.append(p)
app.custom_folders = [CLEAN2]
app._start_scan()
if not wait_until(app, lambda: not app.scanning and len(app.file_iids) == 4):
    fails.append("clean-cancel setup: expected 4 rows")
else:
    app._select_all()
    calls = {"n": 0}
    real_trash = gui.send2trash

    def fake_trash(p):
        calls["n"] += 1
        os.remove(p)  # simulate a successful move to the Recycle Bin
        if calls["n"] == 2:
            app.cancel_event.set()

    gui.send2trash = fake_trash
    real_ask2 = gui.messagebox.askyesno
    gui.messagebox.askyesno = lambda *a, **k: True
    try:
        app._clean_selected()
        wait_until(app, lambda: not app.cleaning, timeout=30)
    finally:
        gui.send2trash = real_trash
        gui.messagebox.askyesno = real_ask2
    remaining_paths = {f.path for f in app.results}
    if calls["n"] != 2:
        fails.append(f"clean-cancel: trash called {calls['n']} times, expected 2")
    if len(remaining_paths) != 2:
        fails.append(f"clean-cancel: expected 2 unprocessed files listed, got {remaining_paths}")
    if not all(p in app.checked_paths for p in remaining_paths):
        fails.append("clean-cancel: unprocessed files lost their ticks")
    if "not processed" not in app.status.cget("text"):
        fails.append(f"clean-cancel: status should mention unprocessed files: {app.status.cget('text')}")
    if app.cleaning:
        fails.append("clean-cancel: cleaning flag stuck on")

# --- 11) self-update helpers: version compare, validation, apply, banner --
if not (gui.parse_version("1.2.0") > gui.parse_version("1.1.0")):
    fails.append("parse_version: 1.2.0 should beat 1.1.0")
if gui.parse_version("1.1.0") != gui.parse_version("1.1"):
    fails.append("parse_version: 1.1.0 should equal 1.1")
if not (gui.parse_version("2.0") > gui.parse_version("1.9.9")):
    fails.append("parse_version: 2.0 should beat 1.9.9")
good = {
    "disk_cleaner_app.py": b"X = 1\n",
    "cleaner_core.py": b"Y = 2\n",
    "build.bat": b"@echo off\n",
}
if not gui.validate_update_files(good):
    fails.append("validate_update_files: valid set rejected")
broken = dict(good)
broken["cleaner_core.py"] = b"def broken(:\n"
if gui.validate_update_files(broken):
    fails.append("validate_update_files: broken python accepted")
missing = dict(good)
del missing["build.bat"]
if gui.validate_update_files(missing):
    fails.append("validate_update_files: incomplete set accepted")
UPD = os.path.join(BASE, "updproj")
os.makedirs(UPD, exist_ok=True)
with open(os.path.join(UPD, "cleaner_core.py"), "w") as fh:
    fh.write("OLD = True\n")
gui.apply_update_files(UPD, {"cleaner_core.py": b"NEW = True\n"})
with open(os.path.join(UPD, "cleaner_core.py")) as fh:
    if fh.read() != "NEW = True\n":
        fails.append("apply_update_files: content not replaced")
app._show_update_banner({"version": "9.9.9", "notes": "test notes"})
app.update()
if not app.update_banner.winfo_ismapped():
    fails.append("update banner: not visible after _show_update_banner")
if "9.9.9" not in app.update_label.cget("text"):
    fails.append("update banner: label missing the version")
app.update_banner.pack_forget()

# --- 12) update helper: auto build + log, copy-back, relaunch launched --
# (hotfix Nov 22, 2026: build.bat used to pause forever unattended)
PROJ = os.path.join(HERE, "..")
LAUNCHED = os.path.join("C:\\Users\\Ariya", "Desktop", "DiskCleaner.exe")
lines = gui.update_helper_lines(PROJ, LAUNCHED)
joined = "\n".join(lines)
if "call build.bat auto >> update_build.log 2>&1" not in joined:
    fails.append("helper: build must run as 'call build.bat auto >> update_build.log 2>&1'")
if any(l.strip() == "call build.bat" for l in lines):
    fails.append("helper: bare 'call build.bat' (no auto) would pause forever")
if 'if /I not "%BUILT%"=="%LAUNCHED%" copy /Y "%BUILT%" "%LAUNCHED%" >NUL' not in joined:
    fails.append("helper: missing copy-back of the fresh exe over the launched copy")
if 'start "" "%LAUNCHED%"' not in joined:
    fails.append("helper: relaunch must start the launched copy, not dist")
if 'start "" "%BUILT%"' in joined:
    fails.append("helper: must not relaunch the dist exe directly")
if f'set "LAUNCHED={LAUNCHED}"' not in joined:
    fails.append("helper: LAUNCHED not set to the passed exe path")
built = os.path.join(PROJ, "dist", "DiskCleaner.exe")
if f'set "BUILT={built}"' not in joined:
    fails.append("helper: BUILT not set to the dist exe path")
if 'if exist "%LAUNCHED%" start "" "%LAUNCHED%"' not in joined:
    fails.append("helper: build failure must fall back to relaunching the old copy")
# build.bat itself: pause only when NOT called with "auto", on both paths
with open(os.path.join(PROJ, "build.bat"), encoding="utf-8") as fh:
    bat = fh.read()
if bat.count('if /I not "%~1"=="auto" pause') != 2:
    fails.append("build.bat: expected exactly 2 conditional pauses (success + error paths)")
for _l in bat.splitlines():
    if _l.strip() == "pause":
        fails.append("build.bat: bare 'pause' would stall an unattended update")
        break
# _write_update_helper writes the same lines with the real launched exe
HELPER_DIR = os.path.join(BASE, "helperproj")
os.makedirs(HELPER_DIR, exist_ok=True)
real_proj_folder = gui.project_folder
real_popen2 = gui.subprocess.Popen
popen_calls2 = []
gui.project_folder = lambda: HELPER_DIR
gui.subprocess.Popen = lambda args, **kw: popen_calls2.append(args)
try:
    app._write_update_helper()
finally:
    gui.project_folder = real_proj_folder
    gui.subprocess.Popen = real_popen2
helper_path = os.path.join(HELPER_DIR, "finish_update.bat")
if not os.path.exists(helper_path):
    fails.append("_write_update_helper: finish_update.bat not written")
else:
    with open(helper_path, encoding="utf-8") as fh:
        written = fh.read()
    if "call build.bat auto >> update_build.log 2>&1" not in written:
        fails.append("_write_update_helper: written helper lacks the auto build call")
    if f'set "LAUNCHED={sys.executable}"' not in written:
        fails.append("_write_update_helper: launched exe should be sys.executable")
    if 'copy /Y "%BUILT%" "%LAUNCHED%"' not in written:
        fails.append("_write_update_helper: written helper lacks the copy-back")
if popen_calls2 != [["explorer.exe", helper_path]]:
    fails.append(f"_write_update_helper: helper should be handed to Explorer: {popen_calls2}")
# Fallback: if Explorer cannot start, the helper runs detached via cmd.
popen_calls3 = []


def _popen_fallback(args, **kw):
    popen_calls3.append((args, kw))
    if args[0] == "explorer.exe":
        raise OSError("no explorer")
    return None


gui.project_folder = lambda: HELPER_DIR
gui.subprocess.Popen = _popen_fallback
try:
    app._write_update_helper()
finally:
    gui.project_folder = real_proj_folder
    gui.subprocess.Popen = real_popen2
if len(popen_calls3) != 2 or popen_calls3[0][0] != ["explorer.exe", helper_path] \
        or popen_calls3[1][0] != ["cmd", "/c", helper_path]:
    fails.append(f"_write_update_helper: Explorer failure should fall back to cmd /c: {popen_calls3}")

# --- 13) Biggest folders tab: ranked rows, open, empty roots -------------
BIG = os.path.join(BASE, "bigfold")
os.makedirs(os.path.join(BIG, "games"), exist_ok=True)
os.makedirs(os.path.join(BIG, "photos"), exist_ok=True)
with open(os.path.join(BIG, "games", "g.bin"), "wb") as fh:
    fh.truncate(3 * 1024 * 1024)
with open(os.path.join(BIG, "photos", "p.bin"), "wb") as fh:
    fh.truncate(1024 * 1024)
app.custom_folders = [BIG]
app._find_biggest_folders()
if not wait_until(app, lambda: not app.biggest_running and app.biggest_entries, timeout=20):
    fails.append("biggest: run did not finish")
else:
    paths = [os.path.basename(e.path) for e in app.biggest_entries]
    if paths != ["games", "photos"]:
        fails.append(f"biggest: expected [games, photos], got {paths}")
    if len(app.biggest_frame.winfo_children()) != 2:
        fails.append(f"biggest: expected 2 cards, got {len(app.biggest_frame.winfo_children())}")
    if "Top 2 folders" not in app.biggest_status.cget("text"):
        fails.append(f"biggest: status wrong: {app.biggest_status.cget('text')}")
    if str(app.biggest_btn.cget("state")) != "normal":
        fails.append("biggest: button not re-enabled after the run")
    # Open opens the folder itself (not its parent).
    opened = []
    had_startfile = hasattr(os, "startfile")
    real_startfile = getattr(os, "startfile", None)
    os.startfile = lambda p: opened.append(p)
    try:
        gui.DiskCleanerApp._open_directory(os.path.join(BIG, "games"))
        if opened != [os.path.join(BIG, "games")]:
            fails.append(f"biggest open: got {opened}")
    finally:
        if had_startfile:
            os.startfile = real_startfile
        else:
            del os.startfile
# No roots -> info dialog, no run started.
for var in app.folder_vars.values():
    var.set(False)
app.custom_folders = []
infos = []
real_info = gui.messagebox.showinfo
gui.messagebox.showinfo = lambda *a, **k: infos.append(a)
try:
    app._find_biggest_folders()
finally:
    gui.messagebox.showinfo = real_info
if not infos or "Nothing to scan" not in str(infos[0]):
    fails.append(f"biggest: empty roots should show the info dialog, got {infos}")
if app.biggest_running:
    fails.append("biggest: run must not start with no roots")

app.destroy()
print("RESULT:", "FAIL -> " + "; ".join(fails) if fails else "ALL PASS")
