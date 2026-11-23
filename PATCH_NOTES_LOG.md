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
