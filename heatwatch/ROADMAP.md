# HeatWatch roadmap

1. **First release (v1.0.0)** — DONE. Session temperature
   tracking via LibreHardwareMonitor (web feed, then WMI) with
   nvidia-smi GPU fallback; per-session peaks and over-line
   time; sustained-heat tray warning; repaste verdict (median
   peak of the last 5 full sessions); tray + boot-minimized;
   hardened self-update.
2. **Per-session temperature graph** — store the session's
   samples (they are already collected tick by tick) and draw a
   small CPU/GPU line chart in the history detail, so a spike's
   shape is visible, not just its peak.
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
