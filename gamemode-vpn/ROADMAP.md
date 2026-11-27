# GameMode VPN — improvement roadmap

The daily update takes the top unfinished item. Skip items blocked
on a decision Ariya has not made. Detection robustness always
outranks new features: a wrong "protected" or "bare" claim is the
worst bug this app can ship.

1. **Windows detection hardening — DONE in v1.2.0.** Verified on
   Ariya's PC (Nov 22, 2026): Proton VPN 5.1.10's main exe is
   ProtonVPN.Client.exe in the versioned folder
   `C:\Program Files\Proton\VPN\v5.1.10\`; `find_proton_exe` now
   globs the versioned folders (newest version wins, Client name
   first), the Browse filter is unlocked, and tunnel detection was
   verified live on his machine. A registry uninstall-key lookup
   remains an optional extra fallback if a future install layout
   breaks the folder scan.
2. **Session history — DONE in v1.3.0.** Each finished game session
   is recorded (games played, start time, length, Game Mode time,
   whether a restore was needed, best state reached) to
   `~/GameModeVPN/history.json` (capped at 50 entries, oldest drop
   first; a corrupt file degrades to an empty list) and the last 8
   sessions show in a SESSION HISTORY card in the UI. Covered by
   test rounds 21 (engine records + storage) and 22 (GUI).
3. **Minimize to tray — DONE in v1.2.0** (pystray; close hides to
   the tray, double-click reopens, Quit in the tray menu).
4. **Exe icon + branding — DONE in v1.3.6.** `gamemode_icon.ico`
   (violet rounded square + cyan bolt, 16–256px) now ships in the
   repo and is downloaded by the updater; the app uses it for the
   window and tray icons and build.bat embeds it with
   `--icon`. `gamemode_core.write_app_icon()` draws it
   deterministically with Pillow, and build.bat regenerates it if
   it is ever missing. Covered by test round 10.
5. **Ping proof — DONE in v1.4.0.** After Game Mode turns on, the
   app measures the real ping to a configurable host (default
   8.8.8.8) and shows it in a new Ping row in the sidebar, in the
   status line, and in the session history. Off by default (privacy:
   it contacts the chosen host); the host setting only accepts a
   hostname or an IP address, and a host that does not answer shows
   "no answer", never a guess. Covered by test rounds 24 (core) and
   24 GUI.
6. **UIA auto-click — DONE in v1.2.0 as Auto mode.** At Ariya's
   direct request (Nov 22, 2026) it shipped default ON with the
   strict conditions kept: exact-name button matching (Connect can
   never hit Disconnect), live state verification after every
   click, and automatic fallback to the guided steps on any
   failure. Watch for Proton UI renames in future updates; if the
   buttons move, the fallback covers it and the names in
   `AUTO_BUTTONS` (gamemode_core.py) are the fix.
7. **Registry uninstall-key fallback — DONE in v1.4.2.**
   `find_proton_exe` now falls back to the Add/Remove Programs
   registry keys (InstallLocation, DisplayIcon, UninstallString)
   when the folder scan and the flat paths find nothing, so a
   future Proton layout change cannot lose the exe. Only entries
   whose DisplayName names Proton VPN count, and a path is
   returned only when the exe file really exists — a missing or
   broken registry just means "not found", never a guess. Covered
   by test round 25 (fake winreg: versioned InstallLocation,
   flat folder, DisplayIcon/UninstallString derivation,
   non-Proton entries ignored, broken registry degrades to None).
8. **Gateway ping retry — DONE in v1.4.3.** `ping_host` retries
   once before calling the gateway unreachable, so a single
   dropped ICMP echo no longer flips the app to "blocked" for a
   poll tick (false kill-switch warning + spurious blocked_midway
   event). A gateway that answers first try is still pinged
   exactly once; a ping that cannot run stays "unknown" and is
   not retried. Covered by test round 26.
9. **Lowest-metric gateway — DONE in v1.4.4.** `default_gateway`
   now picks the lowest-metric gateway from the Active Routes
   section of `route print` instead of the first 0.0.0.0 row, so
   on a machine with several default routes (Ethernet + Wi-Fi,
   or a VPN's own default route) the bare-vs-blocked verdict is
   decided against the gateway actually carrying traffic.
   Persistent routes never count, ties keep the first row, a
   row with an unreadable metric only wins when alone, and
   output with no recognisable headers (localised Windows)
   falls back to scanning every row. Covered by test round 27.
