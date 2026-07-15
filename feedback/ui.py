"""Streamlit helpers for the feedback-loop dashboard page."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from config.settings import Settings
from feedback.batch import (
    generate_feedback_for_prediction_id,
    run_feedback_batch,
    run_feedback_worker,
)
from feedback.calibration import apply_calibration
from feedback.generate import FEEDBACK_VERSION
from feedback.queue import count_feedback_queue_backlog
from feedback.runtime_flags import clear_overrides, load_overrides, save_overrides
from feedback.schemas import CalibrationStats, ClusterStats, FeedbackRecord
from feedback.dashboard_queries import (
    count_feedback_coverage,
    hybrid_feedback_cost_stats,
    list_clusters,
    list_recent_feedback,
)
from feedback.store import (
    fetch_calibration_stats,
    list_pending_feedback_for_review,
    refresh_cluster_stats,
    set_feedback_review_status,
)
from feedback.jobs.run_cluster_centroids import refresh_cluster_centroids
from feedback.summarize import refresh_cluster_rollups
from storage.vector_store import create_schema, get_connection
from validation_pipeline.store import list_predictions


def _section_header(title: str, help_markdown: str) -> None:
    """Subheader with a ? popover explaining the section."""
    left, right = st.columns([0.93, 0.07])
    with left:
        st.subheader(title)
    with right:
        with st.popover("?"):
            st.markdown(help_markdown)


def _metric(col, label: str, value, *, help_text: str, **kwargs) -> None:
    col.metric(label, value, help=help_text, **kwargs)


def render_feedback_settings_panel(settings: Settings) -> Settings:
    """Editable feature flags — persisted so worker/predict honor them too."""
    _section_header(
        "Feedback loop settings",
        """
These switches control the three learning mechanisms. **They matter.**

| Flag | When ON | When OFF (why turn off?) |
|------|---------|--------------------------|
| **Calibration** | Next predictions get a numeric percentile offset from past errors | A/B test: compare raw vs calibrated accuracy |
| **Feedback records** | After each validation, store a template lesson in the DB | Pause writing lessons while debugging validation |
| **Prompt injection** | Predictor sees up to N recent lessons from the same cluster | A/B test: does lesson text help, or only calibration? |

