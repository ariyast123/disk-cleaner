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
