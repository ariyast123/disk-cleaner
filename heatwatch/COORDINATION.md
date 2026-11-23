# HeatWatch — two-instance coordination

Same arrangement as Disk Cleaner and GameMode VPN: this repo
(`ariyast123/disk-cleaner`, folder `heatwatch/`) is the shared
mailbox between Ariya's web Muse and phone Muse. The daily
update duty alternates via `heatwatch/NEXT_TURN.txt`, OPPOSITE
to Disk Cleaner's baton is NOT required here — HeatWatch has
its own independent baton, starting at "web".

## Daily protocol (whose turn the baton names)

1. Check `PORTAL_MESSAGE.md` in the repo root first (see the
   Disk Cleaner COORDINATION.md for the portal rules — they
   apply repo-wide).
2. Read `heatwatch/NEXT_TURN.txt`. If it names the OTHER side,
   stay silent and end (cover rule: if the baton names the
   other side for two of your daily checks with no new version,
   cover the turn, flip the baton to yourself, and tell Ariya
   you covered).
3. Take the top unfinished item in `heatwatch/ROADMAP.md`.
   Implement ONE focused improvement. Never weaken the data
   rules: sessions are judged on real samples only, the verdict
   uses full-length sessions (>= 10 min) only, and a missing
   temperature source must stay visible as "none", never
   silently filled with guesses.
4. Run the FULL test suite (every round in `heatwatch/tests/`;
   GUI rounds 8, 11 and 15 under xvfb-run with tests/venv).
   Publish nothing on a failing day — revert and report
   honestly.
5. Publish order: changed source files -> tests ->
   PATCH_NOTES_LOG.md -> ROADMAP.md -> version.json ->
   NEXT_TURN.txt flipped to the other side, LAST.
6. Chat delivery: a short Persian note with ONLY the new
   version number. Patch notes live in version.json's
   `patch_notes` field and PATCH_NOTES_LOG.md; the app shows
   them in its What's New dialog, and the Sunday weekly digest
   (both chats, ~20:00 Los Angeles) collects them.

## Standing quality rule (Ariya's, from GameMode)

Quality over speed: the full test suite, every time; bugs are
caught before publishing, not after. Focus order for HeatWatch:
sensor-reading robustness across LHM tree/WMI variants,
session-tracker correctness, verdict sanity, UI consistency
with GameMode VPN.