Safe production default: **feedback records ON**, **calibration and prompt
injection OFF** until held-out evaluation shows a lift.
Overrides are saved to `data/feedback_loop_overrides.json` and apply on the
next `load_settings()` call (Streamlit page reload, worker, CLI).
""",
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        cal_on = st.toggle(
            "Calibration",
            value=settings.validation_calibration_enabled,
            help=(
                "Adds mean prediction error (actual − predicted) to new "
                "percentile scores once enough validated rows exist. "
                "Turn OFF to measure baseline accuracy without the offset."
            ),
            key="fb_toggle_calibration",
        )
    with c2:
        fb_on = st.toggle(
            "Feedback records",
            value=settings.validation_feedback_enabled,
            help=(
                "After a prediction is validated (~48h later), write a structured "
                "lesson row. Turn OFF to stop creating new lessons (existing ones stay)."
            ),
            key="fb_toggle_feedback",
        )
    with c3:
        inj_on = st.toggle(
            "Prompt injection",
            value=settings.validation_feedback_injection_enabled,
            help=(
                "At predict time, inject a short block of recent same-cluster lessons "
                "into the Predictor prompt. Turn OFF for an A/B without lesson text."
            ),
            key="fb_toggle_injection",
        )
    with c4:
        inj_limit = st.number_input(
            "Injection limit",
            min_value=1,
            max_value=20,
            value=int(settings.validation_feedback_injection_limit),
            help=(
                "Max lesson rows injected per prediction. Keeps the prompt small "
                "(default 5). Higher = more context, more tokens."
            ),
            key="fb_injection_limit",
        )

    g1, g2, g3, g4 = st.columns(4)
    with g1:
        n_min = st.number_input(
            "Global N_min",
            min_value=1,
            max_value=500,
            value=int(settings.validation_calibration_n_min),
            help=(
                "Validated rows required before global calibration applies. "
                "Below this, raw percentiles are used (cold start)."
            ),
            key="fb_global_n_min",
        )
    with g2:
        cluster_n_min = st.number_input(
            "Cluster N_min",
            min_value=1,
            max_value=500,
            value=int(settings.validation_cluster_n_min),
            help=(
                "Samples required in a cluster before that cluster's own mean_delta "
                "is used for calibration (instead of global)."
            ),
            key="fb_cluster_n_min",
        )
    with g3:
        llm_on = st.toggle(
            "LLM hybrid (v2)",
            value=settings.validation_feedback_llm_enabled,
            help=(
                "For large misses, enrich lessons with Gemini. New v2 rows stay "
                "pending until human review. Staging only while injection is OFF."
            ),
            key="fb_toggle_llm",
        )
    with g4:
        llm_delta = st.number_input(
            "LLM |delta| min",
            min_value=1.0,
            max_value=50.0,
            value=float(settings.validation_feedback_llm_delta_min),
            help="Only call LLM when absolute prediction delta meets this threshold.",
            key="fb_llm_delta_min",
        )

    g5, g6, g7 = st.columns(3)
    with g5:
        llm_max = st.number_input(
            "LLM max / day",
            min_value=0,
            max_value=500,
            value=int(settings.validation_feedback_llm_max_per_day),
            help="Daily cap on hybrid/llm feedback rows (UTC).",
            key="fb_llm_max_day",
        )
    with g6:
        shadow_on = st.toggle(
            "Shadow mode",
            value=settings.validation_shadow_mode_enabled,
            help=(
                "Log soft-blend shadow_percentile in telemetry without changing "
                "the user-facing score (unless injectability mode is soft_blend)."
            ),
            key="fb_toggle_shadow",
        )
    with g7:
        inj_mode = st.selectbox(
            "Injectability mode",
            options=["hard_lock", "soft_blend", "shadow_only"],
            index=["hard_lock", "soft_blend", "shadow_only"].index(
                settings.validation_injectability_mode
                if settings.validation_injectability_mode
                in {"hard_lock", "soft_blend", "shadow_only"}
                else "hard_lock"
            ),
            help=(
                "hard_lock = neighbor score (safe default). "
                "soft_blend = blend LLM toward neighbor with weight w. "
                "shadow_only = hard_lock live + always log soft-blend shadow."
            ),
            key="fb_injectability_mode",
        )

    g8, g9, g10 = st.columns(3)
    with g8:
        blend_w = st.number_input(
            "Soft blend weight",
            min_value=0.0,
            max_value=1.0,
            value=float(settings.validation_soft_blend_weight),
            step=0.05,
            help="w in final = neighbor + w*(llm − neighbor). Default 0.15.",
            key="fb_soft_blend_weight",
        )
    with g9:
        inj_format = st.selectbox(
            "Injection format",
            options=["lessons", "rollup_top2", "rollup_contrastive"],
            index=["lessons", "rollup_top2", "rollup_contrastive"].index(
                settings.validation_feedback_injection_format
                if settings.validation_feedback_injection_format
                in {"lessons", "rollup_top2", "rollup_contrastive"}
                else "lessons"
            ),
            help=(
                "lessons = numbered rows (default). "
                "rollup_top2 = cluster roll-up + structured bias + top 2 examples. "
                "rollup_contrastive = roll-up + big-miss vs near-hit pair."
            ),
            key="fb_injection_format",
        )
    with g10:
        st.write("")

    a1, a2, a3, a4 = st.columns(4)
    with a1:
        auto_on = st.toggle(
            "Auto-approve hybrid",
            value=settings.validation_feedback_auto_approve_enabled,
            help=(
                "When ON, grounded hybrid v2 rows with |delta| ≤ cap can skip the "
                "human queue (reviewed_by=auto_approve). Default OFF."
            ),
            key="fb_toggle_auto_approve",
        )
    with a2:
        auto_max = st.number_input(
            "Auto-approve max / day",
            min_value=0,
            max_value=500,
            value=int(settings.validation_feedback_auto_approve_max_per_day),
            help="Daily cap on auto-approved hybrid rows (UTC).",
            key="fb_auto_approve_max",
        )
    with a3:
        auto_delta = st.number_input(
            "Auto-approve |delta| max",
            min_value=1.0,
            max_value=100.0,
            value=float(settings.validation_feedback_auto_approve_delta_max),
            help="Only auto-approve when absolute prediction delta is at or below this.",
            key="fb_auto_approve_delta_max",
        )
    with a4:
        st.write("")
        st.write("")
        save = st.button("Save settings", type="primary", key="fb_save_settings")

    r1, r2 = st.columns(2)
    with r1:
        st.write("")
    with r2:
        reset = st.button("Reset to .env defaults", key="fb_reset_settings")

    if save:
        save_overrides(
            {
                "validation_calibration_enabled": bool(cal_on),
                "validation_feedback_enabled": bool(fb_on),
                "validation_feedback_injection_enabled": bool(inj_on),
                "validation_feedback_injection_limit": int(inj_limit),
                "validation_calibration_n_min": int(n_min),
                "validation_cluster_n_min": int(cluster_n_min),
                "validation_feedback_llm_enabled": bool(llm_on),
                "validation_feedback_llm_delta_min": float(llm_delta),
                "validation_feedback_llm_max_per_day": int(llm_max),
                "validation_shadow_mode_enabled": bool(shadow_on),
                "validation_injectability_mode": str(inj_mode),
                "validation_soft_blend_weight": float(blend_w),
                "validation_feedback_injection_format": str(inj_format),
                "validation_feedback_auto_approve_enabled": bool(auto_on),
                "validation_feedback_auto_approve_max_per_day": int(auto_max),
                "validation_feedback_auto_approve_delta_max": float(auto_delta),
            }
        )
        st.success("Saved — applies on this page reload and to new worker/predict runs.")
        st.rerun()

    if reset:
        clear_overrides()
        st.success("Cleared dashboard overrides — back to .env / defaults.")
        st.rerun()

    overrides = load_overrides()
    if overrides:
        st.caption(
            f"Active dashboard overrides: `{', '.join(sorted(overrides.keys()))}` "
            f"(file: `data/feedback_loop_overrides.json`)."
        )
    else:
        st.caption("No dashboard overrides — using `.env` / built-in defaults.")

    # Return a settings object reflecting the form (already applied if saved+rerun).
    from dataclasses import replace

    return replace(
        settings,
        validation_calibration_enabled=bool(cal_on),
        validation_feedback_enabled=bool(fb_on),
        validation_feedback_injection_enabled=bool(inj_on),
        validation_feedback_injection_limit=int(inj_limit),
        validation_calibration_n_min=int(n_min),
        validation_cluster_n_min=int(cluster_n_min),
        validation_feedback_llm_enabled=bool(llm_on),
        validation_feedback_llm_delta_min=float(llm_delta),
        validation_feedback_llm_max_per_day=int(llm_max),
        validation_shadow_mode_enabled=bool(shadow_on),
        validation_injectability_mode=str(inj_mode),  # type: ignore[arg-type]
        validation_soft_blend_weight=float(blend_w),
        validation_feedback_injection_format=str(inj_format),  # type: ignore[arg-type]
        validation_feedback_auto_approve_enabled=bool(auto_on),
        validation_feedback_auto_approve_max_per_day=int(auto_max),
        validation_feedback_auto_approve_delta_max=float(auto_delta),
    )


def render_calibration_panel(settings: Settings) -> Optional[CalibrationStats]:
    """Global mean_delta and whether the N_min gate would apply."""
    _section_header(
        "Calibration (global)",
        """
