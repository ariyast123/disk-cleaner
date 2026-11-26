"""Debug round 9: biggest-folders view - core aggregation + tab behaviour."""
import os
import sys
import threading
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import cleaner_core as core
import disk_cleaner_app as gui

# Same note as round 3: fixtures live inside the project folder, which
# the app protects as its own home - point "home" elsewhere for tests.
gui.own_folders = lambda: [os.path.join(HERE, "fake_app_home")]

BASE = os.path.join(HERE, "fixtures9")
os.system(f"rm -rf {BASE}")
os.makedirs(BASE, exist_ok=True)
NOW = time.time()
DAY = 86400
fails = []


def make(path, size, age_days=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)
    t = NOW - age_days * DAY
    os.utime(path, (t, t))


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


# --- 1) aggregation: order, sizes, counts, direct-files bucket ----------
T = f"{BASE}/tree"
for i in range(3):
    make(f"{T}/big/f{i}.bin", 500)
for i in range(2):
    make(f"{T}/small/f{i}.bin", 100)
make(f"{T}/loose.bin", 50)
# A nested folder folds into its top-level parent.
make(f"{T}/big/deep/nested.bin", 500)

got = core.top_folders(roots=[T])
want = [(f"{T}/big", 2000, 4), (f"{T}/small", 200, 2), (T, 50, 1)]
if got != want:
    fails.append(f"aggregate: expected {want}, got {got}")

# --- 2) limit -------------------------------------------------------------
if core.top_folders(roots=[T], limit=2) != want[:2]:
    fails.append(
        f"limit: expected top 2 {want[:2]}, "
        f"got {core.top_folders(roots=[T], limit=2)}"
    )

# --- 3) skip-list respected, in both modes -------------------------------
S = f"{BASE}/skips"
for i in range(5):
    make(f"{S}/keep/f{i}.bin", 64)
for i in range(50):
    make(f"{S}/node_modules/f{i}.bin", 64)
for i in range(10):
    make(f"{S}/.git/f{i}.bin", 64)
for i in range(7):
    make(f"{S}/Windows/f{i}.bin", 64)
if core.top_folders(roots=[S]) != [(f"{S}/keep", 320, 5)]:
    fails.append(
        f"skips: normal mode should list only keep, "
        f"got {core.top_folders(roots=[S])}"
    )
full = core.top_folders(roots=[S], include_system=True)
if full != [(f"{S}/Windows", 448, 7), (f"{S}/keep", 320, 5)]:
    fails.append(
        f"skips: full mode should list Windows + keep, got {full}"
    )

# --- 4) overlapping roots / temp dir count each file once ----------------
once = core.top_folders(roots=[T])
twice = core.top_folders(roots=[T, f"{T}/big"])
if once != twice:
    fails.append(f"overlap: roots [T, T/big] double-counted: {twice} vs {once}")
temp_twice = core.top_folders(roots=[T], temp_dirs=[T])
if once != temp_twice:
    fails.append(f"overlap: temp dir already in roots double-counted: {temp_twice}")

# --- 5) extra_protected dir is excluded ----------------------------------
P = f"{BASE}/prot"
for i in range(6):
    make(f"{P}/open/f{i}.bin", 64)
for i in range(9):
    make(f"{P}/secret/f{i}.bin", 64)
if core.top_folders(roots=[P], extra_protected=[f"{P}/secret"]) != [
    (f"{P}/open", 384, 6)
]:
    fails.append(
        f"protected: expected only open, "
        f"got {core.top_folders(roots=[P], extra_protected=[f'{P}/secret'])}"
    )

# --- 6) cancel / missing root --------------------------------------------
ev = threading.Event()
ev.set()
if core.top_folders(roots=[T], cancel_event=ev) != []:
    fails.append("cancel: pre-set event should return [] at once")
if core.top_folders(roots=[f"{BASE}/does-not-exist"]) != []:
    fails.append("missing: nonexistent root should return []")

# --- 7) GUI: tab exists, empty state, rows render ------------------------
import customtkinter as ctk

app = gui.DiskCleanerApp()
app.update()
try:
    tab_names = list(getattr(app.tabs, "_tab_dict", {}).keys())
    if "Biggest folders" not in tab_names:
        fails.append(f"gui tab: 'Biggest folders' missing, tabs are {tab_names}")
    if not app.folders_frame.winfo_exists():
        fails.append("gui tab: folders frame missing")

    texts = []

    def collect(widget):
        try:
            texts.append(str(widget.cget("text")))
        except Exception:
            pass
        for ch in widget.winfo_children():
            collect(ch)

    # Empty state on first launch.
    texts.clear()
    collect(app.folders_frame)
    if not any("No folders scanned yet" in t for t in texts):
        fails.append("gui empty: empty-state label missing")

    # Rendered rows: path, size, file count, bar scaled to the largest.
    sample = [(f"{T}/big", 2000, 4), (f"{T}/small", 200, 2), (T, 50, 1)]
    app._scan_roots = [T]
    app._show_top_folders(sample)
    app.update()
    if app.top_folders != sample:
        fails.append("gui render: app.top_folders not stored")
    texts.clear()
    collect(app.folders_frame)
    for needle in (f"{T}/big", "2.0 KB", "4 files", "200 B",
                   "(files directly in this folder)"):
        if not any(needle in t for t in texts):
            fails.append(f"gui render: {needle!r} not shown: {texts}")
    bars = []

    def collect_bars(widget):
        if isinstance(widget, ctk.CTkProgressBar):
            bars.append(widget.get())
        for ch in widget.winfo_children():
            collect_bars(ch)

    collect_bars(app.folders_frame)
    if len(bars) != 3:
        fails.append(f"gui bars: expected 3 bars, found {len(bars)}")
    elif abs(bars[0] - 1.0) > 0.01 or abs(bars[1] - 0.1) > 0.01:
        fails.append(f"gui bars: expected [1.0, 0.1, 0.025], got {bars}")

    # The Open button opens the folder (on Linux os.startfile does not
    # exist - the call must fail silently, not crash the app).
    opened = []

    def collect_buttons(widget):
        if isinstance(widget, ctk.CTkButton) and widget.cget("text") == "Open":
            opened.append(widget)
        for ch in widget.winfo_children():
            collect_buttons(ch)

    collect_buttons(app.folders_frame)
    if not opened:
        fails.append("gui open: no Open button on folder rows")
    else:
        try:
            opened[0].invoke()
            app.update()
        except Exception as exc:
            fails.append(f"gui open: invoking Open raised {exc!r}")

    # --- 8) GUI end to end: real scan fills the tab, Clear empties it ----
    for var in app.folder_vars.values():
        var.set(False)
    app.custom_folders = [T]
    app.caches_var.set(False)
    app.hogs_var.set(False)
    app.dup_var.set(False)
    app._start_scan()
    if not wait_until(app, lambda: not app.scanning):
        fails.append("gui e2e: scan never finished")
    if app.top_folders != want:
        fails.append(f"gui e2e: expected {want}, got {app.top_folders}")
    texts.clear()
    collect(app.folders_frame)
    if not any(f"{T}/big" in t for t in texts):
        fails.append("gui e2e: biggest folder not shown in tab")

    app._clear_scan()
    app.update()
    if app.top_folders != []:
        fails.append("gui clear: top_folders not cleared")
    texts.clear()
    collect(app.folders_frame)
    if not any("No folders scanned yet" in t for t in texts):
        fails.append("gui clear: empty-state label missing after Clear scan")
finally:
    app.destroy()

print("RESULT:", "FAIL -> " + "; ".join(fails) if fails else "ALL PASS")
