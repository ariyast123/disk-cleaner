# Disk Cleaner — improvement roadmap

Ariya asked (Nov 21, 2026) for daily updates: new features, UI polish,
one focused improvement per day, always fully tested before delivery.
Safety rules are non-negotiable in every change: never-delete
protection stays, deletion only via Recycle Bin after tick +
confirmation, no admin requirement, UI text in English.

## Queue (work top-down)

1. **Update system — DONE (Nov 21, 2026).** Updater built into the
   app (v1.1.0), repo `ariyast123/disk-cleaner` live, token connected
   as custom.github, test publish verified, and the daily cron now
   publishes each update to the repo. The publishing how-to lives in
   ~/workspace/custom-connectors/custom.github/CONNECTOR.md.
2. **HOTFIX — updater stall: build.bat `pause` (found Nov 22, 2026
   via GameMode VPN; do this before item 3).** Disk Cleaner's
   build.bat still has the unconditional `pause` on both the success
   and the error paths — the exact flaw that stalled GameMode VPN's
   unattended finish_update.bat forever (a build that waits for a
   keypress nobody will ever give). Disk Cleaner's update helper
   also calls plain `call build.bat` (in _write_update_helper) with
   no argument and no build log. Fix, mirroring GameMode v1.2.2:
   (a) build.bat skips `pause` on both paths when called with the
   argument `auto` (e.g. `if /I not "%~1"=="auto" pause`);
   (b) the helper calls `call build.bat auto > update_build.log 2>&1`;
   (c) also port GameMode v1.2.1's copy-back: after a successful
   build, copy dist\DiskCleaner.exe back over the launched exe's
   path before relaunching, so a pinned or standalone copy can
   never resurrect an old version. Cover the helper lines with
   tests like GameMode's round 14 and run the full suite as usual.
3. **What's New window after updating (Ariya's ask, Nov 21, 2026).** When the app finishes updating itself, the
   next launch shows a small closable window with the new version's
   patch notes. Design: version.json gains a `patch_notes` field (a
   few short lines) next to the short banner `notes`. When he clicks
   Update now, the app saves the target version + its patch notes to
   ~/DiskCleaner/whats_new.json before applying; on startup, if that
   file exists and its version equals the running VERSION, show the
   notes in a small dialog with a Close button, then delete the file
   so it appears exactly once. The daily cron writes patch_notes into
   version.json on every publish and appends the same notes to
   PATCH_NOTES_LOG.md for the weekly digest. Daily chat messages
   carry no changelog (his rule) — only the new version number.
4. **Faster cleaning** — the first real clean (36,776 files) took
   ~25 minutes because each file is a separate Recycle Bin shell call.
   Batch the recycle operations (one shell operation for many files)
   while keeping per-file failure reporting and the log.
5. **Scan progress with a percentage** — quick counting pass or
   running estimate so the bar shows % instead of an indeterminate
   stripe; keep the live files-checked counter.
6. **Biggest-folders view** — a simple visual breakdown (top folders
   by size) on the System tab or its own tab, so he sees where space
   goes before scanning.
7. **Remember settings + window size** between runs (small JSON in
   ~/DiskCleaner), including scan locations and thresholds.
8. **Export a scan report** (txt/html) he can keep or share.
9. **Scheduled quick scan** — optional weekly reminder inside the app
   when caches pass a size threshold (e.g. NVIDIA DXCache > 5 GB).

## Done

- v1 (Nov 21, 2026): scanner (caches/temp/installers/large/old/
  duplicates), system hogs tab, Recycle Bin cleaning with log.
- Same day: full system scan (opt-in), never-delete protection
  researched + hard-coded, per-folder remove, Clear scan, double-click
  open / right-click menu, cleaning progress counter + cancellable
  cleaning, app-folder self-protection.
- First real clean freed ~140 GB on Ariya's PC (153 → 293 GB free).
- GitHub update pipeline (Nov 21, 2026): public repo
  ariyast123/disk-cleaner, fine-grained token (Contents read/write,
  that repo only, no expiration) stored as connector custom.github,
  README + version.json test publishes verified end to end, daily
  cron rewired to publish each day's update to the repo.