**What this is:** a silent numeric correction, not AI advice.

After enough validated predictions, we compute the average error:
`mean_delta = average(actual_percentile − predicted_percentile)`.

On the **next** prediction:
`calibrated = clamp(raw + mean_delta, 0, 100)`.

- Positive mean_delta → model usually **under**estimates → we nudge scores up  
- Negative mean_delta → model usually **over**estimates → we nudge scores down  

This does **not** re-scrape LinkedIn. It only adjusts scores when predicting
*new* posts, once N ≥ N_min and Calibration is ON.
""",
    )
    conn = get_connection(settings)
    try:
        create_schema(conn)
        stats = fetch_calibration_stats(conn)
    finally:
        conn.close()

    n_min = settings.validation_calibration_n_min
    would_apply = (
        settings.validation_calibration_enabled
        and stats.n_validated >= n_min
    )
    demo_raw = 70.0
    demo = apply_calibration(demo_raw, stats.mean_delta, stats.n_validated, n_min)

    cols = st.columns(5)
    _metric(
        cols[0],
        "Validated (N)",
        stats.n_validated,
        help_text="How many validated predictions contribute to mean_delta.",
    )
    _metric(
        cols[1],
        "Mean delta",
        f"{stats.mean_delta:+.2f}",
        help_text="Average (actual − predicted) percentile. Applied as an offset when the gate opens.",
    )
    _metric(
        cols[2],
        "N_min gate",
        n_min,
        help_text="Cold-start threshold. Below this, calibration does nothing.",
    )
    _metric(
        cols[3],
        "Would apply?",
        "Yes" if would_apply else "No",
        help_text="Yes only if Calibration is ON and Validated (N) ≥ N_min.",
    )
    _metric(
        cols[4],
        "Example (raw 70)",
        f"{demo.calibrated_percentile:.1f}",
        help_text="If a new post's raw neighbor percentile were 70, this is what calibrated would be right now.",
        delta=(
            f"{demo.calibrated_percentile - demo_raw:+.1f}"
            if demo.applied
            else "unchanged"
        ),
    )

    if not settings.validation_calibration_enabled:
        st.info("Calibration is disabled — predictions use raw neighbor percentiles.")
    elif stats.n_validated < n_min:
        st.warning(
            f"Cold start: need **{n_min - stats.n_validated}** more validated rows "
            "before the global offset is applied."
        )
    else:
        direction = (
            "overestimates"
            if stats.mean_delta < 0
            else "underestimates"
            if stats.mean_delta > 0
            else "is unbiased on average"
        )
        st.success(
            f"Global bias: model typically **{direction}** by "
            f"**{abs(stats.mean_delta):.1f}** percentile points "
            f"(formula: `calibrated = clamp(raw + mean_delta, 0, 100)`)."
        )
    return stats


def render_coverage_panel(settings: Settings) -> dict[str, int]:
    """Validated vs feedback coverage metrics."""
    _section_header(
        "Feedback coverage",
        """
