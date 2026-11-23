# GameMode VPN — coordination between Ariya's two Muse instances

GameMode VPN lives in this repo under `gamemode-vpn/`, next to Disk
Cleaner (repo root). Ariya has two Muse accounts (web/desktop and
phone) with separate memories. This folder is how the two instances
share the daily-improvement work on GameMode VPN. The repo is the
source of truth — if this file and a chat disagree, this file wins.

## The two-app arrangement

Both apps get a daily update, one per instance, and the turns are
OPPOSITE: on a day when one instance updates Disk Cleaner, the other
updates GameMode VPN. Disk Cleaner's baton is `NEXT_TURN.txt` at the
repo root; GameMode's baton is `gamemode-vpn/NEXT_TURN.txt`. They
start opposite and each side flips only the baton of the app it just
updated, so the arrangement holds by itself.

## Shared files (all under `gamemode-vpn/`)

- `gamemode_vpn_app.py`, `gamemode_core.py`, `build.bat` — the app
  sources Ariya builds (PyInstaller). Only these three are downloaded
  by the in-app updater.
- `version.json` — `{version, notes, patch_notes}`. The app checks
  this file on startup; bumping it is what offers users the update.
  `notes` is one short line for the banner; `patch_notes` is a few
  short lines the app shows in its What's New window after updating
  and the weekly digest reads.
- `ROADMAP.md` — the improvement queue. Detection robustness
  outranks features, always.
- `PATCH_NOTES_LOG.md` — append one entry per published update
  (date, version, patch notes). Never rewrite old entries.
- `NEXT_TURN.txt` — contains exactly `web` or `phone`: whose turn
  the next daily GameMode update is.
- `tests/` — the full test suite (rounds 1–9). Keep it in the repo
  so either instance can verify to the same standard.

## Ariya's standing rules for this app

- **Quality over speed — time does not matter.** The final result
  matters, not how long it took. Catch the bugs BEFORE publishing:
  run the FULL suite for every change, add tests for new behavior,
  and if anything fails, publish nothing that day and say so
  honestly. A skipped day is acceptable; a broken update is not.
- **Chat messages carry only the version number.** Patch notes go
  to `version.json` (`patch_notes`), `PATCH_NOTES_LOG.md`, the
  What's New window, and the weekly digest — never in the daily
  chat note.
- **Never weaken the safety rules** (next section), not even if a
  roadmap item seems to ask for it. Flag it instead.

## Safety rules (never break)

- The app only OBSERVES the system and LAUNCHES Proton. It never
  kills processes, never touches the firewall or WFP filters, never
  edits services or the registry beyond its own Start-with-Windows
  Run value (user's explicit toggle), and needs no admin rights.
- Fully automatic Proton control is impossible by design: Proton's
  Windows app has no CLI/API and only the app can toggle its
  Advanced kill switch. The guided flow is the product. Do not
  "fix" this with process killing, filter tampering, or brittle
  screen-scraping hacks; the UIA roadmap item is an investigation
  with strict conditions, default OFF if it ever ships.
- Detection must stay honest: probes that cannot tell report
  `unknown`; the app never claims protected/bare on a guess.
- Settings and logs live in `~/GameModeVPN`, never next to the exe.

## What to focus on when updating (Ariya's priorities)

1. **Real-Windows detection first.** Proton adapter names, exe
   install paths, gateway parsing — the parts only a real Windows
   machine settles. Make probes more robust, keep the fallbacks.
2. **State machine correctness.** Sessions, debounce, restore
   nagging only when the VPN was on before the game. No false
   claims in either direction.
3. **The guided flow's clarity.** Steps must match what Proton's
   current UI actually shows; if Proton renames a setting, update
   the step text the same day it is noticed.
4. **UI consistency.** Dark gaming look (violet/cyan), English UI
   text (Tk renders Persian disconnected), no layout regressions —
   screenshot the states when you change layout.

## Daily protocol (whoever's turn it is)

0. **Portal inbox first**: if `PORTAL_MESSAGE.md` exists at the repo
   root, read it. If it concerns you, act within these rules, then
   delete it. If it is for the other instance, leave it alone.
1. Read `gamemode-vpn/NEXT_TURN.txt`. If it names the OTHER
   instance, do nothing (Disk Cleaner is yours that day instead).
   Cover rule: if the baton has named the other instance for two of
   your daily checks in a row with no new version published, cover
   the turn yourself, flip the baton back to yourself, and tell
   Ariya you covered because the other side seemed inactive.
2. Read `gamemode-vpn/ROADMAP.md`; take the top unblocked item and
   implement ONE focused improvement.
3. Run the FULL test suite: rounds 1, 2, 3, 4, 7, 8, 9 with plain
   Python; rounds 5 and 6 (GUI) under `xvfb-run -a` with the test
   venv's Python (customtkinter + psutil); plus `py_compile` and
   `pyflakes` on both source files. GUI tests monkeypatch
   `core.settings_path` / `core.log_path` to a temp dir before
   constructing the app — keep that working. All rounds must pass.
4. Bump the version (patch bump for fixes/polish, minor for a new
   feature), write `notes` (one line) and `patch_notes` (a few
   lines) into `version.json`, append the entry to
   `PATCH_NOTES_LOG.md`, and update `ROADMAP.md`.
5. Publish with the GitHub contents API, in this order: changed
   source files → `PATCH_NOTES_LOG.md` → `ROADMAP.md` →
   `version.json` → `NEXT_TURN.txt` flipped to the other instance,
   LAST.
6. Send Ariya a short chat note with ONLY the new version number
   (e.g. "آپدیت روزانه GameMode VPN منتشر شد — نسخه ۱٫۱٫۱"). If the
   tests fail and nothing is published, send an honest failure note
   instead and do not flip the baton.
