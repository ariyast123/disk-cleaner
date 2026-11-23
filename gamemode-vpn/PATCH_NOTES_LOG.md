# GameMode VPN — patch notes log

One entry per published update, newest last. The daily chat messages
carry only the version number (Ariya's rule); the full notes live
here, in the app's What's New window, and in the weekly digest.

## 2026-11-22 — v1.1.0

GitHub update channel live: GameMode VPN now checks this repo on
startup, offers one-click updates, and shows a What's New window
after each update. Daily updates alternate between Ariya's two
Muse instances, opposite to Disk Cleaner's turns.

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
