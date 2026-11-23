# GameMode VPN — patch notes log

One entry per published update, newest last. The daily chat messages
carry only the version number (Ariya's rule); the full notes live
here, in the app's What's New window, and in the weekly digest.

## 2026-11-22 — v1.1.0

GitHub update channel live: GameMode VPN now checks this repo on
startup, offers one-click updates, and shows a What's New window
after each update. Daily updates alternate between Ariya's two
Muse instances, opposite to Disk Cleaner's turns.

## 2026-11-22 — v1.2.2 (off-cycle, at Ariya's direct request)

One consolidated manual-install release for every update problem
he reported that evening, per his instruction: this one he
installs by hand (files in chat), future ones must flow through
the in-app updater.

- **App did not reopen after updating.** Root cause: build.bat
  ended with an interactive `pause` (both success and failure
  paths), and the unattended finish_update.bat calls it — the
  helper stalled forever on a keypress nobody could give. The
  updater now calls `build.bat auto` (pause skipped in auto
  mode), redirects the build to update_build.log, relaunches the
  previous version if the build fails, and the app restarts
  itself to finish instead of asking for a manual close. A
  pending update also bypasses minimize-to-tray, which would
  otherwise keep the process alive and stall the helper's wait.
- **Stale-copy loop** (from v1.2.1): the freshly built exe is
  copied back over the launched exe's path.
- **New app icon** (gamemode_icon.ico, embedded by build.bat and
  used for the window and tray): violet ring + cyan core on a
  dark tile, so current builds are visually distinct from old
  copies with the generic icon. The icon joins UPDATE_FILES so
  future updates carry it.

## 2026-11-22 — v1.2.1 (off-cycle hotfix)

Updater fix, reported by Ariya the same evening: after updating,
reopening the app from his taskbar pin brought back the old
version, which offered the same update again. Cause: the updater
rebuilt and relaunched only the dist copy, while the pin pointed
at a standalone copy elsewhere that stayed old. finish_update.bat
now copies the freshly built exe back over the launched exe's
path before relaunching it, so any shortcut that started the app
gets the new version too. (One-time note: a pin still pointing at
a pre-1.2.1 copy has to be aimed at the dist exe once; from then
on updates self-replace in place.)

## 2026-11-22 — v1.2.0 (off-cycle, at Ariya's direct request)

Auto mode: GameMode now clicks Proton's own Disconnect and Connect
buttons (Windows UI Automation) and verifies the result live; the
guided steps remain as an automatic fallback. Minimize to tray:
closing the window hides the app in the system tray, still
watching; double-click reopens, right-click quits. Proton
auto-detect fixed for the real install layout
(ProtonVPN.Client.exe in the versioned folder, newest version
wins) and the Browse filter unlocked. The app also learns whether
the kill switch is in play and shortens the guided steps when it
is not. Published off-cycle by the web instance; the daily baton
was intentionally left untouched, so the scheduled alternation
continues as planned.
