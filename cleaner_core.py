"""Disk Cleaner - scanning core.

No GUI code lives here so the logic can be tested on its own.
The scanner only *finds* candidate files. It never deletes anything;
deletion is a separate, explicit step in the app, and it goes to the
Recycle Bin, never a permanent delete.

Two kinds of results:
  * FoundFile  - individual files the user can review and send to the
                 Recycle Bin (personal files + known safe caches).
  * HogInfo    - big system space users that must NOT be deleted by
                 hand (Windows.old, hiberfil.sys, WinSxS, restore
                 points...). The app only measures them and points to
                 the safe, official way to reclaim the space.
"""

import glob
import hashlib
import html
import os
import re
import time
from dataclasses import dataclass

# Categories for personal files
CAT_TEMP = "Temp junk"
CAT_INSTALLER = "Old installer"
CAT_DUPLICATE = "Duplicate"
CAT_LARGE = "Large file"
CAT_OLD = "Unused (old)"

INSTALLER_EXTS = {".exe", ".msi", ".iso", ".dmg", ".pkg"}

# Directories the generic scanner never descends into. Deleting from
# these can break Windows or installed programs, so they are off-limits.
# Known *specific* cache folders inside AppData are handled separately
# through default_cache_targets(), never by opening AppData as a whole.
SKIP_DIR_NAMES = {
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
    "appdata",
    ".git",
    "node_modules",
}

# With the opt-in full system scan, the folders above are walked too -
# except these, which are never user files in any mode: the Recycle
# Bin's own store, restore-point data, and dev folders (perf + safety).
FULL_SCAN_SKIP_DIR_NAMES = {
    "$recycle.bin",
    "system volume information",
    ".git",
    "node_modules",
}


@dataclass
class FoundFile:
    path: str
    size: int
    mtime: float
    category: str
    note: str = ""
    pre_checked: bool = False  # safe junk categories start ticked in the UI


@dataclass
class HogInfo:
    name: str
    path: str
    size: int  # -1 means "cannot be measured reliably"
    detail: str
    action_label: str  # text for the action button, "" if no action
    action_kind: str  # settings | cleanmgr | protection | copy | empty_recycle | none
    command: str = ""  # for action_kind == "copy"


def human_size(num_bytes):
    if num_bytes is None or num_bytes < 0:
        return "unknown"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0


# --------------------------------------------------------------------------
# Recycle Bin moves, batched
# --------------------------------------------------------------------------

def _recycle_batch_windows(paths):
    """One SHFileOperationW call (FO_DELETE + FOF_ALLOWUNDO) for many files.

    Returns True only if the shell call itself reported success (no error
    code, not aborted). The caller must still verify per file what
    actually vanished, because a locked file can survive an otherwise
    successful batch. Returns False on non-Windows platforms, for an
    empty list, or when the call fails - the caller then falls back to
    one trash call per file, which keeps per-file failure reporting.
    """
    if os.name != "nt" or not paths:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        buf = "\0".join(paths) + "\0\0"
        file_op = ctypes.create_unicode_buffer(buf)

        class SHFILEOPSTRUCT(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", wintypes.UINT),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", wintypes.LPVOID),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        op = SHFILEOPSTRUCT()
        op.hwnd = None
        op.wFunc = 0x3  # FO_DELETE
        op.pFrom = ctypes.cast(file_op, wintypes.LPCWSTR)
        op.pTo = None
        # FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT:
        # to the Recycle Bin, no prompts, no error popups, no progress UI.
        op.fFlags = 0x40 | 0x10 | 0x400 | 0x4
        op.fAnyOperationsAborted = False
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return result == 0 and not op.fAnyOperationsAborted
    except Exception:
        return False


def _trash_one(path, trash_one):
    """One per-file trash call. Returns None on success, else the error."""
    try:
        trash_one(path)
        return None
    except Exception as exc:  # locked / permission / already gone
        return str(exc)


def recycle_files(paths, trash_one, batch_size=200, cancel_event=None,
                  progress_cb=None):
    """Move paths to the Recycle Bin, fast.

    On Windows the paths are sent in batches of ``batch_size`` through a
    single SHFileOperationW call each, instead of one shell call per
    file (the first real clean of ~37k files took ~25 minutes that way).
    A batch that reports success is verified file by file: anything
    still there is retried with the per-file ``trash_one`` call, so a
    locked file is still reported individually. A batch that fails falls
    back to per-file calls for the whole batch. On other platforms the
    batch API does not exist, so every file goes through ``trash_one``.

    ``trash_one`` is the single-file mover (send2trash in the app).
    ``progress_cb(done, total)`` is called after each resolved file.
    Returns (moved, failed, processed): moved is a count, failed is a
    list of (path, reason) for files that were attempted but not moved,
    processed is how many files were attempted at all - the rest were
    never tried because the run was cancelled.
    """
    paths = list(paths)
    total = len(paths)
    moved = 0
    failed = []
    processed = 0
    i = 0
    while i < total:
        if cancel_event is not None and cancel_event.is_set():
            break
        batch = paths[i:i + batch_size]
        batched = _recycle_batch_windows(batch)
        for p in batch:
            if cancel_event is not None and cancel_event.is_set():
                break
            if batched and not os.path.exists(p):
                moved += 1
            else:
                err = _trash_one(p, trash_one)
                if err is None:
                    moved += 1
                else:
                    failed.append((p, err))
            processed += 1
            if progress_cb is not None:
                progress_cb(processed, total)
        i += batch_size
    return moved, failed, processed


