"""Debug round 2: edge cases."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cleaner_core as core

BASE = os.path.join(os.path.dirname(__file__), "fixtures2")
os.system(f"rm -rf {BASE}")
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


R = f"{BASE}/root"
make(f"{R}/exact.bin", 1024 * 1024, 1)                       # exactly at threshold
make(f"{R}/zero1.bin", 0, 1, content=b"")                    # zero-byte dups -> no
make(f"{R}/zero2.bin", 0, 1, content=b"")
make(f"{R}/locked.bin", 2048, 1, content=b"L" * 2048)        # unreadable file
os.chmod(f"{R}/locked.bin", 0)
make(f"{R}/nodir/secret.bin", 2048, 1)                       # unreadable dir
os.chmod(f"{R}/nodir", 0)
make(f"{R}/real_target.bin", 4096, 1, content=b"T" * 4096)   # symlink targets
os.symlink(f"{R}/real_target.bin", f"{R}/link_file.bin")
os.makedirs(f"{R}/realdir", exist_ok=True)
make(f"{R}/realdir/inner.bin", 4096, 1, content=b"I" * 4096)
os.symlink(f"{R}/realdir", f"{R}/link_dir")
make(f"{R}/Windows/evil_big.bin", 5 * 1024 * 1024, 1)        # safety-skipped dir
make(f"{R}/song_cache_copy.mp3", 0, 50, content=b"S" * 8000)  # dup of cache file
make(f"{BASE}/cacheX/song.mp3", 0, 2, content=b"S" * 8000)

found = core.scan(
    roots=[R],
    cache_targets=[("TestCache", f"{BASE}/cacheX", "", True)],
    large_bytes=1024 * 1024,
    old_days=180,
    installer_days=30,
    find_duplicates=True,
)
names = {os.path.basename(f.path): f for f in found}

if "exact.bin" not in names or names["exact.bin"].category != core.CAT_LARGE:
    fails.append("exact-threshold file should be Large")
if "zero1.bin" in names or "zero2.bin" in names:
    fails.append("zero-byte files must not be flagged")
if "link_file.bin" in names:
    fails.append("symlinked file must be skipped")
inner = names.get("inner.bin")
if inner and inner.path.startswith(f"{R}/link_dir"):
    fails.append("symlinked dir must not be walked")
if "evil_big.bin" in names:
    fails.append("files under a 'Windows' subdir must be skipped by generic scan")
dup = names.get("song_cache_copy.mp3")
if not dup or dup.category != core.CAT_DUPLICATE:
    fails.append(f"older personal copy of a cached file should be Duplicate, got {dup and dup.category}")
if "song.mp3" in names and names["song.mp3"].category != "TestCache":
    fails.append("cache copy should keep its cache category")

ev = threading.Event()
ev.set()
t0 = time.time()
found2 = core.scan(roots=[R], find_duplicates=True, cancel_event=ev)
if time.time() - t0 > 5:
    fails.append("cancelled scan took too long")
if found2:
    fails.append(f"pre-cancelled scan should return nothing, got {len(found2)}")

if core.scan(roots=["/nonexistent_dc_path"]) != []:
    fails.append("nonexistent root should give []")
os.makedirs(f"{BASE}/empty", exist_ok=True)
if core.scan(roots=[f"{BASE}/empty"]) != []:
    fails.append("empty dir should give []")

if core.human_size(0) != "0 B":
    fails.append(f"human_size(0) = {core.human_size(0)}")
if core.human_size(-1) != "unknown":
    fails.append("human_size(-1) should be 'unknown'")
if core.human_size(1024) != "1.0 KB":
    fails.append(f"human_size(1024) = {core.human_size(1024)}")
if core.human_size(16 * 1024**3) != "16.0 GB":
    fails.append(f"human_size(16GB) = {core.human_size(16 * 1024**3)}")

os.chmod(f"{R}/locked.bin", 0o644)
os.chmod(f"{R}/nodir", 0o755)
print("RESULT:", "FAIL -> " + "; ".join(fails) if fails else "ALL PASS")
