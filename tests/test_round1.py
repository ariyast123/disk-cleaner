"""Debug round 1: core scan fixtures."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cleaner_core as core

BASE = os.path.join(os.path.dirname(__file__), "fixtures")
os.system(f"rm -rf {BASE}")
NOW = time.time()
DAY = 86400


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
make(f"{P}/Downloads/setup_old.exe", 10_000, 90)          # old installer
make(f"{P}/Downloads/setup_new.exe", 10_000, 5)           # recent installer -> no
make(f"{P}/Downloads/movie.mp4", 3 * 1024 * 1024, 10)     # large
make(f"{P}/Documents/ancient.txt", 100, 400)               # old
make(f"{P}/Videos/clip.mkv", 100, 2)                      # nothing -> no
make(f"{P}/Documents/dup_a.bin", 0, 3, content=b"A" * 5000)   # duplicate (older)
make(f"{P}/Documents/dup_b.bin", 0, 1, content=b"A" * 5000)   # duplicate keeper (newer)
make(f"{P}/Documents/samesize.bin", 0, 2, content=b"B" * 5000)  # same size, diff content -> no
make(f"{BASE}/Temp/junk.tmp", 50_000, 1)
make(f"{BASE}/Local/NVIDIA/DXCache/shader1.bin", 2 * 1024 * 1024, 30)
make(f"{BASE}/Local/NVIDIA/DXCache/shader2.bin", 1024, 30)
make(f"{BASE}/Roaming/discord/Cache/img.png", 700_000, 30)
os.environ["SystemRoot"] = f"{BASE}/Windows"
os.environ["SystemDrive"] = BASE
make(f"{BASE}/Windows.old/oldwin.dll", 5 * 1024 * 1024, 60)
make(f"{BASE}/hiberfil.sys", 4 * 1024 * 1024, 60)
make(f"{BASE}/pagefile.sys", 6 * 1024 * 1024, 60)
make(f"{BASE}/Windows/MEMORY.DMP", 1024 * 1024, 60)
make(f"{BASE}/Windows/SoftwareDistribution/Download/upd.cab", 2 * 1024 * 1024, 60)
os.makedirs(f"{BASE}/Windows/WinSxS", exist_ok=True)

cache_targets = [
    ("NVIDIA shader cache (DXCache)", f"{BASE}/Local/NVIDIA/DXCache", "note", True),
    ("Discord cache", f"{BASE}/Roaming/discord/Cache", "note", True),
]

found = core.scan(
    roots=[P],
    temp_dirs=[f"{BASE}/Temp"],
    cache_targets=cache_targets,
    large_bytes=1024 * 1024,
    old_days=180,
    installer_days=30,
    find_duplicates=True,
)
by_name = {os.path.basename(f.path): f for f in found}

checks = [
    ("setup_old.exe", core.CAT_INSTALLER),
    ("movie.mp4", core.CAT_LARGE),
    ("ancient.txt", core.CAT_OLD),
    ("junk.tmp", core.CAT_TEMP),
    ("shader1.bin", "NVIDIA shader cache (DXCache)"),
    ("shader2.bin", "NVIDIA shader cache (DXCache)"),
    ("img.png", "Discord cache"),
    ("dup_a.bin", core.CAT_DUPLICATE),
]
fails = []
for name, cat in checks:
    f = by_name.get(name)
    if f is None:
        fails.append(f"MISSING {name}")
    elif f.category != cat:
        fails.append(f"WRONGCAT {name}: {f.category} != {cat}")
for absent in ("setup_new.exe", "clip.mkv", "samesize.bin", "dup_b.bin"):
    if absent in by_name:
        fails.append(f"SHOULD-BE-ABSENT {absent} ({by_name[absent].category})")
dup = by_name.get("dup_a.bin")
if dup and "dup_b.bin" not in dup.note:
    fails.append(f"DUP NOTE wrong: {dup.note}")
inst = by_name.get("setup_old.exe")
if inst and not inst.pre_checked:
    fails.append("installer should be pre_checked")
large = by_name.get("movie.mp4")
if large and large.pre_checked:
    fails.append("large file should NOT be pre_checked")

hogs = core.system_hogs()
hog_names = {h.name: h for h in hogs}
for want in (
    "Windows.old (previous Windows)",
    "Hibernation file (hiberfil.sys)",
    "Page file (pagefile.sys)",
    "Full crash dump (MEMORY.DMP)",
    "Windows Update download cache",
    "Component store (WinSxS)",
):
    if want not in hog_names:
        fails.append(f"HOG MISSING {want}")
wo = hog_names.get("Windows.old (previous Windows)")
if wo and wo.size != 5 * 1024 * 1024:
    fails.append(f"Windows.old size wrong: {wo.size}")
ws = hog_names.get("Component store (WinSxS)")
if ws and ws.size != -1:
    fails.append("WinSxS size should be -1 (unmeasured)")

print("RESULT:", "FAIL -> " + "; ".join(fails) if fails else "ALL PASS")
