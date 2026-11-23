# HeatWatch

Game-session temperature guard for Ariya's gaming laptop
(i7-11800H + RTX 3060). It watches CPU/GPU temperatures while a
watched game runs, records each session's peaks and time spent
over the warning line, warns live when the CPU cooks, and keeps
a running verdict — healthy / hot / repaste due — computed from
the median peak of recent full-length sessions. The point is a
data-driven answer to "do I need to repaste yet?". Every session
also keeps its temperature samples, and each history row has a
Graph button that opens a small CPU/GPU line chart for that
session, with the warning lines drawn in.

## Temperature sources (in order)

1. **LibreHardwareMonitor web feed** — LHM (free, open source,
   v0.9.6) running as administrator with Options > Remote Web
   Server ticked; HeatWatch polls
   `http://127.0.0.1:8085/data.json`.
2. **LibreHardwareMonitor WMI** — namespace
   `root\LibreHardwareMonitor` (fallback
   `root\OpenHardwareMonitor`), published whenever LHM runs.
3. **nvidia-smi** — GPU only; ships with the NVIDIA driver.

Get LibreHardwareMonitor from its GitHub releases or
`winget install LibreHardwareMonitor.LibreHardwareMonitor`.
Avoid look-alike download sites (librehardwaremonitor.com is
NOT affiliated with the project).

## Run / build

- Run from source: `pip install customtkinter psutil pystray
  pillow` then `python heatwatch_app.py`.
- Build: run `build.bat` → `dist\HeatWatch.exe`.

Data (settings, session history, log) lives in `~/HeatWatch`,
never next to the exe.

## Updates

Self-updates from this repo's `heatwatch/` folder, following
the same protocol as Disk Cleaner and GameMode VPN (see
COORDINATION.md): cache-busted checks every few minutes, a
What's New dialog after updating, and a finish_update.bat
helper that waits (capped ~30 s) for the app to exit, rebuilds,
copies the fresh exe over the launched one and relaunches.
