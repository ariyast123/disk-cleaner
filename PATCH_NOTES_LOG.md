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
