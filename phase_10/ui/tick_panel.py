"""Scheduler visibility: pause/resume, heartbeat, manual one-shot tick."""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from config.settings import load_settings
from phase_10.tick import run_agentic_tick
from phase_10.tick_control import load_tick_control, set_tick_paused

_STALE_MINUTES = 20


def _parse_utc(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_tick_panel() -> None:
    st.subheader("Tick scheduler")
    control = load_tick_control()
    last_at = _parse_utc(control.last_tick_at)

    st.caption(
        "Background work runs when `python -m phase_10.jobs.run_agentic_tick` executes "
        "(production: systemd `ito-agentic-tick.timer` every ~15m). "
        "This panel does not start a timer by itself — use **Run one tick now** for local dev, "
        "or enable the deploy timer on the server."
    )

    c_status, c_last, c_summary = st.columns(3)
    with c_status:
        if control.paused:
            st.metric("Scheduler", "Paused", help="Cron/timer ticks exit immediately.")
        else:
            st.metric("Scheduler", "Active", help="Ticks may run due jobs when invoked.")
    with c_last:
        st.metric("Last tick", control.last_tick_at or "Never")
    with c_summary:
        st.metric("Last result", (control.last_tick_summary or "—")[:80])

    if not control.paused and last_at is None:
        st.warning(
            "No tick has run yet. On your laptop the systemd timer is usually **not** "
            "installed — click **Run one tick now** or run the CLI in a terminal."
        )
    elif not control.paused and last_at is not None:
        age_min = (datetime.now(timezone.utc) - last_at).total_seconds() / 60.0
        if age_min > _STALE_MINUTES:
            st.warning(
                f"No tick in {int(age_min)} minutes. The 15m timer may be off — "
                "use **Run one tick now** or check `journalctl -u ito-agentic-tick` on the server."
            )

    btn_pause, btn_run = st.columns(2)
    with btn_pause:
        if control.paused:
            if st.button("Resume scheduler", type="primary", key="agentic_resume_tick"):
                set_tick_paused(False)
                st.rerun()
        else:
            if st.button("Pause scheduler", key="agentic_pause_tick"):
                set_tick_paused(True)
                st.rerun()
    with btn_run:
        run_now = st.button("Run one tick now", key="agentic_run_tick_now")

    if run_now:
        settings = load_settings()
        if not settings.database_url:
            st.error("DATABASE_URL is not set — tick needs Postgres.")
            return
        hint = " (scheduler is paused; this one-shot still runs)" if control.paused else ""
        with st.spinner(f"Running agentic tick…{hint}"):
            result = run_agentic_tick(settings, force=True)
        ran = [r for r in result.results if r.action == "ran"]
        skipped = [r for r in result.results if r.action == "skipped"]
        lines = [f"**{r.job_id}**: {r.detail}" for r in result.results if r.job_id != "_tick"]
        if lines:
            st.markdown("\n".join(f"- {line}" for line in lines))
        st.success(f"Tick finished — {len(ran)} ran, {len(skipped)} skipped.")
        st.rerun()
