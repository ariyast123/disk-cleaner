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
3. **Custom games in the UI** — DONE (v1.3.0, Nov 23,
   2026). An Add game button takes a name and comma-separated
   process names and watches the game like the built-in ones;
   custom games get a × on their row to remove them, and the
   five built-in games cannot be removed.
4. **LHM autostart helper** — a guided one-time setup that
   registers LibreHardwareMonitor to start elevated at boot
   (Task Scheduler), so HeatWatch always has its source.
5. **Idle baseline** — DONE (v1.3.1, Nov 23, 2026). Idle
   temperatures are sampled once a minute outside sessions
   (kept a week); the 24-hour median shows in the repaste
   verdict card next to the gaming peaks, and the five
   minutes after a session ends are skipped so post-game
   heat never pollutes it.
6. **Fan-speed capture** — where LHM exposes fan RPM, record
   the session's fan range alongside temps (a maxed fan with
   rising temps strengthens the repaste verdict).
