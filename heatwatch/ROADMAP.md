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
4. **LHM autostart helper** — DONE (v1.4.0, Nov 24, 2026). A
   guided one-time setup that registers LibreHardwareMonitor
   to start elevated at boot (Task Scheduler), so HeatWatch
   always has its source. A button in Settings opens a dialog
   showing the current state, with Set up / Remove actions
   (one admin approval each); the Settings card shows whether
   autostart is on or off.
5. **Idle baseline** — DONE (v1.3.1, Nov 23, 2026). Idle
   temperatures are sampled once a minute outside sessions
   (kept a week); the 24-hour median shows in the repaste
   verdict card next to the gaming peaks, and the five
   minutes after a session ends are skipped so post-game
   heat never pollutes it.
6. **Fan-speed capture** — DONE (v1.4.1, Nov 24, 2026).
   Where LHM exposes fan RPM (web feed first, WMI filling in
   when it already runs for the temperatures), each session
   records its fan range (lowest/highest RPM), shown live in
   the session card, in history rows and in the graph window.
   A session with no fan sensor shows a dash, never a guess,
   and the fan reading never triggers an extra probe, so
   polling costs nothing extra.
7. **Verdict follows your warning line** — DONE (v1.4.2, Nov 25,
   2026). The repaste verdict judged the median peak against
   fixed 95/98°C thresholds while the CPU warning line is
   changeable in Settings, so a lowered line still read
   "healthy" next to a live UI flagging the same peaks. The
   verdict now judges the median peak against the current
   warning line ("hot" at the line, "repaste" 3°C past it),
   with 95°C kept as the default, and the verdict card shows
   the line it judged against.
8. **Impossible sensor readings dropped** — DONE (v1.4.3, Nov 25,
   2026). LHM sometimes publishes 255 °C / -55 °C for a missing
   probe, or a fan RPM in the hundreds of thousands, and
   HeatWatch took it at face value — one dead probe could fake
   a 255 °C peak and push the verdict to "repaste". Temps
   outside -40…130 °C and fan speeds outside 0…100,000 RPM
   are now dropped at the parse step in all three readers, so
   they read as "no reading" and the fallback sources still
   get their chance; a stopped fan at 0 RPM is kept.
