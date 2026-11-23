For the phone Muse — from the web Muse, at Ariya's request (he just had HeatWatch built and released as v1.0.0):

A third app has joined the repo: HeatWatch, in the `heatwatch/` folder — a game-session temperature guard (LibreHardwareMonitor web/WMI + nvidia-smi fallback, session peaks, repaste verdict). Same system as GameMode VPN:

1. Rebuild the project locally from `heatwatch/` in the repo (sources, build.bat, icon, README, ROADMAP, COORDINATION, PATCH_NOTES_LOG, NEXT_TURN, version.json, and `heatwatch/tests/` with all 12 test files; venv with customtkinter + psutil + pyflakes + pillow; GUI rounds 8 and 11 run under xvfb-run).
2. Read `heatwatch/COORDINATION.md` and follow it as the standing protocol. Its baton (`heatwatch/NEXT_TURN.txt`) is independent and currently reads "web"; after your own HeatWatch updates you flip it to "web", after mine I flip it to "phone".
3. Create a matching daily job in the phone chat (~19:23 Los Angeles) implementing that protocol: on your turn, take the top ROADMAP item, run the full 12-round suite, publish only if everything passes, flip the baton last, and send Ariya a short note with only the version number — no patch notes in chat, ever.
4. Extend your Sunday weekly digest with HeatWatch's PATCH_NOTES_LOG.md as its own section, next to Disk Cleaner's and GameMode's.
5. Standing rule, same as GameMode: quality over speed — full suite, publish nothing on a failing day; focus on sensor-reading robustness, session correctness, verdict sanity.

When this is set up, please delete this file (that is the receipt) and confirm to Ariya in the phone chat in your own words.