# --------------------------------------------------------------------------
# Generic file walking
# --------------------------------------------------------------------------

def _is_under(path, roots):
    p = os.path.normcase(os.path.abspath(path))
    for r in roots:
        base = os.path.normcase(os.path.abspath(r))
        if p == base or p.startswith(base + os.sep):
            return True
    return False


def _in_downloads(path):
    parts = os.path.normcase(path).lower().split(os.sep)
    return "downloads" in parts


# --------------------------------------------------------------------------
# Never-delete protection. Researched against Microsoft and vendor
# guidance (Nov 2026): deleting inside these locations breaks Windows
# or installed programs - e.g. the Windows Installer cache and the
# Burn "Package Cache" are required to repair, update or uninstall
# the programs they belong to, and WinSxS / DriverStore may only be
# shrunk with DISM / PnPUtil, never by hand. Files in these places are
# never listed as cleanup candidates, in ANY scan mode (even full).
# --------------------------------------------------------------------------

PROTECTED_FILE_NAMES = {
    "pagefile.sys",      # Windows virtual memory - managed by Windows
    "swapfile.sys",      # page file companion for Store apps
    "hiberfil.sys",      # hibernation - remove only via powercfg
    "memory.dmp",        # full crash dump - Disk Cleanup territory
    "bootmgr",           # boot manager
    "bootnxt",
    "dumpstack.log",
    "dumpstack.log.tmp",
}

# Registry hives and their journals, wherever they live in a profile.
PROTECTED_FILE_PREFIXES = ("ntuser.dat", "usrclass.dat")


def _protected_areas():
    """Return (dir_prefixes, system_root) that must never be listed."""
    sr = os.environ.get("SystemRoot", r"C:\Windows")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pd = os.environ.get("ProgramData", r"C:\ProgramData")
    drive = os.environ.get("SystemDrive", "C:")
    dirs = [
        os.path.join(sr, "System32"),       # core OS + registry + drivers
        os.path.join(sr, "SysWOW64"),       # 32-bit core OS
        os.path.join(sr, "WinSxS"),         # component store (DISM only)
        os.path.join(sr, "Installer"),      # MSI cache: repair/uninstall
        os.path.join(sr, "servicing"),      # servicing stack
        os.path.join(sr, "assembly"),       # global assembly cache
        os.path.join(sr, "Fonts"),
        os.path.join(sr, "inf"),            # driver INF store
        os.path.join(pd, "Microsoft"),      # Defender & platform data
        os.path.join(pd, "Package Cache"),  # Burn cache (VS, VC++, .NET)
        os.path.join(pf, "WindowsApps"),    # Store app packages
        os.path.join(pf86, "WindowsApps"),
        os.path.join(pf, "Common Files"),   # shared program components
        os.path.join(pf86, "Common Files"),
        os.path.join(drive + os.sep, "Recovery"),   # Windows Recovery
        os.path.join(drive + os.sep, "Boot"),
        os.path.join(drive + os.sep, "EFI"),
    ]
    prefixes = [os.path.normcase(os.path.abspath(p)) for p in dirs]
    return prefixes, os.path.normcase(os.path.abspath(sr))


def _is_protected(path, prefixes, system_root):
    # Compare in lowercase throughout: os.path.normcase only lowercases
    # on Windows, and this check must be case-insensitive everywhere.
    p = os.path.abspath(path).lower()
    name = os.path.basename(p)
    if name in PROTECTED_FILE_NAMES or name.startswith(PROTECTED_FILE_PREFIXES):
        return True
    # Files directly inside C:\Windows itself (explorer.exe and friends).
    if os.path.dirname(p) == system_root.lower():
        return True
    # The Burn installer cache, per-machine or per-user: any folder
    # literally named "Package Cache" in the path.
    if "package cache" in p.split(os.sep):
        return True
    for pre in prefixes:
        pre = pre.lower()
        if p == pre or p.startswith(pre + os.sep):
            return True
    return False


def _iter_files(roots, cancel_event=None, skip_names=None, protected_dirs=()):
    """Yield (path, size, mtime) for every readable file under roots."""
    skip = SKIP_DIR_NAMES if skip_names is None else skip_names
    protected = frozenset(os.path.abspath(d).lower() for d in protected_dirs)
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if cancel_event is not None and cancel_event.is_set():
                return
            dirnames[:] = [
                d
                for d in dirnames
                if d.lower() not in skip
                and not os.path.islink(os.path.join(dirpath, d))
                and os.path.abspath(os.path.join(dirpath, d)).lower()
                not in protected
            ]
            for name in filenames:
                full = os.path.join(dirpath, name)
                if os.path.islink(full):
                    continue
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                # Canonical spelling, so the same file reached through
                # differently-spelled roots (C:/ vs C:\) is one entry.
                yield os.path.normpath(full), st.st_size, st.st_mtime


