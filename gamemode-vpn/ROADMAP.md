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
4. **Exe icon + branding.** A proper .ico for GameModeVPN.exe in
   build.bat, matching the violet/cyan look.
5. **Ping proof.** After Game Mode turns on, optionally measure and
   show the real ping to a configurable host, so the improvement is
   visible, not just claimed. Off by default (privacy: it contacts
   the chosen host).
6. **UIA auto-click — DONE in v1.2.0 as Auto mode.** At Ariya's
   direct request (Nov 22, 2026) it shipped default ON with the
   strict conditions kept: exact-name button matching (Connect can
   never hit Disconnect), live state verification after every
   click, and automatic fallback to the guided steps on any
   failure. Watch for Proton UI renames in future updates; if the
   buttons move, the fallback covers it and the names in
   `AUTO_BUTTONS` (gamemode_core.py) are the fix.
