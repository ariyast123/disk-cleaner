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
2. **HOTFIX — updater stall: build.bat `pause` — DONE (Nov 22, 2026,
   v1.1.1).** Disk Cleaner's
   build.bat still has the unconditional `pause` on both the success
   and the error paths — the exact flaw that stalled GameMode VPN's
   unattended finish_update.bat forever (a build that waits for a
   keypress nobody will ever give). Disk Cleaner's update helper
   also calls plain `call build.bat` (in _write_update_helper) with
   no argument and no build log. Fixed, mirroring GameMode v1.2.2:
   (a) build.bat skips `pause` on both paths when called with the
   argument `auto` (e.g. `if /I not "%~1"=="auto" pause`);
   (b) the helper calls `call build.bat auto > update_build.log 2>&1`;
   (c) also port GameMode v1.2.1's copy-back: after a successful
   build, copy dist\DiskCleaner.exe back over the launched exe's
   path before relaunching, so a pinned or standalone copy can
   never resurrect an old version. Covered by new tests in round 5
   (section 12); full suite green.
3. **What's New window after updating — DONE (Nov 23, 2026, v1.2.4).** When the app finishes updating itself, the
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
   Implemented exactly as designed, with a new test round 7
   (save/load, bad-file rejection, startup show-once, stale-version
   cleanup, update-hook save); full suite green.
4. **Faster cleaning — DONE (Nov 23, 2026, v1.2.5).** The first real
   clean (36,776 files) took ~25 minutes because each file was a
   separate Recycle Bin shell call. Cleaning now batches: on Windows
   `cleaner_core.recycle_files()` sends up to 200 files per
   SHFileOperationW call (FO_DELETE + FOF_ALLOWUNDO), verifies each
   file afterwards, retries leftovers one by one with send2trash,
   and falls back to per-file calls whenever a batch fails — so
   per-file failure reporting and the log are unchanged, and a
   cancelled clean still leaves unprocessed files listed + ticked.
   Covered by new tests in round 4 (section 14). Full suite green.
   (Also fixed round 5's stale helper assertion: the build line
   appends with `>>` because the helper already truncates the log
   with its header line; the test now expects the append form.)
5. **Scan progress with a percentage — DONE (Nov 24, 2026, v1.2.7).**
   The app now does a quick counting pass before scanning
   (`cleaner_core.count_files()`: walks the same roots with the
   same skip-list and protected-area pruning, but never stats a
   file, so it is much faster than the scan itself), then the bar
   fills from 0% to 100% as files are checked instead of showing
   an indeterminate stripe; the live files-checked counter is
   still there, now with the percentage next to it. The count is
   an estimate (unreadable files, single-file caches), so the bar
   is capped at 99% mid-scan and only reaches full when the scan
   actually finishes. Covered by new tests in round 8 (count vs
   scan counter, skip-list in both modes, cache targets, temp
   dedup, protected dirs, cancel, GUI bar behaviour, end-to-end
   scan); full suite green.
6. **Biggest-folders view — DONE (Nov 25, 2026, v1.2.8).** A new
   "Biggest folders" tab next to "Files to clean" and "System space"
   lists the largest folders inside the scanned roots after a scan,
   biggest first, each with its size, file count and a bar scaled to
   the largest folder, plus an Open button per folder. Sizes count
   every file in each folder, not just junk candidates
   (`cleaner_core.top_folders()`: same walk roots, skip-list and
   never-delete pruning as scan(), files counted once even when roots
   overlap; files directly in a root are shown as a row for that
   root). The tab is read-only - nothing can be deleted from it. The
   breakdown runs in a parallel thread during the scan, so the scan
   itself takes no longer. Covered by new test round 9 (core
   aggregation, skip-list in both modes, overlap dedup, protected
   dirs, cancel, GUI render + bars + Open button, end-to-end scan,
   Clear scan); full suite green.
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