def _count_in_tree(root, skip_names, protected, cancel_event=None):
    """Count files under root, pruning exactly like _iter_files.

    No os.stat calls: only directory listings and symlink checks, so
    this is the quick pass the progress bar's total comes from."""
    if not root or not os.path.isdir(root):
        return 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if cancel_event is not None and cancel_event.is_set():
            return total
        dirnames[:] = [
            d
            for d in dirnames
            if d.lower() not in skip_names
            and not os.path.islink(os.path.join(dirpath, d))
            and os.path.abspath(os.path.join(dirpath, d)).lower()
            not in protected
        ]
        for name in filenames:
            if not os.path.islink(os.path.join(dirpath, name)):
                total += 1
    return total


def count_files(roots, temp_dirs=(), cache_targets=(), include_system=False,
                extra_protected=(), cancel_event=None):
    """Quick counting pass: how many files scan() is about to walk.

    Walks the same roots scan() walks (cache-target folders, scan roots
    plus temp dirs) with the same directory skip-list and protected-area
    pruning, but never stats a file, so it runs much faster than the
    scan itself. The number is an estimate for the progress bar, not an
    exact promise: files that turn out unreadable are counted here but
    skipped by the scan, and single-file cache targets are counted here
    but never bump the scan counter - so the bar is capped just below
    100% until the scan finishes and sets it to full.
    """
    skip_names = FULL_SCAN_SKIP_DIR_NAMES if include_system else SKIP_DIR_NAMES
    prot_prefixes, prot_root = _protected_areas()
    if extra_protected:
        prot_prefixes = prot_prefixes + [
            os.path.normcase(os.path.abspath(p)) for p in extra_protected
        ]
    protected = frozenset(os.path.abspath(d).lower() for d in prot_prefixes)

    total = 0
    for _label, path, _note, _pre in cache_targets:
        if cancel_event is not None and cancel_event.is_set():
            return total
        path = os.path.normpath(path)
        if os.path.isfile(path):
            if not _is_protected(path, prot_prefixes, prot_root):
                total += 1
            continue
        total += _count_in_tree(path, skip_names, protected, cancel_event)
    walk_roots = list(roots) + [t for t in temp_dirs if t not in roots]
    for root in walk_roots:
        if cancel_event is not None and cancel_event.is_set():
            return total
        total += _count_in_tree(root, skip_names, protected, cancel_event)
    return total


def _top_bucket(path, root):
    """Immediate child of `root` containing `path`; the root itself
    when the file sits directly in it."""
    rel = os.path.relpath(path, root)
    first = rel.split(os.sep)[0]
    if first in (".", "..") or os.sep not in rel:
        return root
    return os.path.join(root, first)


