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

print("RESULT:", "FAIL -> " + "; ".join(fails) if fails else "ALL PASS")
