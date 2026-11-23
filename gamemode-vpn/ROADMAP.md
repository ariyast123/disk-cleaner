# GameMode VPN — improvement roadmap

The daily update takes the top unfinished item. Skip items blocked
on a decision Ariya has not made. Detection robustness always
outranks new features: a wrong "protected" or "bare" claim is the
worst bug this app can ship.

1. **Windows detection hardening.** Verify the Proton adapter names
   the current Proton Windows app actually creates (WireGuard/Wintun
   naming) and the exe's install path on a real machine; add a
   registry uninstall-key lookup as a path fallback. Keep every
   probe degrading to "unknown", never to a guess.
2. **Session history.** Record each game session (game, start,
   length, peak state) to a local JSON history in ~/GameModeVPN and
   show a small history list in the UI.
3. **Minimize to tray.** Optional tray icon (pystray) so the watcher
   can live in the tray during long sessions; restore on click.
4. **Exe icon + branding.** A proper .ico for GameModeVPN.exe in
   build.bat, matching the violet/cyan look.
5. **Ping proof.** After Game Mode turns on, optionally measure and
   show the real ping to a configurable host, so the improvement is
   visible, not just claimed. Off by default (privacy: it contacts
   the chosen host).
6. **UIA auto-click investigation.** Research whether Proton's
   current Windows UI exposes stable UI-Automation targets for
   Disconnect/Connect and the kill-switch control. Only ship it if
   it is provably reliable across a version bump, default OFF,
   guided mode always available as fallback. If the investigation
   says no, close this item with the evidence recorded here.
