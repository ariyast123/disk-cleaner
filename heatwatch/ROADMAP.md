# HeatWatch roadmap

1. **First release (v1.0.0)** — DONE. Session temperature
   tracking via LibreHardwareMonitor (web feed, then WMI) with
   nvidia-smi GPU fallback; per-session peaks and over-line
   time; sustained-heat tray warning; repaste verdict (median
   peak of the last 5 full sessions); tray + boot-minimized;
   hardened self-update.
2. **Per-session temperature graph** — DONE (v1.1.0, Nov 22,
   2026). The session's samples are stored (thinned past 600
   points so long sessions stay bounded) and each history row
   has a Graph button opening a small CPU/GPU line chart with
   the warning lines drawn in.
3. **Custom games in the UI** — add/remove games like GameMode
   has (v1.0.0 ships toggles only).
4. **LHM autostart helper** — a guided one-time setup that
   registers LibreHardwareMonitor to start elevated at boot
   (Task Scheduler), so HeatWatch always has its source.
5. **Idle baseline** — track idle temperatures outside sessions
   and show them next to gaming peaks; a rising idle baseline
   is an early dust/paste signal.
6. **Fan-speed capture** — where LHM exposes fan RPM, record
   the session's fan range alongside temps (a maxed fan with
   rising temps strengthens the repaste verdict).
