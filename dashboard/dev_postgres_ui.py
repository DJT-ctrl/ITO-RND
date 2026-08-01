"""Streamlit UI for one-click local Postgres setup."""

from __future__ import annotations

import time

import streamlit as st

from config.settings import load_settings
from dashboard.dev_postgres import (
    BootstrapResult,
    DevPostgresStatus,
    bootstrap_local_postgres,
    diagnose_dev_postgres,
)

_DIAGNOSE_TTL_S = 30.0
_SESSION_STATUS_KEY = "dev_postgres_status_cache"
_SESSION_AT_KEY = "dev_postgres_status_at"


def _step_icon(state: str) -> str:
    return {
        "ok": "✅",
        "warn": "⚠️",
        "error": "❌",
        "pending": "⏳",
    }.get(state, "•")


def _cached_diagnose(*, force: bool = False) -> DevPostgresStatus:
    """Reuse last diagnose for a few seconds so sidebar reruns stay snappy."""
    now = time.monotonic()
    cached = st.session_state.get(_SESSION_STATUS_KEY)
    cached_at = float(st.session_state.get(_SESSION_AT_KEY, 0.0) or 0.0)
    if (
        not force
        and cached is not None
        and (now - cached_at) < _DIAGNOSE_TTL_S
    ):
        return cached
    status = diagnose_dev_postgres()
    st.session_state[_SESSION_STATUS_KEY] = status
    st.session_state[_SESSION_AT_KEY] = now
    return status


def render_dev_postgres_setup(*, compact: bool = False) -> DevPostgresStatus:
    """Show checklist + one-click bootstrap. Returns latest status."""
    status = _cached_diagnose()

    if status.ready and compact:
        st.caption("Postgres: ready")
        return status

    if compact:
        st.caption("Postgres: not ready")
        if st.button(
            "Set up local database",
            type="primary",
            key="dev_postgres_sidebar_setup",
            use_container_width=True,
        ):
            with st.spinner("Starting Postgres…"):
                result = bootstrap_local_postgres()
            if result.ok:
                st.session_state.pop(_SESSION_STATUS_KEY, None)
                st.success(result.message)
                st.rerun()
            else:
                st.error(result.message[:200])
        return status

    if not compact:
        st.subheader("Local database")
        st.caption(
            "Dev shortcut: creates `.env` if needed, starts Docker Postgres, "
            "runs schema migrate, and wires `DATABASE_URL` for Streamlit on your Mac."
        )

    for step in status.steps:
        line = f"{_step_icon(step.state)} **{step.label}**"
        if step.detail:
            line += f" — {step.detail}"
        st.markdown(line)

    col_a, col_b = st.columns([1, 1])
    with col_a:
        setup = st.button(
            "Set up local database",
            type="primary",
            key="dev_postgres_setup_btn",
            use_container_width=True,
        )
    with col_b:
        refresh = st.button(
            "Check again",
            key="dev_postgres_refresh_btn",
            use_container_width=True,
        )

    if setup:
        with st.spinner("Starting Postgres (Docker) and applying schema…"):
            result: BootstrapResult = bootstrap_local_postgres()
        st.session_state.pop(_SESSION_STATUS_KEY, None)
        if result.ok:
            st.success(result.message)
        else:
            st.error(result.message)
        if result.logs:
            with st.expander("Setup log", expanded=not result.ok):
                st.code("\n".join(result.logs))
        if result.ok:
            st.rerun()

    if refresh:
        _cached_diagnose(force=True)
        st.rerun()

    return status


def require_postgres_for_page(*, compact: bool = False) -> bool:
    """Block page content until Postgres is reachable (or user is still on setup UI)."""
    settings = load_settings()
    status = _cached_diagnose()
    if status.ready and settings.database_url:
        return True

    if not compact:
        st.warning(
            "This page needs a local Postgres database. "
            "Use the button below — no terminal steps required."
        )
    render_dev_postgres_setup(compact=compact)
    return False