def top_folders(roots, temp_dirs=(), limit=10, include_system=False,
                extra_protected=(), cancel_event=None):
    """Biggest folders inside the scanned roots.

    Walks the same roots scan() walks (scan roots plus temp dirs) with
    the same directory skip-list and protected-area pruning, and adds
    up every file's size into the bucket of its immediate parent
    folder under the root - so each scan root contributes one row per
    top-level folder, plus one row for files sitting directly in the
    root. Files are counted once even when roots overlap. Returns a
    list of (path, total_bytes, file_count), biggest first, at most
    `limit` entries. This only *measures* - nothing here is ever a
    deletion candidate, and the same never-delete protection applies.
    """
    skip_names = FULL_SCAN_SKIP_DIR_NAMES if include_system else SKIP_DIR_NAMES
    prot_prefixes, prot_root = _protected_areas()
    if extra_protected:
        prot_prefixes = prot_prefixes + [
            os.path.normcase(os.path.abspath(p)) for p in extra_protected
        ]
    walk_roots = list(roots) + [t for t in temp_dirs if t not in roots]
    totals = {}
    seen = set()
    for root in walk_roots:
        if cancel_event is not None and cancel_event.is_set():
            break
        root = os.path.normpath(root)
        for fpath, size, _mtime in _iter_files(
                [root], cancel_event, skip_names, prot_prefixes):
            if _is_protected(fpath, prot_prefixes, prot_root):
                continue
            key = os.path.normcase(fpath)
            if key in seen:
                continue
            seen.add(key)
            bucket = _top_bucket(fpath, root)
            entry = totals.setdefault(bucket, [0, 0])
            entry[0] += size
            entry[1] += 1
    ranked = sorted(
        ((path, size, count) for path, (size, count) in totals.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[:limit] if limit and limit > 0 else ranked


def _raw_folder_size(path):
    """Total size of a folder tree without the safety skip-list.

    Used only for *measuring* system hogs (e.g. Windows.old), never for
    finding files to delete."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, followlinks=False):
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            try:
                total += os.path.getsize(full)
            except OSError:
                continue
    return total


# --------------------------------------------------------------------------
# Duplicates
# --------------------------------------------------------------------------

def _hash_file(path, limit=None):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            read_so_far = 0
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                read_so_far += len(chunk)
                if limit is not None and read_so_far >= limit:
                    break
    except OSError:
        return None
    return h.hexdigest()


def _find_duplicates(files, cancel_event=None):
    """files: list of (path, size, mtime). Returns {path: kept_original}
    for every copy except the newest one in each identical group."""
    # Dedupe by path first: overlapping scan roots can list the same file
    # twice, and a file must never be reported as a copy of itself.
    unique = {}
    for path, size, mtime in files:
        unique.setdefault(os.path.normcase(path), (path, size, mtime))
    by_size = {}
    for path, size, mtime in unique.values():
        if size > 0:
            by_size.setdefault(size, []).append((path, mtime))

    duplicates = {}
    for _size, group in by_size.items():
        if len(group) < 2:
            continue
        if cancel_event is not None and cancel_event.is_set():
            break
        by_partial = {}
        for path, mtime in group:
            ph = _hash_file(path, limit=256 * 1024)
            if ph:
                by_partial.setdefault(ph, []).append((path, mtime))
        for subgroup in by_partial.values():
            if len(subgroup) < 2:
                continue
            by_full = {}
            for path, mtime in subgroup:
                fh = _hash_file(path)
                if fh:
                    by_full.setdefault(fh, []).append((path, mtime))
            for copies in by_full.values():
                if len(copies) < 2:
                    continue
                copies.sort(key=lambda item: item[1], reverse=True)
                keeper = copies[0][0]
                for path, _mtime in copies[1:]:
                    duplicates[path] = keeper
    return duplicates


# --------------------------------------------------------------------------
# Known cache locations (researched, verified paths)
# --------------------------------------------------------------------------

# (label, [path patterns with %ENV% vars and optional * globs], note, pre_checked)
_CACHE_DEFS = [
    (
        "NVIDIA shader cache (DXCache)",
        [r"%LOCALAPPDATA%\NVIDIA\DXCache"],
        "Compiled DirectX shaders. Safe: games rebuild them; first launch "
        "of each game may stutter once. Can grow past 16 GB.",
        True,
    ),
    (
        "NVIDIA shader cache (GLCache)",
        [r"%LOCALAPPDATA%\NVIDIA\GLCache"],
        "Compiled OpenGL/Vulkan shaders (Minecraft, emulators). Safe: rebuilt.",
        True,
    ),
    (
        "DirectX shader cache (Windows)",
        [r"%LOCALAPPDATA%\D3DSCache"],
        "Windows' own shader cache. Safe: rebuilt automatically.",
        True,
    ),
    (
        "NVIDIA driver downloads",
        [r"%PROGRAMDATA%\NVIDIA Corporation\Downloader"],
        "Old driver packages the NVIDIA app downloaded. Safe once the "
        "driver is installed.",
        True,
    ),
    (
        "Driver installer leftovers",
        [r"%SystemDrive%\NVIDIA", r"%SystemDrive%\AMD"],
        "Folders driver installers unpack on the system drive and never clean.",
        True,
    ),
    (
        "Discord cache",
        [
            r"%APPDATA%\discord\Cache",
            r"%APPDATA%\discord\Code Cache",
            r"%APPDATA%\discord\GPUCache",
            r"%APPDATA%\discord\blob_storage",
        ],
        "Images/media Discord cached. Safe: rebuilt. Quit Discord first. "
        "(Local Storage is never touched - it holds your settings.)",
        True,
    ),
    (
        "Spotify streaming cache",
        [
            r"%LOCALAPPDATA%\Spotify\Data",
            r"%LOCALAPPDATA%\Packages\SpotifyAB.SpotifyMusic_*\LocalCache\Spotify\Data",
        ],
        "Streamed songs cached locally; often 2+ GB. Safe: rebuilt as you "
        "listen. Quit Spotify first.",
        True,
    ),
    (
        "Spotify storage (may hold offline downloads)",
        [r"%LOCALAPPDATA%\Spotify\Storage"],
        "WARNING: can include songs downloaded for offline listening - "
        "those would need downloading again.",
        False,
    ),
    (
        "Battle.net cache",
        [r"%LOCALAPPDATA%\Battle.net\Cache", r"%LOCALAPPDATA%\Battle.net\BrowserCaches"],
        "Launcher cache. Safe: rebuilt. Quit Battle.net first.",
        True,
    ),
    (
        "Firefox cache",
        [r"%LOCALAPPDATA%\Mozilla\Firefox\Profiles\*\cache2"],
        "Web cache of your Firefox profiles. Safe: rebuilt. Does not "
        "touch history, bookmarks or logins.",
        True,
    ),
    (
        "Chrome cache",
        [
            r"%LOCALAPPDATA%\Google\Chrome\User Data\*\Cache",
            r"%LOCALAPPDATA%\Google\Chrome\User Data\*\Code Cache",
        ],
        "Web cache of Chrome profiles. Safe: rebuilt.",
        True,
    ),
    (
        "VS Code cache",
        [
            r"%APPDATA%\Code\Cache",
            r"%APPDATA%\Code\CachedData",
            r"%APPDATA%\Code\Code Cache",
            r"%APPDATA%\Code\GPUCache",
        ],
        "Editor caches. Safe: rebuilt; extensions and settings untouched.",
        True,
    ),
    (
        "Crash dumps",
        [r"%LOCALAPPDATA%\CrashDumps"],
        "Memory snapshots from crashed programs - only useful for "
        "debugging a crash. Safe to delete if you are not investigating one.",
        True,
    ),
    (
        "Windows error reports (WER)",
        [
            r"%LOCALAPPDATA%\Microsoft\Windows\WER\ReportArchive",
            r"%LOCALAPPDATA%\Microsoft\Windows\WER\ReportQueue",
            r"%PROGRAMDATA%\Microsoft\Windows\WER\ReportArchive",
            r"%PROGRAMDATA%\Microsoft\Windows\WER\ReportQueue",
        ],
        "Records of crashes that already happened. Safe: Windows does "
        "not need them to run.",
        True,
    ),
    (
        "Blue-screen minidumps",
        [r"%SystemRoot%\Minidump", r"%SystemRoot%\LiveKernelReports"],
        "Small dumps from blue screens / GPU hangs. Keep them only if you "
        "are actively troubleshooting crashes. May need admin rights.",
        False,
    ),
    (
        "Thumbnail & icon cache",
        [
            r"%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db",
            r"%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache_*.db",
        ],
        "Explorer thumbnail/icon databases. Safe: rebuilt automatically. "
        "Files in use by Explorer are skipped.",
        True,
    ),
]


def _resolve_pattern(pattern):
    """Expand %ENV% vars and globs; return existing file/dir paths."""
    expanded = os.path.expandvars(pattern)
    if "*" in expanded:
        return [p for p in glob.glob(expanded) if os.path.exists(p)]
    return [expanded] if os.path.exists(expanded) else []


def find_steam_libraries():
    """Return Steam library roots (folders containing 'steamapps')."""
    roots = []
    bases = []
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if base:
            bases.append(os.path.join(base, "Steam"))
    for base in bases:
        if os.path.isdir(os.path.join(base, "steamapps")):
            roots.append(base)
            vdf = os.path.join(base, "steamapps", "libraryfolders.vdf")
            try:
                with open(vdf, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                for match in re.findall(r'"path"\s+"([^"]+)"', text):
                    lib = match.replace("\\\\", "\\")
                    if os.path.isdir(os.path.join(lib, "steamapps")):
                        roots.append(lib)
            except OSError:
                pass
    # Dedupe, keep order
    seen = set()
    unique = []
    for r in roots:
        key = os.path.normcase(r)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def default_cache_targets():
    """All known cache locations that exist on this machine.

    Returns a list of (label, path, note, pre_checked). Steam libraries
    are detected dynamically and added here too.
    """
    targets = []
    for label, patterns, note, pre_checked in _CACHE_DEFS:
        for pattern in patterns:
            for path in _resolve_pattern(pattern):
                targets.append((label, path, note, pre_checked))

    for lib in find_steam_libraries():
        shadercache = os.path.join(lib, "steamapps", "shadercache")
        if os.path.isdir(shadercache):
            targets.append(
                (
                    "Steam shader cache",
                    shadercache,
                    "Per-game compiled shaders. Safe: rebuilt by Steam/games.",
                    True,
                )
            )
        downloading = os.path.join(lib, "steamapps", "downloading")
        if os.path.isdir(downloading):
            targets.append(
                (
                    "Steam leftover downloads",
                    downloading,
                    "Staging area for downloads/updates. Only clean this if "
                    "Steam shows NO download in progress.",
                    False,
                )
            )
        appcache = os.path.join(lib, "appcache")
        if os.path.isdir(appcache):
            targets.append(
                (
                    "Steam app cache",
                    appcache,
                    "Client artwork/info cache. Safe: Steam downloads it again.",
                    True,
                )
            )
    return targets


# --------------------------------------------------------------------------
# Main scan
# --------------------------------------------------------------------------

def scan(
    roots,
    temp_dirs=(),
    cache_targets=(),
    large_bytes=500 * 1024 * 1024,
    old_days=180,
    installer_days=30,
    find_duplicates=False,
    include_system=False,
    extra_protected=(),
    progress=None,
    cancel_event=None,
):
    """Scan and return a list of FoundFile, biggest first.

    Category priority per file:
    known cache > Temp junk > Old installer > Large file > Unused (old).
    Duplicates are only assigned to files with no other category.
    "Unused" is judged by last *modified* time: Windows usually does not
    maintain last-access times, so modified time is the honest signal.
    """
    now = time.time()
    old_cutoff = now - old_days * 86400
    installer_cutoff = now - installer_days * 86400
    skip_names = FULL_SCAN_SKIP_DIR_NAMES if include_system else SKIP_DIR_NAMES
    prot_prefixes, prot_root = _protected_areas()
    if extra_protected:
        # Extra protected folders (e.g. the app's own folder): merged
        # into the same prefix list, so they are pruned from the walk
        # and rejected by every _is_protected check below.
        prot_prefixes = prot_prefixes + [
            os.path.normcase(os.path.abspath(p)) for p in extra_protected
        ]

    results = {}
    seen_keys = set()  # normcase(path) of everything already in results
    counter = {"n": 0}

    def bump():
        counter["n"] += 1
        if progress is not None and counter["n"] % 200 == 0:
            progress(counter["n"])

    # 1) Known caches: every file inside gets the cache's label.
    for label, path, note, pre_checked in cache_targets:
        if cancel_event is not None and cancel_event.is_set():
            break
        path = os.path.normpath(path)
        if os.path.isfile(path):
            if os.path.normcase(path) in seen_keys:
                continue
            if _is_protected(path, prot_prefixes, prot_root):
                continue
            try:
                st = os.stat(path)
                results[path] = FoundFile(path, st.st_size, st.st_mtime, label, note, pre_checked)
                seen_keys.add(os.path.normcase(path))
            except OSError:
                pass
            continue
        for fpath, size, mtime in _iter_files([path], cancel_event, skip_names, prot_prefixes):
            bump()
            if _is_protected(fpath, prot_prefixes, prot_root):
                continue
            if os.path.normcase(fpath) in seen_keys:
                continue
            seen_keys.add(os.path.normcase(fpath))
            results[fpath] = FoundFile(fpath, size, mtime, label, note, pre_checked)

    # 2) Personal folders. Temp dirs are walked too: on Windows the user
    # Temp folder lives under AppData, which is never a scan root, so
    # without this its junk would never be found at all.
    all_files = []
    walk_roots = list(roots) + [t for t in temp_dirs if t not in roots]
    for path, size, mtime in _iter_files(walk_roots, cancel_event, skip_names, prot_prefixes):
        bump()
        if _is_protected(path, prot_prefixes, prot_root):
            continue
        all_files.append((path, size, mtime))
        if os.path.normcase(path) in seen_keys:
            continue
        category = None
        note = ""
        pre_checked = False
        ext = os.path.splitext(path)[1].lower()
        if temp_dirs and _is_under(path, temp_dirs):
            category = CAT_TEMP
            pre_checked = True
        elif ext in INSTALLER_EXTS and mtime < installer_cutoff and _in_downloads(path):
            category = CAT_INSTALLER
            note = "Installer sitting in Downloads"
            pre_checked = True
        elif size >= large_bytes:
            category = CAT_LARGE
        elif mtime < old_cutoff:
            category = CAT_OLD

        if category:
            age_days = int((now - mtime) / 86400)
            if category in (CAT_LARGE, CAT_INSTALLER) and mtime < old_cutoff:
                note = (note + " " if note else "") + f"Not modified in {age_days} days"
            seen_keys.add(os.path.normcase(path))
            results[path] = FoundFile(path, size, mtime, category, note.strip(), pre_checked)

    # 3) Duplicates among everything scanned (personal + caches).
    if find_duplicates and not (cancel_event is not None and cancel_event.is_set()):
        pool = list({os.path.normcase(p): (p, s, m) for p, s, m in all_files}.values())
        seen_paths = {p for p, _s, _m in pool}
        for f in results.values():
            if f.path not in seen_paths:
                pool.append((f.path, f.size, f.mtime))
        dup_map = _find_duplicates(pool, cancel_event)
        for path, keeper in dup_map.items():
            if os.path.normcase(path) not in seen_keys:
                for p, size, mtime in pool:
                    if p == path:
                        seen_keys.add(os.path.normcase(path))
                        results[path] = FoundFile(
                            path, size, mtime, CAT_DUPLICATE, f"Copy of: {keeper}"
                        )
                        break

    return sorted(results.values(), key=lambda f: f.size, reverse=True)


# --------------------------------------------------------------------------
# System space hogs (report only - never hand-deleted by the app)
# --------------------------------------------------------------------------

def system_hogs(cancel_event=None):
    """Measure the big system space users and name the safe fix for each."""
    hogs = []
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    system_drive = os.environ.get("SystemDrive", "C:")
    drive_root = system_drive + os.sep

    def add_folder_hog(name, path, detail, action_label, action_kind, command=""):
        if os.path.isdir(path):
            hogs.append(
                HogInfo(name, path, _raw_folder_size(path), detail, action_label, action_kind, command)
            )

    def add_file_hog(name, path, detail, action_label, action_kind, command=""):
        if os.path.isfile(path):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = -1
            hogs.append(HogInfo(name, path, size, detail, action_label, action_kind, command))

    add_folder_hog(
        "Windows.old (previous Windows)",
        os.path.join(drive_root, "Windows.old"),
        "Your previous Windows installation, kept after a feature update "
        "for roll-back. Removing it ends the option to go back.",
        "Open Storage settings",
        "settings",
    )
    add_folder_hog(
        "Windows update leftovers ($WINDOWS.~BT)",
        os.path.join(drive_root, "$WINDOWS.~BT"),
        "Staging files from a Windows upgrade.",
        "Open Storage settings",
        "settings",
    )
    add_file_hog(
        "Hibernation file (hiberfil.sys)",
        os.path.join(drive_root, "hiberfil.sys"),
        "Stores RAM for Hibernate; roughly 40% of your RAM. If you only "
        "ever Sleep, turning Hibernate off frees it - but also disables "
        "Fast Startup. Never delete the file by hand.",
        "Copy the command",
        "copy",
        "powercfg /hibernate off",
    )
    add_file_hog(
        "Page file (pagefile.sys)",
        os.path.join(drive_root, "pagefile.sys"),
        "Windows virtual memory. Leave it alone - shown only so the "
        "space is not a mystery.",
        "",
        "none",
    )
    add_file_hog(
        "Full crash dump (MEMORY.DMP)",
        os.path.join(system_root, "MEMORY.DMP"),
        "Kernel memory snapshot from a blue screen. Delete via Disk "
        "Cleanup (admin) if you are not debugging the crash.",
        "Open Disk Cleanup",
        "cleanmgr",
    )
    add_folder_hog(
        "Windows Update download cache",
        os.path.join(system_root, "SoftwareDistribution", "Download"),
        "Downloaded update packages. Clean through Disk Cleanup's "
        "'Windows Update Cleanup', not by hand.",
        "Open Disk Cleanup",
        "cleanmgr",
    )

    winsxs = os.path.join(system_root, "WinSxS")
    if os.path.isdir(winsxs):
        hogs.append(
            HogInfo(
                "Component store (WinSxS)",
                winsxs,
                -1,
                "Old versions of system components. Explorer's size for "
                "this folder is misleading (hard links). NEVER delete "
                "inside it by hand - shrink it with DISM instead "
                "(admin terminal).",
                "Copy the DISM command",
                "copy",
                "DISM /Online /Cleanup-Image /StartComponentCleanup",
            )
        )
        hogs.append(
            HogInfo(
                "System Restore points",
                os.path.join(drive_root, "System Volume Information"),
                -1,
                "Snapshots Windows keeps for roll-back; can quietly grow "
                "to tens of GB. Cap or clear them in System Protection - "
                "keep the most recent one.",
                "Open System Protection",
                "protection",
            )
        )
        hogs.append(
            HogInfo(
                "Delivery Optimization cache",
                "",
                -1,
                "Update pieces Windows stores to share with other PCs. "
                "Clear it in Storage settings > Temporary files > "
                "Delivery Optimization Files.",
                "Open Storage settings",
                "settings",
            )
        )

    # Recycle Bin per drive (approximate without admin rights).
    if os.name == "nt":
        import string

        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            bin_path = os.path.join(root, "$Recycle.Bin")
            if os.path.isdir(bin_path):
                size = _raw_folder_size(bin_path)
                if size > 0:
                    hogs.append(
                        HogInfo(
                            f"Recycle Bin ({letter}:)",
                            bin_path,
                            size,
                            "Files you deleted are still on disk until the "
                            "bin is emptied. Emptying is permanent.",
                            "Empty Recycle Bin",
                            "empty_recycle",
                        )
                    )

    # Steam Workshop: report only - hand-deleting makes Steam re-download.
    for lib in find_steam_libraries():
        workshop = os.path.join(lib, "steamapps", "workshop")
        if os.path.isdir(workshop):
            size = _raw_folder_size(workshop)
            if size > 0:
                hogs.append(
                    HogInfo(
                        "Steam Workshop content",
                        workshop,
                        size,
                        "Mods/maps you subscribed to. Manage them inside "
                        "Steam (unsubscribe) - deleting by hand just makes "
                        "Steam download them again.",
                        "",
                        "none",
                    )
                )
    return hogs

# --------------------------------------------------------------------------
# Scan report export (txt / html): a read-only summary of the last scan
# that the user can keep or share. Exporting never touches the files
# listed in the report - it only writes the report file itself.
# --------------------------------------------------------------------------

def _report_timestamp(generated_at):
    """Fixed string in tests; the current local time in the app."""
    if generated_at:
        return str(generated_at)
    return time.strftime("%Y-%m-%d %H:%M", time.localtime())


def _report_categories(results):
    """[(category, count, size)] sorted by total size, biggest first."""
    by_cat = {}
    for f in results:
        count, size = by_cat.get(f.category, (0, 0))
        by_cat[f.category] = (count + 1, size + f.size)
    return sorted(
        ((cat, count, size) for cat, (count, size) in by_cat.items()),
        key=lambda item: item[2],
        reverse=True,
    )


def _hog_size_text(hog):
    return human_size(hog.size) if hog.size >= 0 else "size varies"


def render_scan_report_txt(results, top_folders=(), hogs=(), roots=(),
                           generated_at=None, app_version=""):
    """Plain-text scan report: summary, files by category, biggest
    folders, system hogs. Paths are written as-is (UTF-8 on write)."""
    stamp = _report_timestamp(generated_at)
    version_text = f" (Disk Cleaner {app_version})" if app_version else ""
    lines = [
        "Disk Cleaner - scan report",
        f"Generated: {stamp}{version_text}",
    ]
    if roots:
        lines.append("Scanned: " + ", ".join(roots))
    total = sum(f.size for f in results)
    lines.append("")
    lines.append(
        f"Summary: {len(results)} candidate file"
        f"{'s' if len(results) != 1 else ''}, {human_size(total)} total"
    )
    for cat, count, size in _report_categories(results):
        lines.append(
            f"  {cat}: {count} file{'s' if count != 1 else ''}, "
            f"{human_size(size)}"
        )
    lines.append("")
    if results:
        lines.append("Files to clean")
        by_cat = {}
        for f in results:
            by_cat.setdefault(f.category, []).append(f)
        for cat, _count, size in _report_categories(results):
            files = sorted(by_cat[cat], key=lambda f: f.size, reverse=True)
            lines.append(
                f"  [{cat}] ({len(files)} file"
                f"{'s' if len(files) != 1 else ''}, {human_size(size)})"
            )
            for f in files:
                modified = time.strftime("%Y-%m-%d", time.localtime(f.mtime))
                note = f"  {f.note}" if f.note else ""
                lines.append(
                    f"    {human_size(f.size):>10}  {f.path}"
                    f"  (modified {modified}){note}"
                )
        lines.append("")
    else:
        lines.append("No candidate files found.")
        lines.append("")
    if top_folders:
        lines.append("Biggest folders")
        for path, size, count in top_folders:
            lines.append(
                f"  {human_size(size):>10}  {path}"
                f"  ({count} file{'s' if count != 1 else ''})"
            )
        lines.append("")
    if hogs:
        lines.append("System space (measured only - the app never deletes these)")
        for hog in hogs:
            where = f" - {hog.path}" if hog.path else ""
            lines.append(f"  {_hog_size_text(hog)}  {hog.name}{where}")
            lines.append(f"    {hog.detail}")
        lines.append("")
    lines.append(
        "Note: this report only lists files. "
        "Nothing was deleted by generating it."
    )
    return "\n".join(lines) + "\n"


def render_scan_report_html(results, top_folders=(), hogs=(), roots=(),
                            generated_at=None, app_version=""):
    """HTML scan report: the same content as the text report, in
    tables. Self-contained (inline CSS, no external resources) and
    UTF-8; every path and note is escaped, so odd filenames cannot
    break the markup."""
    esc = html.escape
    stamp = _report_timestamp(generated_at)
    version_text = (
        f" (Disk Cleaner {esc(app_version)})" if app_version else ""
    )
    total = sum(f.size for f in results)
    parts = [
        "<!DOCTYPE html>",
        "<html lang=\"en\">",
        "<head>",
        "<meta charset=\"utf-8\">",
        "<title>Disk Cleaner - scan report</title>",
        "<style>"
        "body{font-family:'Segoe UI',Arial,sans-serif;max-width:900px;"
        "margin:24px auto;padding:0 16px;color:#222}"
        "h1{font-size:22px}h2{font-size:17px;margin-top:24px}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #ccc;padding:6px 8px;text-align:left;"
        "font-size:14px}th{background:#eee}"
        "td.num{text-align:right;white-space:nowrap}"
        ".muted{color:#666}</style>",
        "</head>",
        "<body>",
        "<h1>Disk Cleaner - scan report</h1>",
        f"<p class=\"muted\">Generated: {esc(stamp)}{version_text}</p>",
    ]
    if roots:
        parts.append(
            "<p class=\"muted\">Scanned: "
            + esc(", ".join(roots)) + "</p>"
        )
    parts.append(
        f"<p><strong>Summary:</strong> {len(results)} candidate file"
        f"{'s' if len(results) != 1 else ''}, {esc(human_size(total))} total</p>"
    )
    if results:
        parts.append("<h2>Files to clean</h2>")
        parts.append(
            "<table><tr><th>Category</th><th>Files</th>"
            "<th>Size</th></tr>"
        )
        for cat, count, size in _report_categories(results):
            parts.append(
                f"<tr><td>{esc(cat)}</td><td class=\"num\">{count}</td>"
                f"<td class=\"num\">{esc(human_size(size))}</td></tr>"
            )
        parts.append("</table>")
        by_cat = {}
        for f in results:
            by_cat.setdefault(f.category, []).append(f)
        for cat, _count, size in _report_categories(results):
            files = sorted(by_cat[cat], key=lambda f: f.size, reverse=True)
            parts.append(f"<h2>{esc(cat)} ({len(files)} files, "
                         f"{esc(human_size(size))})</h2>")
            parts.append(
                "<table><tr><th>Size</th><th>File</th>"
                "<th>Modified</th><th>Note</th></tr>"
            )
            for f in files:
                modified = time.strftime("%Y-%m-%d", time.localtime(f.mtime))
                parts.append(
                    f"<tr><td class=\"num\">{esc(human_size(f.size))}</td>"
                    f"<td>{esc(f.path)}</td><td>{modified}</td>"
                    f"<td>{esc(f.note)}</td></tr>"
                )
            parts.append("</table>")
    else:
        parts.append("<p>No candidate files found.</p>")
    if top_folders:
        parts.append("<h2>Biggest folders</h2>")
        parts.append(
            "<table><tr><th>Size</th><th>Folder</th><th>Files</th></tr>"
        )
        for path, size, count in top_folders:
            parts.append(
                f"<tr><td class=\"num\">{esc(human_size(size))}</td>"
                f"<td>{esc(path)}</td><td class=\"num\">{count}</td></tr>"
            )
        parts.append("</table>")
    if hogs:
        parts.append("<h2>System space (measured only - the app never "
                     "deletes these)</h2>")
        parts.append(
            "<table><tr><th>Size</th><th>Name</th><th>Detail</th></tr>"
        )
        for hog in hogs:
            where = f" - {esc(hog.path)}" if hog.path else ""
            parts.append(
                f"<tr><td class=\"num\">{esc(_hog_size_text(hog))}</td>"
                f"<td>{esc(hog.name)}{where}</td>"
                f"<td>{esc(hog.detail)}</td></tr>"
            )
        parts.append("</table>")
    parts.append(
        "<p class=\"muted\">Note: this report only lists files. "
        "Nothing was deleted by generating it.</p>"
    )
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts) + "\n"


def write_scan_report(results, top_folders, hogs, path, roots=(),
                      app_version=""):
    """Write the report to `path`: .html/.htm gets the HTML report,
    anything else the plain-text one. Returns the path written.
    Raises OSError when the file cannot be written - the caller
    reports that to the user."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".html", ".htm"):
        text = render_scan_report_html(
            results, top_folders, hogs, roots=roots, app_version=app_version
        )
    else:
        text = render_scan_report_txt(
            results, top_folders, hogs, roots=roots, app_version=app_version
        )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path