**This is not the 48-hour re-scrape.** The Queue / worker already pulled
actual engagement and computed deltas. This section only answers:

> Of those validated predictions, how many already have a **lesson row**
> stored for the AI?

- **Validated** — prediction finished the wait window; we know actual vs predicted  
- **With feedback** — a template lesson JSON exists (version v1)  
- **Missing** — validated but no lesson yet (use **Generate missing feedback**)

Lessons are enqueued when Feedback records is ON and validation succeeds;
run **Process feedback queue** (or the CLI worker) to write them. The
manual generate button below is for sync backfill / recovery.
""",
    )
    conn = get_connection(settings)
    try:
        create_schema(conn)
        coverage = count_feedback_coverage(conn, feedback_version=FEEDBACK_VERSION)
        hybrid_cost = hybrid_feedback_cost_stats(conn)
        backlog = count_feedback_queue_backlog(conn)
    finally:
        conn.close()

    cols = st.columns(3)
    _metric(
        cols[0],
        "Validated predictions",
        coverage["validated"],
        help_text="Predictions that already have actual engagement + a prediction_delta.",
    )
    _metric(
        cols[1],
        "With feedback (v1)",
        coverage["with_feedback"],
        help_text="Validated rows that have a stored template lesson (feedback version v1).",
    )
    _metric(
        cols[2],
        "Missing feedback",
        coverage["missing_feedback"],
        help_text="Validated but no lesson yet — backfill with Generate missing feedback.",
    )
    if coverage["missing_feedback"] > 0:
        st.caption(
            "Use **Generate missing feedback** below to backfill template lessons, "
            "or **Process feedback queue** if jobs are pending."
        )

    qcols = st.columns(4)
    _metric(
        qcols[0],
        "Queue pending",
        backlog.pending,
        help_text="feedback_jobs waiting for the async worker.",
    )
    _metric(
        qcols[1],
        "Queue processing",
        backlog.processing,
        help_text="Jobs currently claimed (or stuck mid-run).",
    )
    _metric(
        qcols[2],
        "Queue done",
        backlog.done,
        help_text="Successfully processed feedback jobs.",
    )
    _metric(
        qcols[3],
        "Queue dead",
        backlog.dead,
        help_text="Failed after max attempts — inspect last_error / regenerate one.",
    )
    if backlog.dead > 0:
        st.warning(
            f"{backlog.dead} feedback job(s) dead-lettered. "
            "Use Regenerate one or re-enqueue via a new validate."
        )

    cost_cols = st.columns(3)
    _metric(
        cost_cols[0],
        "Hybrid v2 rows",
        hybrid_cost["hybrid_rows"],
        help_text="LLM-enriched feedback rows (pending + approved + rejected).",
    )
    _metric(
        cost_cols[1],
        "Approved v2",
        hybrid_cost["approved_v2"],
        help_text="Human-approved hybrid lessons (staging DoD target: ≥10).",
    )
    _metric(
        cost_cols[2],
        "Cost / 100 hybrid",
        f"${hybrid_cost['cost_per_100_usd']:.4f}",
        help_text=(
            f"Estimated from stored tokens; total "
            f"${hybrid_cost['total_cost_usd']:.4f} across "
            f"{hybrid_cost['hybrid_rows']} hybrid rows."
        ),
    )
    return coverage


def render_clusters_table(settings: Settings, *, cluster_n_min: int) -> list[ClusterStats]:
    """Per-cluster sample counts and mean deltas."""
    _section_header(
        "Clusters",
        """
