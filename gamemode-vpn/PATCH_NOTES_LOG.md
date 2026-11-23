# GameMode VPN — patch notes log

One entry per published update, newest last. The daily chat messages
carry only the version number (Ariya's rule); the full notes live
here, in the app's What's New window, and in the weekly digest.

## 2026-11-22 — v1.1.0

GitHub update channel live: GameMode VPN now checks this repo on
startup, offers one-click updates, and shows a What's New window
after each update. Daily updates alternate between Ariya's two
Muse instances, opposite to Disk Cleaner's turns.

## 2026-11-22 — v1.2.3 (off-cycle hotfix)

Auto mode's first real-machine run (Ariya's log, Nov 22, 2026)
reported "the Disconnect button was not found in Proton" — the
scan ran once, the moment Proton's window existed, before its
controls had necessarily loaded (and in his session the state
went bare meanwhile, making the late failure message misleading
as well). Fixes: the UIA scan now retries until its timeout,
accepts exact-name controls of any type (Buttons preferred) in
case Proton's Avalonia tree types them differently, failure
details list the control names that were seen, and the app
suppresses a stale auto failure when the job is already done
("already bare — no click was needed"). This release is also
the first delivered purely through the rebuilt in-app updater.

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

## 2026-11-22 — v1.2.4 (off-cycle hotfix)

Single-instance guard. Root cause of the stalled v1.2.3 update on
Ariya's PC: five GameModeVPN instances were running at once (some
hidden in the tray from earlier launches — every launch opened a
fresh copy, nothing stopped it), and the updater's helper waits for
every GameModeVPN.exe to exit before rebuilding, so it waited
forever with no visible sign. The app now takes a named Windows
mutex at startup (GameModeVPN-SingleInstance-7C5CFF); a second
launch shows "already running — check the window or tray" and
exits. The guard fails open on any error and on non-Windows
platforms, so it can never be the reason the app does not open.
New test round 15 covers: non-Windows proceeds, first instance
proceeds, ERROR_ALREADY_EXISTS refuses, NULL handle and ctypes
exceptions fail open. 15 rounds all pass, pyflakes clean.
Published off-cycle by the web instance; the baton was left
untouched.

## 2026-11-22 — v1.2.5 (off-cycle hotfix)

Two fixes from Ariya's first full v1.2.4 session. (1) Auto
CONNECT after a game failed with "Proton's window was not found"
(74 s stall in his log) while auto DISCONNECT worked: the UIA
backend used top_window(), which can hand back a hidden shell
window with no buttons. The backend now enumerates the Proton
process's windows, picks the one exposing the most controls
(new pure helper _pick_main_window), restores it when hidden or
minimized, connects with an explicit timeout, and the overall
auto timeout rises 15 s -> 25 s. (2) The v1.2.3 update helper
never fired on its own even after Ariya End-tasked the stacked
instances (a lingering copy kept its wait loop busy; he ran
finish_update.bat manually in the end). The helper now logs
every phase into update_build.log from the first line, caps the
wait at ~60 s, then force-closes leftover GameModeVPN.exe copies
(taskkill /F) and builds anyway; build output appends to the
same log. New test round 16 covers _pick_main_window, the
backend's pick-and-restore with a fake pywinauto Application,
and the helper's new lines. 16 rounds all pass, pyflakes clean.
Published off-cycle by the web instance; baton untouched.

## 2026-11-22 — v1.2.6 (off-cycle, at Ariya's direct request)

Stealth session flow. Ariya: two windows popping up at game
start (GameMode + Proton) is annoying, and he dared not close
Proton's window because auto control used to break without it.
Now: after a successful auto click, the driver waits half a
second and closes the Proton window it used (backend
close_window: window.close(), minimize as fallback). Only the
window closes — Proton keeps running and its service holds the
tunnel state. On failure paths the window stays open for the
guided steps. A close failure never fails a worked click, and
backends without close_window still work. GameMode's own side
needed no change: the only deiconify in the app is the tray
menu's Open action, so the session flow never raises its window.
New test round 17 covers all of it. 17 rounds all pass, pyflakes
clean. Note: the 1.2.4 -> 1.2.5 update again needed a manual
finish_update run on his PC — that update was still executed by
1.2.4's old uncapped, unlogged helper; the hardened helper ships
in 1.2.5 and governs from this update on. Baton untouched.

## 2026-11-22 — v1.2.7 (off-cycle, at Ariya's direct request)

Boot behavior, Ariya's closing ask for the app. The Start-with-
Windows entry now carries a --minimized flag (_startup_command),
so a boot launch goes straight to the tray (_start_in_tray) and
never presents the window; manual launches and the updater's
relaunch carry no flag and open normally. Because his existing
registry entry predates the flag, the app refreshes the entry on
every launch when the setting is on (Windows only), so it
self-heals with no action from him. While hidden in the tray, an
available update now fires a tray notification (_notify_tray,
also factored into the close-to-tray notice) instead of only the
invisible banner — he opens the app himself to install. What's
New no longer pops at a boot launch; the saved notes wait for
the next visible open. Also fixed the stale update-confirm
dialog text (it still described the pre-1.2.2 close-by-hand
flow). New test round 18 (fake pystray): startup command,
flag parsing, hide-to-tray, notify-while-hidden, What's New
guard, visible-launch behavior. 18 rounds all pass, pyflakes
clean. Baton untouched.
