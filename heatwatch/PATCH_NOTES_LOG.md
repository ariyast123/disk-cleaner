# HeatWatch patch notes log

## 2026-11-22 — v1.1.0

Every session now keeps its temperature samples, and each
history row has a Graph button that opens a small CPU/GPU line
chart for that session, with the CPU and GPU warning lines
drawn in so a spike's shape is visible, not just its peak.
Long sessions thin their stored samples instead of growing
the history file without bound, and sessions recorded before
this version simply say they have no samples. 13 test rounds,
all passing.

## 2026-11-22 — v1.0.0 (first release)

HeatWatch is born: it watches CPU and GPU temperatures during
game sessions (via LibreHardwareMonitor, with nvidia-smi as
the GPU fallback), records peaks and time over the warning
line for every session, warns live when the CPU stays over
the line, and keeps a repaste verdict — healthy, hot, or
repaste due — from your recent full sessions. Starts hidden
in the tray at boot, and updates itself like GameMode VPN
does. 12 test rounds, all passing at release.

## 2026-11-22 — v1.1.1 (off-cycle, at Ariya's direct request)

UI polish pass: CPU and GPU cards gain gauge bars that fill
and change color with the heat, a status orb in the sidebar
shows the state at a glance (grey for no source, green calm,
cyan in a session, pulsing red over the line), a new live
graph card draws the last minutes of CPU/GPU temperatures
with the CPU warning line dashed in, the session card's
border turns red while the CPU is over the line, and every
history row gets a severity dot colored by its peak. Two new
test rounds (14 helpers, 15 GUI polish); all 15 rounds pass.

## 2026-11-22 — v1.2.0 (off-cycle, at Ariya's direct request)

A deeper UI pass. A header band now shows the live state in
words (waiting for sensors, idle, in session with the game
named, running hot). The session card gains three chips —
peak CPU, peak GPU, time over the line — colored by severity.
Every watched game gets a running dot that lights green while
it plays. The repaste verdict card's border takes the
verdict's color. The live graph labels the current CPU and
GPU values at its right edge. New test round 16 covers the
header, chips, dots, labels and verdict border; all 16
rounds pass.

## 2026-11-22 — v1.2.1 (off-cycle, at Ariya's direct request)

Optimization pass, no features changed. The WMI temperature
route spawns PowerShell — the most expensive probe HeatWatch
makes. When it comes back empty (LibreHardwareMonitor not
running), the app now remembers the miss for 60 seconds
instead of paying that spawn on every 3-second poll; a
successful WMI read clears the miss immediately, and all
merge results and source labels are exactly as before. New
test round 17 covers the cache; all 17 rounds pass.

## 2026-11-22 — v1.2.2 (off-cycle, at Ariya's direct request)

One-click updates. The helper no longer waits politely for
the app to close: its first move is taskkill — every running
copy of HeatWatch.exe dies at once — then a short capped
loop verifies they are gone (a survivor is logged and the
build proceeds anyway), then the build, copy-back and
relaunch run as before. The app's guaranteed-exit timer drops
from 3 s to 1 s. Test round 10 updated for the kill-first
helper; all 17 rounds pass.

## 2026-11-22 — v1.2.3 (test update)

- Test update at Ariya's request, to exercise the update
  flow. No changes to the app itself.

## 2026-11-22 — v1.2.4

- Automatic-update fix, found by Ariya's live test: the app
  closed on Update but the helper (launched with no console,
  DETACHED_PROCESS) died silently after its first log line on
  his PC; the same finish_update.bat run by hand worked. The
  helper now launches with its own console window
  (CREATE_NEW_CONSOLE), identical to a manual double-click.
  Landing on this version takes one manual finish_update run;
  after that, updates are fully automatic.

## 2026-11-22 — v1.2.5 (test update)

- Test update at Ariya's request, to exercise the fixed
  automatic update flow. No changes to the app itself.

## 2026-11-23 — v1.3.0

Custom games in the UI, like GameMode has: an Add game button
on the Watched Games list takes a name and its process names
(comma separated) and watches the game like the built-in
ones. Custom games get a × on their row to remove them; the
five built-in games cannot be removed. New test round 18
covers adding, duplicates, and removing; all 18 rounds pass.

## 2026-11-23 — v1.3.1

HeatWatch now tracks idle temperatures: one sample a minute
while no watched game is running, kept for a week, with the
24-hour median shown as an idle baseline in the repaste
verdict card, next to the gaming peaks — a rising idle
baseline is an early dust/paste signal. The five minutes
after a session ends are skipped so post-game heat never
pollutes the baseline, and a tick with no temperature source
is dropped, never guessed. New test round 19 covers the
recording throttle, the median window, the cooldown and the
verdict-card label; all 19 rounds pass. (This run also fixed
the round-10 version assertion, which v1.3.0 had left
stale at 1.2.5.)

## 2026-11-24 — v1.3.2

- The automatic update hand-off was rebuilt: the app now hands
  finish_update.bat to Explorer instead of starting it itself.
  A helper launched by the app died together with the app it had
  just closed (console opened, closed, nothing rebuilt), while a
  manual double-click always worked. Explorer-launched, the
  helper is fully independent of the app.
- The helper now logs a 'relaunch issued' line at the end, so any
  future failure leaves clear evidence in update_build.log.

## 2026-11-24 — v1.4.0

LHM autostart helper: a "Set up LHM to start at boot…" button
in Settings opens a guided one-time setup that registers
LibreHardwareMonitor in Task Scheduler to start elevated at
every sign-in, so HeatWatch always has its CPU source — one
admin approval, and it can be removed again from the same
dialog. The Settings card shows whether autostart is on or
off, and the dialog says plainly when LHM is not installed
instead of offering a dead button. New test rounds 20 (task
registration and elevation) and 21 (the dialog); all 21 rounds
pass.

## 2026-11-24 — v1.4.1

- Fan-speed capture: wherever LibreHardwareMonitor exposes fan
  RPM (web feed first, WMI filling in when it already runs for
  the temperatures), each session now records its fan range —
  lowest and highest RPM while the game ran — shown live in
  the session card, in every history row, and in the session
  graph window. A session with no fan sensor shows a dash,
  never a guess, and the fan reading never triggers an extra
  probe on its own, so polling costs nothing extra. A fan
  pinned at its maximum while temperatures keep climbing is
  now visible next to the peaks, which is the extra evidence
  the repaste verdict was missing. New test round 22 covers
  the web/WMI fan parsing, the merge rules, the per-session
  range and the range formatting; all 22 rounds pass.

## 2026-11-25 — v1.4.2

- The repaste verdict judged the median peak of recent full
  sessions against fixed 95/98°C thresholds, even though the
  CPU warning line is changeable in Settings — so a lowered
  line still read "healthy" while the live UI flagged the
  same peaks as over the line. The verdict now judges the
  median peak against the current warning line ("hot" at the
  line, "repaste" 3°C past it), with 95°C kept as the
  default, and the verdict card shows the line it judged
  against. New test in round 6 covers the line-following
  boundaries; all 21 rounds pass.