**What a cluster is:** a bucket of *similar-shaped* posts — not topics, not
embeddings (yet). Every post gets a stable id from three metadata axes:

1. **Length** — short / medium / long (word count)  
2. **Format** — prose / list / question  
3. **Follower band** — nano / micro / mid / macro / unknown  

Example: `short_list_micro` = short listicle from a micro-influencer.

**Why bother?**  
A short listicle from a nano account behaves differently from a long prose
post from a macro account. Clustering lets us:

- Apply a **cluster-specific** calibration offset once that bucket has enough samples  
- Inject only lessons from the **same bucket** into the next prediction (so the
  model isn't flooded with unrelated feedback)

**cluster calib = ready** means samples ≥ Cluster N_min and we have a mean_delta
for that bucket. Until then, global calibration (above) is used.
""",
    )
    conn = get_connection(settings)
    try:
        create_schema(conn)
        clusters = list_clusters(conn)
    finally:
        conn.close()

    if not clusters:
        st.info(
            "No clusters yet. Generate feedback for validated predictions "
            "(clusters are derived from content length × format × follower band)."
        )
        return []

    rows = []
    for c in clusters:
        eligible = c.sample_count >= cluster_n_min and c.mean_delta is not None
        rows.append(
            {
                "cluster_id": c.cluster_id,
                "label": c.label or "",
                "samples": c.sample_count,
                "mean_delta": round(c.mean_delta, 2) if c.mean_delta is not None else None,
                "std_delta": round(c.std_delta, 2) if c.std_delta is not None else None,
                "cluster calib": "ready" if eligible else f"need {cluster_n_min}",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "Hover the section **?** for a full explanation. "
        "`cluster calib = ready` → that bucket can drive its own offset + lesson retrieval."
    )
    return clusters


def render_recent_feedback_table(
    settings: Settings,
    *,
    limit: int = 40,
    cluster_id: Optional[str] = None,
) -> list[FeedbackRecord]:
    """Recent structured feedback lessons."""
    _section_header(
        "Recent feedback records",
        """
**What you're looking at:** compact, number-grounded lesson cards stored after
validation — not free-form AI essays.

**Honest limitation (v1):** templates mostly say *how far* the prediction was
off (and on which metrics), plus a short “bias toward higher/lower percentiles”
lesson. They do **not** yet diagnose deep causal “why” (e.g. “hook was weak”
or “topic was stale”). That would need an LLM pass; v1 stays template-only so
feedback stays factual and cheap.

**How the AI sees this without blowing the context window:**
1. New post is routed to a **cluster**  
2. We fetch only the latest **N** lessons from that cluster (Injection limit)  
3. Those are formatted into a short prompt block (~a few hundred tokens)  
4. Thousands of other rows stay in Postgres and are **not** sent to the model  

So sorting into clusters is exactly how we keep context small and relevant.
""",
    )
    conn = get_connection(settings)
    try:
        create_schema(conn)
        records = list_recent_feedback(
            conn, limit=limit, cluster_id=cluster_id, feedback_version=FEEDBACK_VERSION
        )
    finally:
        conn.close()

    if not records:
        st.info("No feedback records yet.")
        return []

    rows = []
    for r in records:
        d = r.feedback_json.delta_summary
        lessons = r.feedback_json.lessons_for_similar_posts
        missed = r.feedback_json.what_missed
        rows.append(
            {
                "generated_at": r.generated_at.strftime("%Y-%m-%d %H:%M")
                if r.generated_at
                else "",
                "cluster": r.cluster_id or "",
                "direction": d.direction,
                "pred %": round(d.predicted_percentile, 1),
                "actual %": round(d.actual_percentile, 1),
                "delta": round(d.prediction_delta, 1),
                "lesson": lessons[0] if lessons else "",
                "missed": missed[0] if missed else "",
                "method": r.generation_method,
                "review": r.feedback_review_status,
                "version": r.feedback_version,
                "latency ms": round(r.generation_latency_ms, 2),
                "cost USD": round(r.cost_usd, 6),
                "prediction_id": str(r.prediction_id),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    return records


def render_manual_actions(settings: Settings) -> None:
    """Buttons to run feedback batch, refresh clusters, regenerate one row."""
    _section_header(
        "Manual process",
        """
**Timing:** this runs **after** the ~48h (or dev-window) results are already in.

The Queue / worker:
1. Re-scrapes the post  
2. Computes actual percentile + deltas  
3. Optionally auto-writes a feedback lesson  

These buttons are for when auto-write missed something, or you want to
recompute cluster stats without waiting for the next validation.

| Button | Does |
|--------|------|
| **Process feedback queue** | Claim pending `feedback_jobs` and generate lessons (Phase I) |
| **Generate missing feedback** | Sync template lessons for validated rows that lack v1 feedback |
| **Refresh cluster stats** | Recompute sample_count / mean_delta / std_delta (+ roll-ups) |
| **Refresh roll-ups** | Rewrite `rollup_summary` text for injection formats |
| **Refresh centroids** | Mean embedding per metadata cluster (Phase H routing) |
| **Regenerate one** | Rebuild one lesson (e.g. after a template change) |
""",
    )
    st.caption(
        "Run these when you want to backfill or refresh without waiting for "
        "the next validation worker pass."
    )

    col_a, col_b = st.columns(2)

    with col_a:
        limit = st.number_input(
            "Backfill / queue limit",
            min_value=1,
            max_value=500,
            value=50,
            key="feedback_batch_limit",
            help="Max jobs or missing rows to process in one click.",
        )
        if st.button(
            "Process feedback queue",
            type="primary",
            disabled=not settings.validation_feedback_enabled,
            help=(
                "Same as: python -m feedback.jobs.run_feedback_worker. "
                "Validations enqueue jobs; this drains them."
            ),
        ):
            with st.spinner("Processing feedback queue..."):
                worker = run_feedback_worker(settings, limit=int(limit))
            st.session_state["feedback_last_worker"] = worker
            st.rerun()

        if st.button(
            "Generate missing feedback",
            disabled=not settings.validation_feedback_enabled,
            help=(
                "Template feedback for validated predictions that lack a v1 row. "
                "Disabled when Feedback records is OFF."
            ),
        ):
            with st.spinner("Generating template feedback..."):
                batch = run_feedback_batch(settings, limit=int(limit))
            st.session_state["feedback_last_batch"] = batch
            st.rerun()

        if st.button(
            "Refresh cluster stats",
            help="Recompute per-cluster mean_delta and sample counts from feedback rows.",
        ):
            with st.spinner("Recomputing cluster mean_delta / sample_count..."):
                conn = get_connection(settings)
                try:
                    create_schema(conn)
                    n = refresh_cluster_stats(conn)
                finally:
                    conn.close()
            st.session_state["feedback_clusters_refreshed"] = n
            st.rerun()

        if st.button(
            "Refresh roll-ups",
            help="Rewrite template rollup_summary on prediction_clusters.",
        ):
            with st.spinner("Writing cluster roll-up summaries..."):
                conn = get_connection(settings)
                try:
                    create_schema(conn)
                    n = refresh_cluster_rollups(conn)
                finally:
                    conn.close()
            st.session_state["feedback_rollups_refreshed"] = n
            st.rerun()

        if st.button(
            "Refresh cluster centroids",
            help="Average validated prediction embeddings per metadata cluster.",
        ):
            with st.spinner("Computing cluster centroids..."):
                n = refresh_cluster_centroids()
            st.session_state["feedback_centroids_refreshed"] = n
            st.rerun()

    with col_b:
        st.markdown("**Regenerate one prediction**")
        validated = []
        conn = get_connection(settings)
        try:
            create_schema(conn)
            validated = list_predictions(conn, status="validated", limit=100)
        finally:
            conn.close()

        options = {
            f"{p.linkedin_post_id}  ({p.prediction_delta:+.1f} Δ)"
            if p.prediction_delta is not None
            else p.linkedin_post_id: p.prediction_id
            for p in validated
        }
        if not options:
            st.info("No validated predictions to regenerate.")
        else:
            choice = st.selectbox(
                "Validated prediction",
                list(options.keys()),
                help="Pick a validated post whose lesson you want to rebuild.",
            )
            if st.button(
                "Regenerate feedback for selected",
                help="Overwrite that prediction's v1 feedback and refresh cluster stats.",
            ):
                pid = options[choice]
                try:
                    with st.spinner("Regenerating..."):
                        record = generate_feedback_for_prediction_id(pid, settings)
                        conn = get_connection(settings)
                        try:
                            create_schema(conn)
                            refresh_cluster_stats(conn)
                        finally:
                            conn.close()
                    st.session_state["feedback_last_regen"] = str(record.prediction_id)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    if "feedback_last_batch" in st.session_state:
        batch = st.session_state["feedback_last_batch"]
        st.success(
            f"Batch done: processed={batch.processed} · generated={batch.generated} · "
            f"failed={batch.failed} · skipped={batch.skipped}"
        )
    if "feedback_last_worker" in st.session_state:
        worker = st.session_state["feedback_last_worker"]
        st.success(
            f"Queue worker: claimed={worker.claimed} · succeeded={worker.succeeded} · "
            f"failed={worker.failed} · dead={worker.dead_lettered}"
        )
    if "feedback_clusters_refreshed" in st.session_state:
        st.success(
            f"Cluster stats refreshed for "
            f"{st.session_state['feedback_clusters_refreshed']} cluster(s)."
        )
    if "feedback_rollups_refreshed" in st.session_state:
        st.success(
            f"Roll-up summaries written for "
            f"{st.session_state['feedback_rollups_refreshed']} cluster(s)."
        )
    if "feedback_last_regen" in st.session_state:
        st.success(
            f"Regenerated feedback for prediction `{st.session_state['feedback_last_regen']}`."
        )


def render_feedback_detail_expander(records: list[FeedbackRecord]) -> None:
    """Expandable full JSON for a selected feedback row."""
    if not records:
        return
    _section_header(
        "Inspect feedback JSON",
        """
Open one stored lesson in full. Check `what_worked`, `what_missed`, and
`lessons_for_similar_posts`. In v1 these are **templates from numbers**, not
an LLM narrative — useful for verifying the closed loop is writing what you expect.
""",
    )
    labels = {
        f"{r.cluster_id or '—'} · {r.feedback_json.delta_summary.direction} · "
        f"{r.generated_at.strftime('%Y-%m-%d %H:%M') if r.generated_at else '?'}"
        : r
        for r in records
    }
    pick = st.selectbox(
        "Select record",
        list(labels.keys()),
        key="feedback_inspect",
        help="Choose a row from the recent feedback table to inspect.",
    )
    record = labels[pick]
    payload = record.feedback_json
    st.markdown(
        f"**Prediction** `{record.prediction_id}` · "
        f"**Cluster** `{record.cluster_id}` · "
        f"**Method** `{record.generation_method}`"
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**What worked**")
        for item in payload.what_worked or ["—"]:
            st.write(f"- {item}")
        st.markdown("**Lessons**")
        for item in payload.lessons_for_similar_posts or ["—"]:
            st.write(f"- {item}")
    with c2:
        st.markdown("**What missed**")
        for item in payload.what_missed or ["—"]:
            st.write(f"- {item}")
        d = payload.delta_summary
        st.markdown(
            f"**Delta summary:** predicted {d.predicted_percentile:.1f} → "
            f"actual {d.actual_percentile:.1f} "
            f"({d.prediction_delta:+.1f}, {d.direction})"
        )
    with st.expander("Raw JSON"):
        st.json(payload.model_dump(mode="json"))


def render_how_this_connects(settings: Settings) -> None:
    """Detailed end-to-end diagram + copy for the Feedback Loop tab."""
    _section_header(
        "How this connects",
        """
Full closed loop from scrape → wait → learn → next prediction.
Read the diagram below; use the numbered steps for detail.
""",
    )

    st.markdown(
        f"""
```
  ┌─────────────┐     ~{settings.validation_window_hours}h wait      ┌──────────────────┐
  │ 1. Collect  │ ───────────────────────────────▶ │ 2. Validate     │
  │ + Predict   │   (Queue / worker re-scrape)     │ actual vs pred  │
  └─────────────┘                                  └────────┬─────────┘
                                                            │
                         ┌──────────────────────────────────┼──────────────────────────┐
                         │                                  ▼                          │
                         │                    ┌─────────────────────────┐              │
                         │                    │ 3. Store feedback       │              │
                         │                    │ (template lesson +      │              │
                         │                    │  assign cluster id)     │              │
                         │                    └───────────┬─────────────┘              │
                         │                                │                            │
                         │              ┌─────────────────┴─────────────────┐          │
                         │              ▼                                   ▼          │
                         │   ┌────────────────────┐           ┌────────────────────┐   │
                         │   │ 4a. Calibration    │           │ 4b. Cluster stats  │   │
                         │   │ global / cluster   │           │ mean_delta, N      │   │
                         │   │ offset for NEXT    │           │                    │   │
                         │   │ predict            │           │                    │   │
                         │   └─────────┬──────────┘           └─────────┬──────────┘   │
                         │             │                                  │            │
                         │             └────────────────┬─────────────────┘            │
                         │                              ▼                              │
                         │                 ┌─────────────────────────┐                 │
                         │                 │ 5. Next prediction      │                 │
                         │                 │ • route to cluster      │                 │
                         │                 │ • inject ≤{settings.validation_feedback_injection_limit} lessons     │                 │
                         │                 │ • apply calibration     │                 │
                         │                 └─────────────────────────┘                 │
                         └─────────────────────────────────────────────────────────────┘
```

**Step by step**

1. **Collect + Predict** — scrape a post, score it (neighbor percentile + Predictor agent).  
2. **Validate (~{settings.validation_window_hours}h later)** — re-scrape engagement, compute deltas. *This* is where the “48h results” come from — not from Manual process.  
3. **Store feedback** — if Feedback records is ON, write a compact lesson JSON and assign a cluster (`length_format_followers`).  
4. **Learn silently** — update global / cluster `mean_delta` (Calibration). Refresh cluster sample counts.  
5. **Next predict** — route the new post to a cluster → pull only the latest **{settings.validation_feedback_injection_limit}** lessons from that cluster into the prompt → optionally add the calibration offset to the numeric percentile.

**Context window:** we never dump the whole feedback table. Clusters + Injection limit keep the prompt to a short comparative block.
"""
    )

    with st.expander("When would I turn a setting OFF?"):
        st.markdown(
            """
- **Calibration OFF** — measure raw model accuracy; or temporarily stop a bad offset while N is still small/noisy.  
- **Feedback records OFF** — stop writing new lessons (e.g. schema migration, debugging validation). Old rows remain.  
- **Prompt injection OFF** — test whether lesson *text* helps beyond the numeric offset alone (A/B).  

Day-to-day: keep feedback collection ON. Enable calibration or injection only
after the evaluation gates in the operations runbook pass.
"""
        )

def render_review_queue(settings: Settings, *, limit: int = 30) -> None:
    """Approve or reject pending hybrid (v2) feedback lessons."""
    _section_header(
        "Human review queue (v2)",
        """
LLM-enriched lessons start as **pending**. Only **approved** rows are eligible
for prompt injection. Reject ungrounded or unsafe text.

Prod injection remains OFF after Phase F; use this queue in staging to build
a trusted lesson set before reconsidering injection.
""",
    )
    conn = get_connection(settings)
    try:
        create_schema(conn)
        pending = list_pending_feedback_for_review(conn, limit=limit)
    finally:
        conn.close()

    if not pending:
        st.info("No pending hybrid feedback rows.")
        return

    st.caption(f"{len(pending)} pending row(s), highest |delta| first.")
    for record in pending:
        delta = record.feedback_json.delta_summary
        with st.expander(
            f"{record.cluster_id or 'unknown'} · "
            f"delta {delta.prediction_delta:+.1f} · {record.feedback_version} · "
            f"{record.generation_method}",
            expanded=False,
        ):
            st.markdown(
                f"**Predicted** {delta.predicted_percentile:.1f} → "
                f"**actual** {delta.actual_percentile:.1f} "
                f"({delta.direction})"
            )
            st.markdown("**What missed**")
            for item in record.feedback_json.what_missed or ["—"]:
                st.write(f"- {item}")
            st.markdown("**Lessons**")
            for item in record.feedback_json.lessons_for_similar_posts or ["—"]:
                st.write(f"- {item}")
            c1, c2, c3 = st.columns(3)
            if c1.button("Approve", key=f"approve_{record.feedback_id}"):
                conn = get_connection(settings)
                try:
                    create_schema(conn)
                    set_feedback_review_status(
                        conn, record.feedback_id, "approved", reviewed_by="dashboard"
                    )
                finally:
                    conn.close()
                st.rerun()
            if c2.button("Reject", key=f"reject_{record.feedback_id}"):
                conn = get_connection(settings)
                try:
                    create_schema(conn)
                    set_feedback_review_status(
                        conn, record.feedback_id, "rejected", reviewed_by="dashboard"
                    )
                finally:
                    conn.close()
                st.rerun()
            c3.caption(str(record.feedback_id))

