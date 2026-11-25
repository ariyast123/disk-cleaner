"""Debug round 4: core stress - overlaps, unicode, hash traps, Steam, scale."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cleaner_core as core

BASE = os.path.join(os.path.dirname(__file__), "fixtures4")
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


P = f"{BASE}/profile"
# --- 1) overlapping roots: a plain recent file must NOT become a self-duplicate
make(f"{P}/Downloads/plain_recent.txt", 3000, 1, content=b"P" * 3000)
make(f"{P}/Downloads/real_a.bin", 0, 5, content=b"R" * 6000)
make(f"{P}/Documents/real_b.bin", 0, 2, content=b"R" * 6000)
found = core.scan(roots=[P, f"{P}/Downloads"], find_duplicates=True,
                  large_bytes=10 * 1024 * 1024, old_days=3650, installer_days=3650)
names = {os.path.basename(f.path): f for f in found}
if "plain_recent.txt" in names:
    fails.append(f"overlap: plain file falsely flagged as {names['plain_recent.txt'].category} "
                 f"(note: {names['plain_recent.txt'].note})")
if "real_a.bin" not in names or names["real_a.bin"].category != core.CAT_DUPLICATE:
    fails.append("overlap: real duplicate (older copy) not detected")
if "real_b.bin" in names:
    fails.append("overlap: newest copy should be the keeper, not flagged")

# --- 2) triple duplicate: exactly two flagged, newest kept
T = f"{BASE}/triple"
for i, age in enumerate((30, 20, 10)):
    make(f"{T}/copy{i}.dat", 0, age, content=b"T" * 9000)
found = core.scan(roots=[T], find_duplicates=True, large_bytes=10**9, old_days=3650)
dups = [f for f in found if f.category == core.CAT_DUPLICATE]
if len(dups) != 2:
    fails.append(f"triple: expected 2 duplicates flagged, got {len(dups)}")
if any("copy2.dat" in f.note for f in dups) is False and dups:
    fails.append("triple: notes should point at copy2.dat (newest) as keeper")

# --- 3) partial-hash trap: same head, different tail -> NOT duplicates
H = f"{BASE}/hash"
head = b"H" * (1536 * 1024)
make(f"{H}/h1.bin", 0, 3, content=head + b"1" * (512 * 1024))
make(f"{H}/h2.bin", 0, 2, content=head + b"2" * (512 * 1024))
make(f"{H}/h3.bin", 0, 4, content=head + b"1" * (512 * 1024))  # identical to h1
found = core.scan(roots=[H], find_duplicates=True, large_bytes=10**9, old_days=3650)
names = {os.path.basename(f.path): f for f in found}
if "h2.bin" in names:
    fails.append("hash trap: h2 differs in tail but was flagged")
if "h3.bin" not in names or names["h3.bin"].category != core.CAT_DUPLICATE:
    fails.append("hash trap: h3 (identical to h1, older) should be the duplicate")

# --- 4) unicode / Persian filenames
U = f"{BASE}/unicode"
make(f"{U}/ویدیو جدید 🎬.mp4", 2 * 1024 * 1024, 5)
make(f"{U}/آهنگ (کپی).mp3", 0, 8, content=b"U" * 4000)
make(f"{U}/آهنگ.mp3", 0, 3, content=b"U" * 4000)
found = core.scan(roots=[U], find_duplicates=True, large_bytes=1024 * 1024, old_days=3650)
names = {os.path.basename(f.path): f for f in found}
if names.get("ویدیو جدید 🎬.mp4", None) is None or names["ویدیو جدید 🎬.mp4"].category != core.CAT_LARGE:
    fails.append("unicode: Persian-named large file not categorized")
if names.get("آهنگ (کپی).mp3", None) is None or names["آهنگ (کپی).mp3"].category != core.CAT_DUPLICATE:
    fails.append("unicode: Persian-named duplicate not detected")

# --- 5) deep path (>260 chars)
deep = BASE
for i in range(18):
    deep = os.path.join(deep, f"level_{i:02d}_with_a_long_name")
make(os.path.join(deep, "buried_old.txt"), 100, 500)
found = core.scan(roots=[BASE + "/deep_root_marker_ne"], old_days=180) if False else \
    core.scan(roots=[os.path.join(BASE, "level_00_with_a_long_name")], old_days=180,
              large_bytes=10**9)
if not any(f.path.endswith("buried_old.txt") and f.category == core.CAT_OLD for f in found):
    fails.append("deep path: buried old file not found")

# --- 6) cache target that is a FILE + nonexistent targets
thumb = f"{BASE}/thumbcache_256.db"
make(thumb, 12345, 40)
found = core.scan(
    roots=[],
    cache_targets=[
        ("Thumbnail & icon cache", thumb, "", True),
        ("Ghost cache", f"{BASE}/does_not_exist", "", True),
    ],
)
if len(found) != 1 or found[0].category != "Thumbnail & icon cache":
    fails.append(f"file cache target: got {[(f.path, f.category) for f in found]}")

# --- 7) file vanishing mid-scan (stat raises) must not kill the scan
V = f"{BASE}/vanish"
make(f"{V}/stays.txt", 100, 400)
make(f"{V}/vanishes.txt", 100, 400)
real_stat = os.stat


def flaky_stat(path, *a, **kw):
    if str(path).endswith("vanishes.txt"):
        raise OSError("gone")
    return real_stat(path, *a, **kw)


os.stat = flaky_stat
try:
    found = core.scan(roots=[V], old_days=180, large_bytes=10**9)
finally:
    os.stat = real_stat
names = {os.path.basename(f.path) for f in found}
if names != {"stays.txt"}:
    fails.append(f"vanish: expected only stays.txt, got {names}")

# --- 8) Steam detection incl. libraryfolders.vdf with Windows-style paths
PF = os.path.join(BASE, "PF")
steam_main = os.path.join(PF, "Steam")
make(os.path.join(steam_main, "steamapps", "shadercache", "sc.bin"), 1111, 10)
lib2_name = "D:\\SteamLibrary"  # literal dir name, Windows-style as in the vdf
lib2 = os.path.join(BASE, lib2_name)
make(os.path.join(lib2, "steamapps", "shadercache", "sc2.bin"), 2222, 10)
make(os.path.join(lib2, "steamapps", "workshop", "content", "1", "mod.bin"), 777, 10)
vdf = (
    '"libraryfolders"\n{\n'
    f'\t"0"\n\t{{\n\t\t"path"\t\t"{steam_main}"\n\t}}\n'
    '\t"1"\n\t{\n\t\t"path"\t\t"D:\\\\SteamLibrary"\n\t}\n}\n'
)
with open(os.path.join(steam_main, "steamapps", "libraryfolders.vdf"), "w") as fh:
    fh.write(vdf)
os.environ["ProgramFiles(x86)"] = PF
old_cwd = os.getcwd()
os.chdir(BASE)  # so the relative Windows-style lib path resolves
try:
    libs = core.find_steam_libraries()
    targets = core.default_cache_targets()
    hogs = core.system_hogs()
finally:
    os.chdir(old_cwd)
if len(libs) != 2:
    fails.append(f"steam: expected 2 libraries, got {libs}")
steam_targets = [t for t in targets if t[0] == "Steam shader cache"]
if len(steam_targets) != 2:
    fails.append(f"steam: expected 2 shader-cache targets, got {steam_targets}")
workshop_hogs = [h for h in hogs if h.name == "Steam Workshop content"]
if not workshop_hogs or workshop_hogs[0].size != 777:
    fails.append(f"steam: workshop hog wrong: {workshop_hogs}")

# --- 9) scale + cancel responsiveness: 3000 files
S = f"{BASE}/scale"
for d in range(30):
    for i in range(100):
        make(f"{S}/dir{d:02d}/f{i:03d}.bin", 64, 400)
t0 = time.time()
found = core.scan(roots=[S], old_days=180, large_bytes=10**9)
elapsed = time.time() - t0
if len(found) != 3000:
    fails.append(f"scale: expected 3000 results, got {len(found)}")
if elapsed > 20:
    fails.append(f"scale: scan too slow ({elapsed:.1f}s)")
ev = threading.Event()
progress_hits = []


def prog(n):
    progress_hits.append(n)
    if len(progress_hits) >= 3:
        ev.set()


found = core.scan(roots=[S], old_days=180, large_bytes=10**9,
                  progress=prog, cancel_event=ev)
if len(found) >= 3000:
    fails.append("scale: cancel during scan did not stop it early")
if not progress_hits:
    fails.append("scale: progress callback never fired")

# --- 10) same root spelled three ways -> one row per file, no self-dup ----
M = f"{BASE}/mixed"
make(f"{M}/plain.txt", 3000, 1, content=b"M" * 3000)
make(f"{M}/big.bin", 2 * 1024 * 1024, 1)
found = core.scan(
    roots=[M, M + "/", os.path.join(M, ".")],
    find_duplicates=True, large_bytes=1024 * 1024, old_days=3650,
)
paths = [f.path for f in found]
if len(paths) != len(set(paths)):
    fails.append(f"mixed spelling: duplicate rows in results: {paths}")
if any(f.category == core.CAT_DUPLICATE for f in found):
    fails.append("mixed spelling: a file was flagged as a duplicate of itself")
if not any(p.endswith("big.bin") and f.category == core.CAT_LARGE
           for p, f in zip(paths, found)):
    fails.append("mixed spelling: big.bin should appear once as Large")
if len(found) != 1:
    fails.append(f"mixed spelling: expected exactly 1 result (big.bin), got {len(found)}")

# --- 11) full system scan: Program Files/Windows walked only on opt-in ---
FS = f"{BASE}/fullsys"
make(f"{FS}/Program Files/BigApp/huge_old.bin", 2 * 1024 * 1024, 400)
make(f"{FS}/Program Files (x86)/OldApp/legacy.bin", 100, 400)
make(f"{FS}/Windows/System32/old_sys.bin", 100, 400)
make(f"{FS}/$Recycle.Bin/deleted.bin", 2 * 1024 * 1024, 400)
make(f"{FS}/System Volume Information/restore.bin", 2 * 1024 * 1024, 400)
default_names = {os.path.basename(f.path) for f in core.scan(
    roots=[FS], large_bytes=1024 * 1024, old_days=180)}
if default_names:
    fails.append(f"fullsys: default scan must skip system dirs, got {default_names}")
full = core.scan(roots=[FS], large_bytes=1024 * 1024, old_days=180,
                 include_system=True)
full_names = {os.path.basename(f.path): f for f in full}
for want in ("huge_old.bin", "legacy.bin", "old_sys.bin"):
    if want not in full_names:
        fails.append(f"fullsys: include_system=True should find {want}")
for never in ("deleted.bin", "restore.bin"):
    if never in full_names:
        fails.append(f"fullsys: {never} must never be scanned, even in full mode")
if full_names.get("huge_old.bin") and full_names["huge_old.bin"].pre_checked:
    fails.append("fullsys: Program Files files must NOT be pre-ticked")

# --- 12) never-delete protection, incl. in full system scan mode ----------
PS = f"{BASE}/protsys"
WIN = f"{PS}/Windows"
PD = f"{PS}/ProgramData"
PF = f"{PS}/Program Files"
ident = b"Z" * (2 * 1024 * 1024)
make(f"{WIN}/System32/core.dll", 0, 400, content=ident)
make(f"{WIN}/WinSxS/comp.dll", 0, 400, content=ident)  # identical twin
make(f"{WIN}/Installer/patch.msp", 2 * 1024 * 1024, 400)
make(f"{WIN}/explorer.exe", 2 * 1024 * 1024, 400)
make(f"{WIN}/Temp/junk.tmp", 100, 400)                       # listable
make(f"{PD}/Package Cache/{{abc}}/setup.exe", 2 * 1024 * 1024, 400)
make(f"{PD}/Microsoft/Defender/data.bin", 2 * 1024 * 1024, 400)
make(f"{PF}/Common Files/shared.dll", 2 * 1024 * 1024, 400)
make(f"{PF}/WindowsApps/app.exe", 2 * 1024 * 1024, 400)
make(f"{PF}/SomeApp/app.exe", 2 * 1024 * 1024, 400)          # listable
make(f"{PS}/pagefile.sys", 2 * 1024 * 1024, 400)
make(f"{PS}/Users/x/NTUSER.DAT", 2 * 1024 * 1024, 400)
make(f"{PS}/Users/x/AppData/Local/Package Cache/setup.exe", 2 * 1024 * 1024, 400)
_env_keys = ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "SystemDrive")
_env_saved = {k: os.environ.get(k) for k in _env_keys}
os.environ.update({
    "SystemRoot": WIN, "ProgramFiles": PF, "ProgramFiles(x86)": PF,
    "ProgramData": PD, "SystemDrive": PS,
})
try:
    full = core.scan(roots=[PS], include_system=True, find_duplicates=True,
                     large_bytes=1024 * 1024, old_days=180)
    full_paths = {f.path for f in full}
    protected_names = {"core.dll", "comp.dll", "patch.msp", "explorer.exe",
                       "setup.exe", "data.bin", "shared.dll", "pagefile.sys",
                       "NTUSER.DAT"}
    leaked = {os.path.basename(p) for p in full_paths} & protected_names
    if leaked:
        fails.append(f"protection: protected files listed in full mode: {leaked}")
    app_listed = [p for p in full_paths if "SomeApp" in p]
    if len(app_listed) != 1:
        fails.append(f"protection: SomeApp leftover should be listed once, got {app_listed}")
    if not any(p.endswith("junk.tmp") for p in full_paths):
        fails.append("protection: Windows\\Temp junk should still be listed in full mode")
    if any("WindowsApps" in p for p in full_paths):
        fails.append("protection: WindowsApps content listed")
    default = core.scan(roots=[PS], large_bytes=1024 * 1024, old_days=180)
    if default:
        fails.append(f"protection: default scan of system tree should be empty, "
                     f"got {[f.path for f in default]}")
finally:
    for k, v in _env_saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

# --- 13) extra_protected: the app's own folder is never listed -------------
own_parent = f"{BASE}/ownapp"
own_file = f"{own_parent}/disk_cleaner_app.py"
make(own_file, 2 * 1024 * 1024, 400)
make(f"{own_parent}/dist/DiskCleaner.exe", 2 * 1024 * 1024, 400)
res = core.scan(roots=[BASE], find_duplicates=False,
                large_bytes=1024 * 1024, old_days=180,
                extra_protected=[own_parent])
if any(r.path == own_file for r in res):
    fails.append("extra_protected: app-folder file was listed")
if any("ownapp" in r.path for r in res):
    fails.append("extra_protected: something under the app folder was listed")
res = core.scan(roots=[BASE], find_duplicates=False,
                large_bytes=1024 * 1024, old_days=180)
if not any(r.path == own_file for r in res):
    fails.append("extra_protected sanity: file should be listed without protection")

# --- 14) recycle_files: batching, per-file failures, cancel ---------------
REC = f"{BASE}/recycle"
os.makedirs(REC, exist_ok=True)


def _rec_files(names):
    out = []
    for n in names:
        p = os.path.join(REC, n)
        with open(p, "w") as fh:
            fh.write("r" * 10)
        out.append(p)
    return out


def _fake_trash_ok(p):
    os.remove(p)


# 14a) per-file path (no Windows batch API on Linux): all moved, one call each
files = _rec_files(["r1.txt", "r2.txt", "r3.txt"])
calls = []
moved, failed, processed = core.recycle_files(
    files, trash_one=lambda p: (calls.append(p), _fake_trash_ok(p)))
if (moved, failed, processed) != (3, [], 3):
    fails.append(f"recycle: all-ok expected (3, [], 3), got {(moved, failed, processed)}")
if len(calls) != 3 or any(os.path.exists(p) for p in files):
    fails.append("recycle: per-file path should trash each file once")

# 14b) a locked file is reported individually, the rest still move
files = _rec_files(["s1.txt", "s2.txt", "s3.txt"])


def _fake_trash_locked(p):
    if p.endswith("s2.txt"):
        raise PermissionError("file is in use")
    os.remove(p)


moved, failed, processed = core.recycle_files(files, trash_one=_fake_trash_locked)
if moved != 2 or processed != 3:
    fails.append(f"recycle: locked-file run expected moved=2 processed=3, got {moved}/{processed}")
if len(failed) != 1 or not failed[0][0].endswith("s2.txt") or "in use" not in failed[0][1]:
    fails.append(f"recycle: locked file should be the one failure with its reason, got {failed}")
if os.path.exists(files[0]) or not os.path.exists(files[1]) or os.path.exists(files[2]):
    fails.append("recycle: locked file must stay, the others must be gone")

# 14c) batch success, verified per file: leftovers are retried one by one
files = _rec_files(["b1.txt", "b2.txt", "b3.txt", "b4.txt"])
real_batch = core._recycle_batch_windows


def _fake_batch(paths):
    for p in paths[:2]:  # shell moved the first two, left the rest
        os.remove(p)
    return True


core._recycle_batch_windows = _fake_batch
try:
    retried = []
    moved, failed, processed = core.recycle_files(
        files, trash_one=lambda p: (retried.append(p), _fake_trash_ok(p)))
finally:
    core._recycle_batch_windows = real_batch
if (moved, failed, processed) != (4, [], 4):
    fails.append(f"recycle: batch+retry expected (4, [], 4), got {(moved, failed, processed)}")
if sorted(retried) != sorted(files[2:]):
    fails.append(f"recycle: leftovers should be retried per file, got {retried}")
if any(os.path.exists(p) for p in files):
    fails.append("recycle: batch leftovers should be gone after retry")

# 14d) batch failure falls back to per-file for the whole batch
files = _rec_files(["f1.txt", "f2.txt"])
core._recycle_batch_windows = lambda paths: False
try:
    calls = []
    moved, failed, processed = core.recycle_files(
        files, trash_one=lambda p: (calls.append(p), _fake_trash_ok(p)))
finally:
    core._recycle_batch_windows = real_batch
if (moved, failed, processed) != (2, [], 2) or len(calls) != 2:
    fails.append(f"recycle: failed batch should fall back per file, got {(moved, failed, processed)} calls={len(calls)}")

# 14e) batch success but a leftover is locked: reported, not silently moved
files = _rec_files(["g1.txt", "g2.txt"])


def _fake_batch_first_only(paths):
    os.remove(paths[0])  # shell moved the first, left the second
    return True


def _fake_trash_locked_g2(p):
    if p.endswith("g2.txt"):
        raise PermissionError("file is in use")
    os.remove(p)


core._recycle_batch_windows = _fake_batch_first_only
try:
    moved, failed, processed = core.recycle_files(files, trash_one=_fake_trash_locked_g2)
finally:
    core._recycle_batch_windows = real_batch
if moved != 1 or len(failed) != 1 or not failed[0][0].endswith("g2.txt"):
    fails.append(f"recycle: locked leftover expected moved=1 failed=[g2], got {(moved, failed, processed)}")
if not os.path.exists(files[1]):
    fails.append("recycle: locked leftover must still exist")

# 14f) cancel stops before the next file; unprocessed files are untouched
files = _rec_files(["c1.txt", "c2.txt", "c3.txt", "c4.txt"])
ev = threading.Event()


def _fake_trash_cancel(p):
    _fake_trash_ok(p)
    if p.endswith("c2.txt"):
        ev.set()


moved, failed, processed = core.recycle_files(
    files, trash_one=_fake_trash_cancel, cancel_event=ev)
if (moved, processed) != (2, 2):
    fails.append(f"recycle: cancel expected moved=2 processed=2, got {(moved, processed)}")
if not os.path.exists(files[2]) or not os.path.exists(files[3]):
    fails.append("recycle: cancelled files must stay untouched")

# 14g) empty input is a no-op
if core.recycle_files([], trash_one=_fake_trash_ok) != (0, [], 0):
    fails.append("recycle: empty input should return (0, [], 0)")

# 14h) batching actually chunks: batch_size=2 over 5 files
files = _rec_files(["h1.txt", "h2.txt", "h3.txt", "h4.txt", "h5.txt"])
seen_batches = []
core._recycle_batch_windows = lambda paths: (seen_batches.append(list(paths)), False)[1]
try:
    moved, failed, processed = core.recycle_files(
        files, trash_one=_fake_trash_ok, batch_size=2)
finally:
    core._recycle_batch_windows = real_batch
if [len(b) for b in seen_batches] != [2, 2, 1]:
    fails.append(f"recycle: batches should be [2, 2, 1], got {[len(b) for b in seen_batches]}")
if (moved, failed, processed) != (5, [], 5):
    fails.append(f"recycle: chunked run expected (5, [], 5), got {(moved, failed, processed)}")

# --- 15) top_folders: biggest subfolders, ranked, with guards ------------
BF = f"{BASE}/bigfold"
make(f"{BF}/games/huge.dat", 5 * 1024 * 1024, 10)
make(f"{BF}/games/small.txt", 100, 10)
make(f"{BF}/games/sub/nested.bin", 1024 * 1024, 10)  # counts toward games
make(f"{BF}/photos/pic1.bin", 2 * 1024 * 1024, 10)
make(f"{BF}/photos/pic2.bin", 1024 * 1024, 10)
make(f"{BF}/docs/note.txt", 500, 10)
make(f"{BF}/loose.bin", 9 * 1024 * 1024, 10)  # directly in root: not attributed
os.makedirs(f"{BF}/truly_empty", exist_ok=True)
make(f"{BF}/node_modules/pkg/lib.bin", 8 * 1024 * 1024, 10)  # skipped dir
make(f"{BF}/Package Cache/setup.exe", 4 * 1024 * 1024, 10)  # protected name
top = core.top_folders([BF])
names = [os.path.basename(t.path) for t in top]
if names != ["games", "photos", "docs"]:
    fails.append(f"top_folders: expected [games, photos, docs], got {names}")
else:
    if top[0].size != 5 * 1024 * 1024 + 100 + 1024 * 1024:
        fails.append(f"top_folders: games size wrong: {top[0].size}")
    if top[0].file_count != 3:
        fails.append(f"top_folders: games should count 3 files, got {top[0].file_count}")
    if top[1].size != 3 * 1024 * 1024 or top[2].size != 500:
        fails.append(f"top_folders: photos/docs sizes wrong: {[t.size for t in top]}")
if any(t.path == BF for t in top):
    fails.append("top_folders: files directly in the root must not form an entry")
if any(n in names for n in ("truly_empty", "node_modules", "Package Cache")):
    fails.append(f"top_folders: empty/skipped/protected folders leaked in: {names}")
if [os.path.basename(t.path) for t in core.top_folders([BF], limit=2)] != ["games", "photos"]:
    fails.append("top_folders: limit=2 should keep only the top two")
if [os.path.basename(t.path) for t in core.top_folders(
        [BF], extra_protected=[f"{BF}/photos"])] != ["games", "docs"]:
    fails.append("top_folders: extra_protected folder should be excluded")
if core.top_folders([]) != []:
    fails.append("top_folders: empty roots should return []")
if core.top_folders([f"{BASE}/does_not_exist"]) != []:
    fails.append("top_folders: nonexistent root should return []")
ev = threading.Event()
ev.set()
if core.top_folders([BF], cancel_event=ev) != []:
    fails.append("top_folders: pre-set cancel should return []")
# Symlinked folder must not be followed or counted.
os.makedirs(f"{BF}/real_target", exist_ok=True)
make(f"{BF}/real_target/big.bin", 7 * 1024 * 1024, 10)
os.symlink(f"{BF}/real_target", f"{BF}/link_dir")
top2 = core.top_folders([BF])
names2 = [os.path.basename(t.path) for t in top2]
if names2[0] != "real_target" or "link_dir" in names2:
    fails.append(f"top_folders: symlink must not be followed/counted: {names2}")

print("RESULT:", "FAIL -> " + "; ".join(fails) if fails else "ALL PASS")
