# Disk Cleaner — patch notes log

One entry per published update. The daily update job appends here;
the weekly digest job reads the last 7 days and posts them in chat
(Ariya's rule, Nov 21, 2026: no patch notes in daily chat messages).

## 2026-11-21 — v1.1.0

- GitHub update channel live: the app checks the repo on startup and
  offers one-click updates with a banner.

## 2026-11-22 — v1.1.1

- Fixed the updater stall: build.bat no longer waits for a keypress
  when run by the update helper (auto mode), so an unattended update
  finishes instead of hanging forever.
- The update helper now logs the build to update_build.log, so a
  failed build leaves evidence.
- After a successful build, the fresh exe is copied back over the copy
  that was actually launched, so a pinned or standalone copy can never
  resurrect the old version.

## 2026-11-22 — v1.2.0

- One-click updates, at Ariya's request: the "close the app
  yourself" dialog is gone. Clicking Update closes the app
  itself (with a guaranteed-exit backstop), and the helper's
  first move is now taskkill — every running copy is closed at
  once — followed by a short gone-check, the build (logged to
  update_build.log), the copy-back over the launched exe, and
  the relaunch. No manual steps, no infinite wait loop.
- New test round 6 covers the kill-first helper and the
  self-closing update path. All 6 rounds pass.

## 2026-11-22 — v1.2.1 (test update)

- Test update at Ariya's request, to exercise the update
  flow. No changes to the app itself.

## 2026-11-22 — v1.2.2

- Automatic-update fix, found by Ariya's live test: the app
  closed on Update but the helper (launched with no console,
  DETACHED_PROCESS) died silently after its first log line on
  his PC; the same finish_update.bat run by hand worked. The
  helper now launches with its own console window
  (CREATE_NEW_CONSOLE), identical to a manual double-click.
  Landing on this version takes one manual finish_update run;
  after that, updates are fully automatic.

## 2026-11-22 — v1.2.3 (test update)

- Test update at Ariya's request, to exercise the fixed
  automatic update flow. No changes to the app itself.

## 2026-11-23 — v1.2.4

- After an update, the app now shows a small "What's new" window
  on the next launch with the new version's patch notes.
- The window appears exactly once and has a Close button; a note
  saved for a different version is cleaned up without showing.

## 2026-11-23 — v1.2.5

- Cleaning is much faster: files now go to the Recycle Bin in
  batches (one shell operation for many files) instead of one
  call per file, so a large clean finishes much faster.
- A locked or in-use file is still reported individually, and
  the per-file cleanup log is unchanged.
- A cancelled clean still leaves the unprocessed files listed
  and ticked, so it can be resumed.

## 2026-11-24 — v1.2.6

- The automatic update hand-off was rebuilt: the app now hands
  finish_update.bat to Explorer instead of starting it itself.
  A helper launched by the app died together with the app it had
  just closed (console opened, closed, nothing rebuilt), while a
  manual double-click always worked. Explorer-launched, the
  helper is fully independent of the app.
- The helper now logs a 'relaunch issued' line at the end, so any
  future failure leaves clear evidence in update_build.log.

## 2026-11-24 — v1.2.7

- The scan progress bar now shows a real percentage. Before
  scanning, the app does a quick counting pass over the folders
  it is about to scan, then the bar fills from 0% to 100% as
  files are checked.
- The live "files checked" counter is still there, now with the
  percentage next to it.
- The bar stops just below 100% while the duplicate check runs
  and reaches full when the scan actually finishes.

## 2026-11-25 — v1.2.8

- There is a new "Biggest folders" tab next to "Files to clean" and
  "System space". After a scan it lists the largest folders inside
  the folders you scanned, biggest first, each with its size, file
  count and a bar showing how it compares to the largest one.
- Sizes count every file in each folder, not just the junk the scan
  found, so you can see where your space really goes before cleaning.
- The tab is read-only and has an Open button per folder; nothing is
  deleted from it. The breakdown runs in parallel with the scan, so
  the scan itself takes no longer.

## 2026-11-25 — v1.2.9

- Your window size, scan folders, thresholds and toggles are now
  remembered between runs, saved in ~/DiskCleaner/settings.json and
  restored on the next launch. Settings are saved when a scan starts
  and when the app closes, so a crash or a self-update does not lose
  them. A missing or damaged settings file falls back to the defaults
  instead of crashing or opening a weird window.
- Fixed: the Biggest folders tab's Open button opened the folder's
  parent instead of the folder itself; it now opens the folder.
- Repaired the test suite: the tests shipped with v1.2.8 still
  expected the older button-driven biggest-folders design and failed
  against the published app. They now test the scan-integrated design
  v1.2.8 actually shipped, and cover the Open-button fix and the new
  settings persistence. Full suite green.
