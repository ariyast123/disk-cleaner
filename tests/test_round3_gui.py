"""Debug round 3 (UI build): GUI smoke test under a virtual display."""
import os
import sys
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import disk_cleaner_app as gui

# The fixtures live inside the project folder, which the app protects
# as its own home and would never scan. Point "home" at an empty folder
# so the fixture scans behave like a real user's folders. (The
# protection itself is covered at core level in round 4, section 13.)
gui.own_folders = lambda: [os.path.join(HERE, "fake_app_home")]

# Rebuild the shared fixtures first (round 1's script creates them), so
# this round passes regardless of the order the suite runs in - this
# round deletes one fixture file while testing the clean bookkeeping.
import subprocess

subprocess.run([sys.executable, os.path.join(HERE, "test_round1.py")],
               capture_output=True)

FIXTURES = os.path.join(HERE, "fixtures", "profile")

fails = []
app = gui.DiskCleanerApp()
app.update()

for var in app.folder_vars.values():
    var.set(False)
app.custom_folders = [FIXTURES]
app.caches_var.set(False)
app.dup_var.set(True)
app.hogs_var.set(True)
app.large_mb.delete(0, "end")
app.large_mb.insert(0, "1")

app._start_scan()
deadline = time.time() + 30
while app.scanning and time.time() < deadline:
    app.update()
    time.sleep(0.05)
app.update()

if app.scanning:
    fails.append("scan never finished")
if not app.file_iids:
    fails.append("tree is empty after scan")
cats = set(app.cat_iids)
print("categories in tree:", sorted(cats))
for want in ("Large file", "Old installer", "Unused (old)", "Duplicate"):
    if want not in cats:
        fails.append(f"category missing from tree: {want}")

for iid, f in app.file_iids.items():
    if (f.path in app.checked_paths) != f.pre_checked:
        fails.append(f"check state mismatch for {f.path}")
        break

some_iid = next(iter(app.file_iids))
some_path = app.file_iids[some_iid].path
before = some_path in app.checked_paths
app._set_checked(some_iid, not before)
app._refresh_parent(app.tree.parent(some_iid))
app._refresh_selected_label()
if (some_path in app.checked_paths) == before:
    fails.append("toggle did not flip check state")
if "Selected:" not in app.selected_label.cget("text"):
    fails.append(f"selected label broken: {app.selected_label.cget('text')}")
app._set_checked(some_iid, before)

app._select_all()
if len(app.checked_paths) != len(app.results):
    fails.append("Select All did not tick every result")
app._select_none()
if app.checked_paths:
    fails.append("Select None did not clear selection")
app._select_safe()
if app.checked_paths != {f.path for f in app.results if f.pre_checked}:
    fails.append("Safe junk selection mismatch")

checked_before = set(app.checked_paths)
app.filter_var.set("movie")
app._populate_tree()
visible_paths = {f.path for f in app.file_iids.values()}
expected = {f.path for f in app.results if "movie" in f.path.lower()}
if visible_paths != expected:
    fails.append(f"filter result wrong: {visible_paths}")
if app.checked_paths != checked_before:
    fails.append("filtering changed the selection")
app.filter_var.set("")
app._populate_tree()
if len(app.file_iids) != len(app.results):
    fails.append("clearing the filter did not restore all rows")

app.filter_var.set("zzz_no_match_zzz")
app._populate_tree()
if app.file_iids:
    fails.append("no-match filter should show zero rows")
if "match your filter" not in app.empty_label.cget("text"):
    fails.append("no-match empty-state text wrong")
app.filter_var.set("")
app._populate_tree()

victim = app.results[0]
app.checked_paths = {victim.path}
os.remove(victim.path)
app._clean_done([victim], 1, 0, victim.size)
if any(f.path == victim.path for f in app.results):
    fails.append("cleaned file still in results")
if victim.path in app.checked_paths:
    fails.append("cleaned file still ticked")

app._show_hogs([])
app.update()
texts = []


def collect(widget):
    try:
        texts.append(str(widget.cget("text")))
    except Exception:
        pass
    for ch in widget.winfo_children():
        collect(ch)


collect(app.hogs_frame)
if not any("No system space hogs found" in t for t in texts):
    fails.append("hogs empty-state label missing")

app.destroy()
print("RESULT:", "FAIL -> " + "; ".join(fails) if fails else "ALL PASS")
