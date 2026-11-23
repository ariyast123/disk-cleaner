# GameMode VPN

Proton auto-pilot for game nights. Watches for your games and walks
you through the Proton routine that replaces split tunneling on the
free plan:

- **Game starts** → turn the Advanced Kill Switch off, disconnect
  Proton → play on your bare connection (real ping).
- **Game closes** → reconnect Proton, kill switch back to Advanced.

## Why it guides instead of clicking for you

Proton's Windows app has no CLI and no documented API (the official
CLI is Linux-only), and the Advanced kill switch is a set of
persistent Windows Filtering Platform filters that only the Proton
app itself may toggle. So GameMode automates everything around
those two clicks — game detection, live verification of your real
connection state (tunnel adapter + gateway reachability), the
session state machine, and a step panel that checks each step off
as your connection actually changes — and opens Proton for you at
the right moment.

## What it detects

- **Protected** — a Proton tunnel adapter is up.
- **Bare** — no tunnel, and your LAN gateway answers: plain internet
  works, so the kill switch is not blocking.
- **Blocked** — no tunnel and the gateway does not answer: the
  Advanced Kill Switch is doing its job. Expected mid-routine, and
  the step panel says exactly what to do next.
- **Unknown** — not enough information (the panel falls back to
  generic steps).

## Watched games (defaults)

Counter-Strike 2 (`cs2.exe`), Rust (`rustclient.exe`), FiveM / GTA V
(`fivem*.exe`, `gta5.exe`), Overwatch (`overwatch.exe`). Each can be
switched off; custom games can be added with their process names.

## Safety

- Never touches firewall rules, services, or the Proton app's files.
- Never kills processes. It only *observes* processes and adapters,
  and *launches* Proton when you ask (or automatically, if enabled).
- A manual **Restore VPN** button is always available.
- If a game was running while Proton was off, no restore is nagged —
  restore prompts only appear when the VPN was on before the session.

## Updates

GameMode updates itself through GitHub, like Disk Cleaner: on
startup it checks `gamemode-vpn/version.json` in the
`ariyast123/disk-cleaner` repo, offers a one-click update when a
newer version exists, and shows a small **What's New** window once
after each update. Daily improvements alternate between Ariya's two
Muse instances under the protocol in `gamemode-vpn/COORDINATION.md`
in that repo.

## Files

- `gamemode_vpn_app.py` — the CustomTkinter UI.
- `gamemode_core.py` — watcher, state machine, probes, settings.
- `build.bat` — builds `dist\GameModeVPN.exe` (PyInstaller).
- Settings and log: `%USERPROFILE%\GameModeVPN\` (`settings.json`,
  `gamemode.log`) — never next to the exe.

## Run without building

```
pip install customtkinter psutil
python gamemode_vpn_app.py
```
