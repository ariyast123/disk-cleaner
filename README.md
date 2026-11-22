# Disk Cleaner

A careful Windows disk-cleanup tool. It scans first, shows you everything,
and deletes nothing until you tick it and confirm. Deletion always goes to
the **Recycle Bin** — never permanent — and every action is logged to
`~/DiskCleaner/cleanup_log.txt`.

## Run it

Option A — just run the app (needs Python):

```
pip install customtkinter send2trash
python disk_cleaner_app.py
```

Option B — build a standalone exe once:

```
build.bat
```

That creates `dist\DiskCleaner.exe`, which needs no Python afterwards.

## Interface

Dark, single-window layout: a sidebar with a live drive-usage card,
scan locations and junk rules (the settings area scrolls; the Scan
button always stays visible), and a results table grouped by category
with zebra rows. A filter box narrows results by name/path, and
Safe junk / All / None buttons manage ticks — your selection is kept
even while filtering. Double-click a file to open it with its default
app; right-click a file for "Show in Explorer" (opens Explorer with
that exact file highlighted) or "Open containing folder". Folders you
add under "Also scanning" each get a ✕ button to remove them, and
"Clear scan" throws away the current results so you can rescan with
different settings. The System space tab shows each hog as a card
with its size and its safe fix.

## What it finds

**Files you can clean (tick & send to Recycle Bin):**

- **Known app & game caches** — each scanned individually, never AppData
  as a whole: NVIDIA DXCache/GLCache shader caches (can silently grow
  past 16 GB), Windows D3DSCache, NVIDIA driver downloads and installer
  leftovers (C:\NVIDIA, C:\AMD), Discord cache, Spotify streaming cache,
  Battle.net cache, Firefox/Chrome cache, VS Code cache, Steam shader
  cache / app cache / leftover downloads, crash dumps, Windows error
  reports (WER), blue-screen minidumps, thumbnail & icon caches.
  Things that hold your data — e.g. Discord's *Local Storage* — are never
  touched. Spotify's *Storage* folder is listed but unticked by default
  because it can hold offline downloads.
- **Temp junk** in your user Temp folder.
- **Old installers** (.exe/.msi/.iso) sitting in Downloads.
- **Large files** and **unused files** (by last-modified date — Windows
  does not reliably track last-access time, so modified date is the
  honest signal) in the folders you choose.
- **Duplicate files** (optional, slower): matched by size, then by
  SHA-256 hash. The newest copy is always the one kept.

**System space — measured and explained, never hand-deleted:**

Windows.old, $WINDOWS.~BT, hiberfil.sys, pagefile.sys, MEMORY.DMP,
Windows Update download cache, WinSxS component store, System Restore
points, Delivery Optimization cache, Recycle Bin per drive, Steam
Workshop content. Each entry names the safe official way to reclaim its
space (Storage settings, Disk Cleanup, DISM command, System Protection)
with a button that opens the tool or copies the command.

## Safety rules built in

- The generic scanner never enters `Windows`, `Program Files`,
  `ProgramData`, `AppData`, or the Recycle Bin. An opt-in "Full system
  scan" checkbox (off by default, with a warning confirmation) also
  walks those folders — meant for finding leftovers of programs you
  already uninstalled. The Recycle Bin store and System Volume
  Information are never walked in any mode.
- Never-delete protection, in every mode (researched against
  Microsoft/vendor guidance): files are never listed from
  `Windows\System32`, `SysWOW64`, `WinSxS`, `Windows\Installer`,
  `servicing`, `assembly`, `Fonts`, `inf`, `ProgramData\Microsoft`,
  any `Package Cache` folder, `WindowsApps`, `Common Files`,
  `Recovery`/`Boot`/`EFI`, or directly inside `C:\Windows`; and files
  named `pagefile.sys`, `swapfile.sys`, `hiberfil.sys`, `MEMORY.DMP`,
  `bootmgr`, `NTUSER.DAT*` or `UsrClass.dat*` are never listed.
  Deleting the Installer or Package Cache content would break
  repair/update/uninstall of installed programs, and WinSxS /
  DriverStore may only be shrunk with DISM / PnPUtil — so the app
  keeps its hands off entirely.
- The app's own folder is never scanned either: if `DiskCleaner.exe`
  sits in a `dist` subfolder, the project folder above it (with the
  .py sources and build.bat) is protected too — the cleaner never
  lists its own files, not even as duplicates.
- Safe junk categories start ticked; personal files (large/old/
  duplicates) start unticked — you opt in.
- Locked or permission-protected files are skipped and reported, never
  forced.
- Closing an app before cleaning its cache avoids most "file in use"
  skips (Discord, Spotify, Battle.net, browsers).
