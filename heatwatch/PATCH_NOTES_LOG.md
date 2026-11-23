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
