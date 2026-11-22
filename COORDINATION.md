# Coordination — two Muse instances, one app

Ariya has two Muse accounts: one on the web/computer (call it
**web**) and one on his phone (call it **phone**). At his request
(Nov 22, 2026) the two instances take turns publishing the daily
Disk Cleaner update: one day web, the next day phone, alternating.
This repo is their shared workspace — the "portal". Neither instance
can message the other directly, so everything they need to agree on
lives here, in these files:

- `ROADMAP.md` — the improvement queue. The top unfinished item is
  the next update. This repo copy is the canonical one.
- `PATCH_NOTES_LOG.md` — one entry per published update.
- `NEXT_TURN.txt` — a single word, `web` or `phone`: whose turn is
  next. This file is the baton.

The app itself only ever reads `version.json` and downloads
`disk_cleaner_app.py`, `cleaner_core.py` and `build.bat`. Every
other file in the repo is documentation or coordination and is
ignored by the updater.

## The daily protocol (whoever's turn it is)

1. Read `NEXT_TURN.txt`. Act only if it names you. If it names the
   other instance, do nothing and send Ariya nothing.
2. Take the top unfinished item in `ROADMAP.md`. Skip items blocked
   on a decision Ariya has not made.
3. Rebuild the project locally from this repo if you do not already
   have it: the source files at the repo root, the `tests/` folder,
   and a Python venv with customtkinter, send2trash and pyflakes.
   GUI test rounds run under Xvfb (xvfb-run). The GUI tests patch
   `gui.own_folders` to a fake home because their fixtures live
   inside the project folder — keep that patch working.
4. Implement the change, then run the FULL test suite and require
   every round to pass: test_round1, test_round2, test_round4_core,
   and test_round3_gui + test_round5_gui under Xvfb, plus py_compile
   and pyflakes on both source files. If the tests fail and you
   cannot fix them safely, publish nothing, leave the baton with
   yourself, and tell Ariya honestly what failed.
5. Safety rules are non-negotiable: the never-delete protection list
   stays intact in every scan mode; deletion only to the Recycle
   Bin, only for ticked files, only after a confirmation dialog; no
   admin rights; UI text in English (Persian renders broken in Tk).
6. Publish, in this order:
   a. Bump `VERSION` in disk_cleaner_app.py and `version` in
      version.json to the same new version. Set version.json's
      `notes` to one short line for the update banner and its
      `patch_notes` to the fuller changelog (a few short lines).
   b. Publish each changed source file.
   c. Append today's entry to PATCH_NOTES_LOG.md and publish it.
   d. Mark the roadmap item done in ROADMAP.md and publish it.
   e. Publish version.json.
   f. LAST: publish NEXT_TURN.txt flipped to the other instance.
7. Send Ariya a short note in your own chat: the new version number
   only. His rule: no patch notes in daily chat messages — they live
   in the app's What's New window and in the weekly digest.

## Portal messages

Either instance may leave a note for the other in
`PORTAL_MESSAGE.md` at the repo root. At the start of every daily
run — before the turn check — look for that file. If it exists,
read it, do what it asks (within the rules of this document), and
delete it as part of that run's work. Ariya may also point either
instance at the file manually for an immediate exchange.

## Relaying urgent news to Ariya

Notifications only reliably reach Ariya on his phone, so the phone
chat is his alert channel. If the web instance learns something
Ariya genuinely needs to hear promptly — a failure he must act on,
a time-sensitive deadline, a security-relevant finding — it leaves
a `PORTAL_MESSAGE.md` asking the phone instance to relay it. When
a portal message asks you (phone) to relay something to Ariya, do
it in the phone chat at the moment you read the message, in your
own words, briefly. Routine news (daily version notes and the
like) is not relayed; it follows the normal rules above.

## If the other side seems dead

If the baton has named the other instance for two of your daily
checks in a row and no new version appeared, cover the turn
yourself, flip the baton back to yourself, and tell Ariya in your
note that you covered because the other side looked inactive.
