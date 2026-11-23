# HeatWatch patch notes log

## 2026-11-22 — v1.0.0 (first release)

HeatWatch is born: it watches CPU and GPU temperatures during
game sessions (via LibreHardwareMonitor, with nvidia-smi as
the GPU fallback), records peaks and time over the warning
line for every session, warns live when the CPU stays over
the line, and keeps a repaste verdict — healthy, hot, or
repaste due — from your recent full sessions. Starts hidden
in the tray at boot, and updates itself like GameMode VPN
does. 12 test rounds, all passing at release.
