"""Debug round 8: scan progress percentage - counting pass + bar behaviour."""
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

BASE = os.path.join(HERE, "fixtures8")
os.system(f"rm -rf {BASE}")
os.makedirs(BASE, exist_ok=True)
NOW = time.time()
DAY = 86400
fails = []


def make(path, size, age_days, content=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        if content is not None:
            f.write(content)
        else:
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


# --- 1) count matches the scan's own file counter -------------------------
T = f"{BASE}/tree"
for d in range(4):
    for i in range(100):
        make(f"{T}/dir{d}/f{i:03d}.bin", 64, 1)
hits = []


def prog(n):
    hits.append(n)


found = core.scan(roots=[T], old_days=180, large_bytes=10**9, progress=prog)
total = core.count_files(roots=[T])
if total != 400:
    fails.append(f"count: expected 400 files, got {total}")
if not hits or max(hits) != 400:
    fails.append(f"count: scan's last progress hit should be 400, got {hits[-3:] if hits else hits}")
if total != (max(hits) if hits else None):
    fails.append(f"count: count_files ({total}) != scan progress max ({max(hits) if hits else None})")

# --- 2) skip-list respected, in both modes -------------------------------
S = f"{BASE}/skips"
for i in range(5):
    make(f"{S}/keep/f{i}.bin", 64, 1)
for i in range(50):
    make(f"{S}/node_modules/f{i}.bin", 64, 1)
for i in range(10):
    make(f"{S}/.git/f{i}.bin", 64, 1)
for i in range(7):
    make(f"{S}/Windows/f{i}.bin", 64, 1)
if core.count_files(roots=[S]) != 5:
    fails.append(f"count skips: normal mode should count 5, got {core.count_files(roots=[S])}")
if core.count_files(roots=[S], include_system=True) != 12:
    fails.append(
        f"count skips: full mode should count 12 (Windows walked, "
        f"node_modules/.git still skipped), got {core.count_files(roots=[S], include_system=True)}"
    )

# --- 3) cache targets: single file + folder ------------------------------
C = f"{BASE}/cache"
make(f"{C}/single.dat", 100, 1)
for i in range(3):
    make(f"{C}/dir/c{i}.bin", 64, 1)
single = core.count_files(
    roots=[], cache_targets=[("Cache", f"{C}/single.dat", "", True)])
if single != 1:
    fails.append(f"count cache: single-file target should count 1, got {single}")
folder = core.count_files(
    roots=[], cache_targets=[("Cache", f"{C}/dir", "", True)])
if folder != 3:
    fails.append(f"count cache: folder target should count 3, got {folder}")

# --- 4) temp dir already in roots is counted once ------------------------
if core.count_files(roots=[T], temp_dirs=[T]) != 400:
    fails.append(
        f"count temp: temp dir already in roots counted twice: "
        f"{core.count_files(roots=[T], temp_dirs=[T])}"
    )

# --- 5) extra_protected dir is excluded ----------------------------------
P = f"{BASE}/prot"
for i in range(6):
    make(f"{P}/open/f{i}.bin", 64, 1)
for i in range(9):
    make(f"{P}/secret/f{i}.bin", 64, 1)
if core.count_files(roots=[P], extra_protected=[f"{P}/secret"]) != 6:
    fails.append(
        f"count protected: expected 6, got "
        f"{core.count_files(roots=[P], extra_protected=[f'{P}/secret'])}"
    )

# --- 6) cancel during the count returns early ----------------------------
ev = threading.Event()
ev.set()
if core.count_files(roots=[T], cancel_event=ev) != 0:
    fails.append("count cancel: pre-set event should return 0 at once")
missing = core.count_files(roots=[f"{BASE}/does-not-exist"])
if missing != 0:
    fails.append(f"count missing: nonexistent root should count 0, got {missing}")

# --- 7) GUI: queue messages drive the bar --------------------------------
app = gui.DiskCleanerApp()
app.update()
try:
    app.ui_queue.put(("counting",))
    pump(app, 0.4)
    if app.status.cget("text") != "Counting files...":
        fails.append(f"gui counting: status {app.status.cget('text')!r}")

    app.ui_queue.put(("scan_total", 1000))
    pump(app, 0.4)
    if str(app.progress.cget("mode")) != "determinate":
        fails.append(f"gui total: bar should be determinate, got {app.progress.cget('mode')}")
    if abs(app.progress.get() - 0.0) > 0.01:
        fails.append(f"gui total: bar should start at 0, got {app.progress.get()}")
    if "(0%)" not in app.status.cget("text"):
        fails.append(f"gui total: status should show 0%, got {app.status.cget('text')!r}")

    app.ui_queue.put(("progress", 500))
    pump(app, 0.4)
    if app.status.cget("text") != "Scanning... 500 files checked (50%)":
        fails.append(f"gui progress: status {app.status.cget('text')!r}")
    if abs(app.progress.get() - 0.5) > 0.01:
        fails.append(f"gui progress: bar should be 0.5, got {app.progress.get()}")

    # Over-count (unreadable files, single-file caches): capped at 99%.
    app.ui_queue.put(("progress", 5000))
    pump(app, 0.4)
    if "(99%)" not in app.status.cget("text"):
        fails.append(f"gui cap: status should show 99%, got {app.status.cget('text')!r}")
    if app.progress.get() > 0.99 + 0.01:
        fails.append(f"gui cap: bar should never pass 0.99 mid-scan, got {app.progress.get()}")

    # No total known (old-style scan): plain counter text, no crash.
    app.ui_queue.put(("scan_total", 0))
    pump(app, 0.4)
    app.ui_queue.put(("progress", 123))
    pump(app, 0.4)
    if app.status.cget("text") != "Scanning... 123 files checked":
        fails.append(f"gui no-total: status {app.status.cget('text')!r}")

    # --- 8) GUI end to end: real scan, count pass runs, scan finishes ----
    for var in app.folder_vars.values():
        var.set(False)
    app.custom_folders = [T]
    app.caches_var.set(False)
    app.hogs_var.set(False)
    app.dup_var.set(False)
    app._start_scan()
    if not wait_until(app, lambda: not app.scanning):
        fails.append("gui e2e: scan never finished")
    if not app.status.cget("text").startswith("Done."):
        fails.append(f"gui e2e: status should start with 'Done.', got {app.status.cget('text')!r}")
    if abs(app.progress.get() - 1.0) > 0.01:
        fails.append(f"gui e2e: bar should end at 1.0, got {app.progress.get()}")
finally:
    app.destroy()

print("RESULT:", "FAIL -> " + "; ".join(fails) if fails else "ALL PASS")
