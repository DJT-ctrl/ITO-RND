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
    lesson_phase_stats,
    list_clusters,
    list_recent_feedback,
    list_template_hybrid_pairs,
)
from feedback.retrieve import (
    example_limit_for_format,
    fetch_cluster_feedback,
    format_feedback_context_block,
)
from feedback.routing import (
    assign_cluster_id,
    cluster_label,
    content_length_bucket,
    follower_bucket,
    format_bucket,
    metadata_cluster_id,
)
from feedback.store import (
    fetch_calibration_stats,
    fetch_cluster_centroids,
    list_pending_feedback_for_review,
    refresh_cluster_stats,
    resolve_calibration_stats,
    set_feedback_review_status,
)
from feedback.jobs.run_cluster_centroids import refresh_cluster_centroids
from feedback.summarize import fetch_cluster_rollup, refresh_cluster_rollups
from storage.vector_store import create_schema, get_connection
from validation_pipeline.store import list_predictions


from dashboard.chrome import render_phase_badges, section_header as _section_header

_DEMO_POST_PRESETS: dict[str, tuple[str, int]] = {
    "Short listicle (micro)": (
        "Three things that changed how I write on LinkedIn:\n"
        "- Lead with the outcome\n"
        "- Keep paragraphs short\n"
        "- End with one clear ask\n"
        "- Bonus: read it out loud once",
        4500,
    ),
    "Medium prose (mid)": (
        "I spent six months rebuilding our onboarding flow. What surprised me "
        "most was not the conversion lift — it was how much clarity the team "
        "gained once every step had a single owner and a measurable definition "
        "of done. Here is the process we used, what failed first, and what we "
        "kept. The short version: fewer screens, clearer copy, and ruthless "
        "instrumentation before the next redesign.",
        42000,
    ),
    "Question hook (nano)": (
        "What is the one habit that actually moved your content quality this year?",
        800,
    ),
}


def _metric(col, label: str, value, *, help_text: str, **kwargs) -> None:
    col.metric(label, value, help=help_text, **kwargs)


def render_feedback_settings_panel(settings: Settings) -> Settings:
    """Editable feature flags — persisted so worker/predict honor them too."""
    _section_header(
        "Learning switches",
        """
These switches control the three learning mechanisms. **They matter.**

| Switch (plain English) | Phase | When ON | When OFF |
|------|---------|---------|----------|
| **Adjust scores from past mistakes** | A | Next predictions get a numeric offset from past errors | Measure baseline without the nudge |
| **Save lessons after grading** | B | After each validation, store a template lesson | Pause writing new lessons |
| **Show lessons to the AI** | D | Predictor sees recent same-bucket lessons | A/B without lesson text |

Safe production default: **lessons ON**, **calibration and injection OFF**
until Phase F (offline eval) shows a clear lift.
Overrides save to `data/feedback_loop_overrides.json` and apply on the next
`load_settings()` call (Streamlit reload, worker, CLI).
""",
    )
    render_phase_badges(["A", "B", "D"])

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        cal_on = st.toggle(
            "Adjust scores from past mistakes",
            value=settings.validation_calibration_enabled,
            help=(
                "Phase A · Calibration. Adds mean prediction error "
                "(actual − predicted) to new percentile scores once enough "
                "graded rows exist. Turn OFF to measure baseline accuracy."
            ),
            key="fb_toggle_calibration",
        )
    with c2:
        fb_on = st.toggle(
            "Save lessons after grading",
            value=settings.validation_feedback_enabled,
            help=(
                "Phase B · Feedback records. After a prediction is graded "
                "(~48h later, or force-validate), write a structured lesson. "
                "Turn OFF to stop creating new lessons (existing ones stay)."
            ),
            key="fb_toggle_feedback",
        )
    with c3:
        inj_on = st.toggle(
            "Show lessons to the AI",
            value=settings.validation_feedback_injection_enabled,
            help=(
                "Phase D · Prompt injection. At predict time, inject a short "
                "block of recent same-bucket lessons into the Predictor prompt. "
                "Turn OFF for an A/B without lesson text."
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

    age_on = st.toggle(
        "Age-aware learning filter",
        value=settings.validation_age_aware_enabled,
        help=(
            "When ON, exclude forced_early validations (posts graded too soon "
            "after publish) from calibration averages and lesson learning / "
            "injection. Age and mode are still recorded on every validation. "
            "Default OFF — no change to current behavior."
        ),
        key="fb_toggle_age_aware",
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
                "validation_age_aware_enabled": bool(age_on),
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
        validation_age_aware_enabled=bool(age_on),
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
        stats = fetch_calibration_stats(
            conn,
            age_aware_enabled=settings.validation_age_aware_enabled,
        )
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
            "Use Rebuild lesson for one post, or re-enqueue via a new validate."
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


def render_learning_buckets_panel(
    settings: Settings,
    *,
    clusters: Optional[list[ClusterStats]] = None,
    cluster_n_min: Optional[int] = None,
) -> None:
    """Browse stored learning buckets and try live routing + injection preview."""
    n_min = (
        int(cluster_n_min)
        if cluster_n_min is not None
        else int(settings.validation_cluster_n_min)
    )
    _section_header(
        "Learning storage buckets",
        """
**What this is:** the Postgres registry of learning buckets (`prediction_clusters`)
plus the lessons stored under each id. These are **not** cloud object-storage
buckets — they are metadata clusters such as `short_list_micro`.

- **Bucket viewer** — inspect stored bucket stats + lessons  
- **Reactive routing demo** — paste a draft and see live routing / injection  
- **B · Template & G · Smarter** — compare Phase B template lessons vs Phase G
  hybrid LLM lessons (same prediction, side by side)
""",
    )
    render_phase_badges(["B", "C", "D", "G", "H"])

    if clusters is None:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            clusters = list_clusters(conn)
        finally:
            conn.close()

    viewer_tab, demo_tab, lessons_tab = st.tabs(
        [
            "Bucket viewer",
            "Reactive routing demo",
            "B · Template & G · Smarter",
        ]
    )
    with viewer_tab:
        _render_bucket_viewer(settings, clusters=clusters, cluster_n_min=n_min)
    with demo_tab:
        _render_bucket_routing_demo(settings, clusters=clusters, cluster_n_min=n_min)
    with lessons_tab:
        _render_template_vs_smarter_lessons(settings, clusters=clusters)


def _render_bucket_viewer(
    settings: Settings,
    *,
    clusters: list[ClusterStats],
    cluster_n_min: int,
) -> None:
    if not clusters:
        st.info(
            "No learning buckets stored yet. Validate posts and generate feedback "
            "(or refresh cluster stats) to populate `prediction_clusters`."
        )
        return

    by_id = {c.cluster_id: c for c in clusters}
    choices = [c.cluster_id for c in clusters]
    pick = st.selectbox(
        "Stored learning bucket",
        choices,
        format_func=lambda cid: (
            f"{cid} · {by_id[cid].sample_count} samples · "
            f"{cluster_label(cid)}"
        ),
        key="learning_bucket_pick",
        help="Pick a cluster_id from prediction_clusters to inspect stored lessons.",
    )
    cluster = by_id[pick]
    eligible = (
        cluster.sample_count >= cluster_n_min and cluster.mean_delta is not None
    )

    conn = get_connection(settings)
    try:
        create_schema(conn)
        rollup_summary, _, _ = fetch_cluster_rollup(conn, pick)
        lessons = fetch_cluster_feedback(
            conn,
            pick,
            limit=min(20, max(5, settings.validation_feedback_injection_limit)),
            approved_only=False,
            age_aware_enabled=settings.validation_age_aware_enabled,
        )
        centroids = fetch_cluster_centroids(conn)
        phase_stats = lesson_phase_stats(conn, cluster_id=pick)
    finally:
        conn.close()

    has_centroid = any(cid == pick for cid, _ in centroids)
    m1, m2, m3, m4, m5 = st.columns(5)
    _metric(
        m1,
        "Samples",
        cluster.sample_count,
        help_text="Feedback rows aggregated into this bucket's mean_delta.",
    )
    _metric(
        m2,
        "Mean delta",
        (
            f"{cluster.mean_delta:+.2f}"
            if cluster.mean_delta is not None
            else "—"
        ),
        help_text="Average (actual − predicted) for this bucket.",
    )
    _metric(
        m3,
        "Std delta",
        (
            f"{cluster.std_delta:.2f}"
            if cluster.std_delta is not None
            else "—"
        ),
        help_text="Spread of prediction deltas inside this bucket.",
    )
    _metric(
        m4,
        "Cluster calib",
        "ready" if eligible else f"need {cluster_n_min}",
        help_text="Ready when samples ≥ Cluster N_min and mean_delta exists.",
    )
    _metric(
        m5,
        "Centroid",
        "yes" if has_centroid else "no",
        help_text="Phase H nearest-centroid routing needs an embedding centroid.",
    )

    b1, b2, b3, b4 = st.columns(4)
    _metric(
        b1,
        "B · Template v1",
        phase_stats["template_v1"],
        help_text="Phase B number-grounded template lessons in this bucket.",
    )
    _metric(
        b2,
        "G · Hybrid v2",
        phase_stats["hybrid_v2"],
        help_text="Phase G LLM-enriched smarter lessons in this bucket.",
    )
    _metric(
        b3,
        "G pending",
        phase_stats["v2_pending"],
        help_text="Hybrid lessons waiting in the human review queue.",
    )
    _metric(
        b4,
        "G approved",
        phase_stats["v2_approved"],
        help_text="Hybrid lessons approved for injection eligibility.",
    )

    st.caption(f"Label: **{cluster.label or cluster_label(pick)}**")
    if rollup_summary:
        st.markdown("**Roll-up summary**")
        st.write(rollup_summary)
    else:
        st.caption(
            "No roll-up summary yet — use **Refresh roll-ups** under "
            "Write / refresh lessons."
        )

    if not lessons:
        st.info(f"No lessons stored in bucket `{pick}` yet.")
        return

    rows = []
    for r in lessons:
        d = r.feedback_json.delta_summary
        lesson = (
            r.feedback_json.lessons_for_similar_posts[0]
            if r.feedback_json.lessons_for_similar_posts
            else ""
        )
        rows.append(
            {
                "generated_at": r.generated_at.strftime("%Y-%m-%d %H:%M")
                if r.generated_at
                else "",
                "direction": d.direction,
                "delta": round(d.prediction_delta, 1),
                "lesson": lesson,
                "review": r.feedback_review_status,
                "version": r.feedback_version,
                "method": r.generation_method,
            }
        )
    st.markdown(f"**Stored lessons** ({len(lessons)})")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    preview = format_feedback_context_block(
        [
            r
            for r in lessons
            if r.feedback_review_status == "approved"
        ][: settings.validation_feedback_injection_limit]
        or lessons[: settings.validation_feedback_injection_limit],
        cluster_id=pick,
        injection_format=settings.validation_feedback_injection_format,
        rollup_summary=rollup_summary,
        mean_delta=cluster.mean_delta,
        sample_count=cluster.sample_count,
    )
    with st.expander("Injection preview for this bucket", expanded=False):
        if preview:
            st.code(preview, language="markdown")
        else:
            st.caption("Nothing to inject for the current format / approved filter.")


def _render_lesson_card(record: FeedbackRecord, *, title: str) -> None:
    """Compact lesson body for B vs G side-by-side compare."""
    payload = record.feedback_json
    delta = payload.delta_summary
    st.markdown(f"**{title}**")
    st.caption(
        f"`{record.feedback_version}` · `{record.generation_method}` · "
        f"review `{record.feedback_review_status}` · "
        f"delta {delta.prediction_delta:+.1f} ({delta.direction})"
    )
    if record.cost_usd or record.input_tokens or record.output_tokens:
        st.caption(
            f"Tokens in/out {record.input_tokens}/{record.output_tokens} · "
            f"${record.cost_usd:.6f}"
        )
    st.markdown("**What missed**")
    for item in payload.what_missed or ["—"]:
        st.write(f"- {item}")
    st.markdown("**Lessons**")
    for item in payload.lessons_for_similar_posts or ["—"]:
        st.write(f"- {item}")
    if payload.what_worked:
        st.markdown("**What worked**")
        for item in payload.what_worked:
            st.write(f"- {item}")


def _render_template_vs_smarter_lessons(
    settings: Settings,
    *,
    clusters: list[ClusterStats],
) -> None:
    """Related area: Phase B template lessons vs Phase G hybrid smarter lessons."""
    render_phase_badges(["B", "G", "G+"])
    st.markdown(
        """
**Phase B — template lessons (v1):** after grading, write a short number-grounded
lesson from deltas only (no LLM). Cheap, factual, auto-approved.

**Phase G — smarter lessons (v2):** for large misses, enrich `what_missed` /
`lessons_for_similar_posts` with Gemini. New rows stay **pending** until human
review (or G+ auto-approve). Retrieve prefers approved v2 over v1 for the same post.
"""
    )

    s1, s2, s3, s4 = st.columns(4)
    _metric(
        s1,
        "Save lessons (B)",
        "ON" if settings.validation_feedback_enabled else "OFF",
        help_text="Phase B switch — write template lessons after validation.",
    )
    _metric(
        s2,
        "LLM hybrid (G)",
        "ON" if settings.validation_feedback_llm_enabled else "OFF",
        help_text="Phase G switch — enrich large misses with LLM (staging).",
    )
    _metric(
        s3,
        "G |delta| min",
        f"{settings.validation_feedback_llm_delta_min:.0f}",
        help_text="Only call hybrid when absolute prediction delta meets this.",
    )
    _metric(
        s4,
        "Auto-approve (G+)",
        "ON" if settings.validation_feedback_auto_approve_enabled else "OFF",
        help_text="Optionally skip the queue for grounded hybrid rows under the cap.",
    )

    scope_choices = ["All buckets"] + [c.cluster_id for c in clusters]
    scope = st.selectbox(
        "Scope (optional bucket filter)",
        scope_choices,
        key="bg_lessons_scope",
        help="Limit B/G stats and pairs to one learning bucket, or show everything.",
    )
    cluster_filter = None if scope == "All buckets" else scope

    conn = get_connection(settings)
    try:
        create_schema(conn)
        stats = lesson_phase_stats(conn, cluster_id=cluster_filter)
        cost = hybrid_feedback_cost_stats(conn)
        pairs = list_template_hybrid_pairs(
            conn, cluster_id=cluster_filter, limit=40
        )
        recent_b = list_recent_feedback(
            conn,
            limit=12,
            cluster_id=cluster_filter,
            feedback_version="v1",
        )
        recent_g = list_recent_feedback(
            conn,
            limit=12,
            cluster_id=cluster_filter,
            feedback_version="v2",
        )
        pending = list_pending_feedback_for_review(conn, limit=8)
    finally:
        conn.close()

    if cluster_filter and pending:
        pending = [r for r in pending if r.cluster_id == cluster_filter]

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    _metric(
        c1,
        "B · v1 rows",
        stats["template_v1"],
        help_text="Template lessons stored (Phase B).",
    )
    _metric(
        c2,
        "G · v2 rows",
        stats["hybrid_v2"],
        help_text="Hybrid/LLM smarter lessons stored (Phase G).",
    )
    _metric(
        c3,
        "G pending",
        stats["v2_pending"],
        help_text="Awaiting approve/reject in the human review queue.",
    )
    _metric(
        c4,
        "G approved",
        stats["v2_approved"],
        help_text="Staging DoD target is ≥10 approved v2 overall.",
    )
    _metric(
        c5,
        "B+G pairs",
        stats["paired"],
        help_text="Predictions that have both a v1 template and a v2 hybrid row.",
    )
    _metric(
        c6,
        "Cost / 100 G",
        f"${cost['cost_per_100_usd']:.4f}",
        help_text="Estimated hybrid cost per 100 v2 rows from stored tokens.",
    )

    if not settings.validation_feedback_enabled:
        st.warning("Save lessons is OFF — no new Phase B templates will be written.")
    elif not settings.validation_feedback_llm_enabled:
        st.info(
            "LLM hybrid is OFF — only Phase B templates are created. "
            "Turn **LLM hybrid (v2)** on in Learning switches (keep injection OFF in staging)."
        )
    elif stats["v2_approved"] < 10:
        st.info(
            f"Approved smarter lessons: **{stats['v2_approved']}** / 10 staging target. "
            "Review pending rows in **Human review queue** (section 3)."
        )
    else:
        st.success(
            f"Staging target met: **{stats['v2_approved']}** approved Phase G lessons."
        )

    compare_tab, recent_tab, queue_tab = st.tabs(
        ["Side-by-side B vs G", "Recent B / Recent G", "Pending G queue peek"]
    )

    with compare_tab:
        if not pairs:
            st.info(
                "No predictions yet have both a template (v1) and a hybrid (v2) row. "
                "Enable LLM hybrid, process the feedback queue on large misses, then "
                "return here to compare."
            )
        else:
            labels = {
                f"{t.cluster_id or '—'} · Δ"
                f"{t.feedback_json.delta_summary.prediction_delta:+.1f} · "
                f"G {h.feedback_review_status} · `{t.prediction_id}`": (t, h)
                for t, h in pairs
            }
            pick = st.selectbox(
                "Prediction with both lessons",
                list(labels.keys()),
                key="bg_pair_pick",
                help="Same graded post: left = Phase B template, right = Phase G smarter.",
            )
            template, hybrid = labels[pick]
            left, right = st.columns(2)
            with left:
                _render_lesson_card(template, title="B · Template lesson")
            with right:
                _render_lesson_card(hybrid, title="G · Smarter lesson")

    with recent_tab:
        left, right = st.columns(2)
        with left:
            st.markdown("**Recent Phase B (v1)**")
            if not recent_b:
                st.caption("No template lessons in this scope.")
            else:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "cluster": r.cluster_id or "",
                                "delta": round(
                                    r.feedback_json.delta_summary.prediction_delta, 1
                                ),
                                "lesson": (
                                    r.feedback_json.lessons_for_similar_posts[0]
                                    if r.feedback_json.lessons_for_similar_posts
                                    else ""
                                ),
                                "method": r.generation_method,
                            }
                            for r in recent_b
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
        with right:
            st.markdown("**Recent Phase G (v2)**")
            if not recent_g:
                st.caption("No hybrid lessons in this scope.")
            else:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "cluster": r.cluster_id or "",
                                "delta": round(
                                    r.feedback_json.delta_summary.prediction_delta, 1
                                ),
                                "lesson": (
                                    r.feedback_json.lessons_for_similar_posts[0]
                                    if r.feedback_json.lessons_for_similar_posts
                                    else ""
                                ),
                                "review": r.feedback_review_status,
                                "cost": round(r.cost_usd, 6),
                            }
                            for r in recent_g
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

    with queue_tab:
        if not pending:
            st.info("No pending Phase G rows in this scope.")
        else:
            st.caption(
                f"{len(pending)} pending smarter lesson(s). "
                "Approve/reject in **§3 Human review queue**."
            )
            for record in pending:
                delta = record.feedback_json.delta_summary
                with st.expander(
                    f"{record.cluster_id or 'unknown'} · "
                    f"Δ{delta.prediction_delta:+.1f} · {record.generation_method}",
                    expanded=False,
                ):
                    _render_lesson_card(record, title="Pending G lesson")


def _render_bucket_routing_demo(
    settings: Settings,
    *,
    clusters: list[ClusterStats],
    cluster_n_min: int,
) -> None:
    st.markdown(
        "Type or pick a sample post. Routing, stored-bucket match, lessons, and "
        "the prompt block update on every change — same path as predict-time "
        "injection (metadata axes; centroids only when an embedding exists)."
    )

    preset_names = ["Custom draft"] + list(_DEMO_POST_PRESETS.keys())
    preset = st.selectbox(
        "Sample draft",
        preset_names,
        key="bucket_demo_preset",
        help="Pick a canned example or Custom draft to type your own.",
    )
    default_content = ""
    default_followers = 5000
    if preset in _DEMO_POST_PRESETS:
        default_content, default_followers = _DEMO_POST_PRESETS[preset]

    # Keep textarea in sync when the preset changes.
    preset_key = f"bucket_demo_preset_applied"
    if st.session_state.get(preset_key) != preset:
        st.session_state["bucket_demo_content"] = default_content
        st.session_state["bucket_demo_followers"] = int(default_followers)
        st.session_state[preset_key] = preset

    content = st.text_area(
        "Draft post content",
        height=160,
        key="bucket_demo_content",
        help="Word count, list markers, and early ? drive length / format axes.",
    )
    followers = st.number_input(
        "Follower count",
        min_value=0,
        max_value=10_000_000,
        step=100,
        key="bucket_demo_followers",
        help="Maps to nano / micro / mid / macro / unknown.",
    )
    follower_arg = int(followers) if int(followers) > 0 else None

    length = content_length_bucket(content)
    fmt = format_bucket(content)
    followers_band = follower_bucket(follower_arg)
    metadata_id = metadata_cluster_id(content, follower_arg)
    routed_id = assign_cluster_id(content, follower_arg)

    by_id = {c.cluster_id: c for c in clusters}
    stored = by_id.get(routed_id)

    a1, a2, a3, a4 = st.columns(4)
    _metric(a1, "Length", length, help_text="short <50 · medium <150 · long otherwise")
    _metric(a2, "Format", fmt, help_text="list / question / prose from draft shape")
    _metric(
        a3,
        "Followers",
        followers_band,
        help_text="nano / micro / mid / macro / unknown",
    )
    _metric(
        a4,
        "Routed bucket",
        routed_id or "—",
        help_text="assign_cluster_id result (metadata; centroids need embeddings).",
    )

    if not content.strip():
        st.info("Enter draft content to see live routing and lesson retrieval.")
        return

    if routed_id != metadata_id:
        st.caption(
            f"Metadata id `{metadata_id}` overridden by centroid routing → `{routed_id}`."
        )
    else:
        st.caption(f"Metadata routing: `{metadata_id}` · {cluster_label(metadata_id)}")

    conn = get_connection(settings)
    try:
        create_schema(conn)
        records = fetch_cluster_feedback(
            conn,
            routed_id,
            limit=example_limit_for_format(
                settings.validation_feedback_injection_format,
                settings.validation_feedback_injection_limit,
            ),
            approved_only=True,
            age_aware_enabled=settings.validation_age_aware_enabled,
        )
        rollup_summary, mean_delta, sample_count = fetch_cluster_rollup(
            conn, routed_id
        )
        calib = resolve_calibration_stats(
            conn,
            cluster_id=routed_id,
            cluster_n_min=cluster_n_min,
            age_aware_enabled=settings.validation_age_aware_enabled,
        )
    finally:
        conn.close()

    in_storage = stored is not None
    cluster_ready = bool(
        stored
        and stored.sample_count >= cluster_n_min
        and stored.mean_delta is not None
    )
    b1, b2, b3, b4 = st.columns(4)
    _metric(
        b1,
        "In storage?",
        "Yes" if in_storage else "No",
        help_text="Whether prediction_clusters already has this cluster_id.",
    )
    _metric(
        b2,
        "Bucket samples",
        stored.sample_count if stored else 0,
        help_text="sample_count from prediction_clusters (0 if missing).",
    )
    _metric(
        b3,
        "Approved lessons",
        len(records),
        help_text="Lessons fetch_cluster_feedback would return right now.",
    )
    _metric(
        b4,
        "Calib source",
        calib.source,
        help_text="cluster / global / none — same resolver as predict.",
    )

    if not in_storage:
        st.warning(
            f"Bucket `{routed_id}` is not in storage yet. Lessons can still appear "
            "once feedback rows exist for that id; refresh cluster stats after grading."
        )
    elif cluster_ready:
        st.success(
            f"Cluster calibration **ready** for `{routed_id}` "
            f"(N={stored.sample_count}, mean_delta="
            f"{stored.mean_delta:+.2f})."
        )
    else:
        need = max(0, cluster_n_min - (stored.sample_count if stored else 0))
        st.info(
            f"Bucket exists but cluster calib needs **{need}** more sample(s) "
            f"(N_min={cluster_n_min}). Predict would fall back to "
            f"**{calib.source}** calibration."
        )

    injection_on = settings.validation_feedback_injection_enabled
    block = format_feedback_context_block(
        records,
        cluster_id=routed_id,
        injection_format=settings.validation_feedback_injection_format,
        rollup_summary=rollup_summary,
        mean_delta=mean_delta if mean_delta is not None else (
            stored.mean_delta if stored else None
        ),
        sample_count=sample_count or (stored.sample_count if stored else 0),
    )

    st.markdown("**What the predictor would see**")
    if not injection_on:
        st.caption(
            "Show lessons to the AI is **OFF** — predict would skip injection. "
            "Preview below still shows the block that would be built if it were ON."
        )
    if block:
        st.code(block, language="markdown")
    else:
        st.info(
            "No approved lessons (and no roll-up) for this bucket under current "
            "settings — injection block would be empty."
        )

    if records:
        with st.expander("Fetched lesson rows", expanded=False):
            rows = [
                {
                    "direction": r.feedback_json.delta_summary.direction,
                    "delta": round(
                        r.feedback_json.delta_summary.prediction_delta, 1
                    ),
                    "lesson": (
                        r.feedback_json.lessons_for_similar_posts[0]
                        if r.feedback_json.lessons_for_similar_posts
                        else ""
                    ),
                    "version": r.feedback_version,
                    "review": r.feedback_review_status,
                }
                for r in records
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


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
        "Write lessons & refresh buckets",
        """
**What this is:** turn graded predictions into stored lessons and update
learning buckets (`prediction_feedback` / `prediction_clusters`).

**What this is not:** Collect and predict, Validation queue, or offline eval.
Storing a lesson does **not** feed the predictor until **Show lessons to the AI**
(and/or **Adjust scores…**) is ON.

**Usual path:** Validation queue grades → job lands in `feedback_jobs` →
**Process feedback queue** writes the lesson into a bucket.

| Button | Does |
|--------|------|
| **Process feedback queue** | Drain pending jobs → write lessons into buckets |
| **Generate missing feedback** | Backfill validated rows that still lack a v1 lesson |
| **Refresh cluster stats** | Recompute sample_count / mean_delta / std_delta |
| **Refresh roll-ups** | Rewrite bucket summary text used for injection |
| **Refresh centroids** | Mean embedding per bucket (routing) |
| **Rebuild lesson for one post** | Overwrite that post’s stored lesson (not a re-grade) |
""",
    )
    st.caption(
        "Use when the queue has pending jobs, coverage shows Missing feedback, "
        "or you changed a template and need one lesson rewritten."
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
                "Drain pending feedback_jobs and write lessons into learning "
                "buckets. Same as: python -m feedback.jobs.run_feedback_worker."
            ),
        ):
            with st.spinner("Writing lessons from the feedback queue..."):
                worker = run_feedback_worker(settings, limit=int(limit))
            st.session_state["feedback_last_worker"] = worker
            st.rerun()

        if st.button(
            "Generate missing feedback",
            disabled=not settings.validation_feedback_enabled,
            help=(
                "Backfill: write template lessons for validated predictions "
                "that still lack a v1 row. Needs Save lessons after grading ON."
            ),
        ):
            with st.spinner("Generating template feedback..."):
                batch = run_feedback_batch(settings, limit=int(limit))
            st.session_state["feedback_last_batch"] = batch
            st.rerun()

        if st.button(
            "Refresh cluster stats",
            help="Recompute per-bucket sample counts and mean/std delta from lessons.",
        ):
            with st.spinner("Recomputing cluster mean_delta / sample_count..."):
                conn = get_connection(settings)
                try:
                    create_schema(conn)
                    n = refresh_cluster_stats(
                        conn,
                        age_aware_enabled=settings.validation_age_aware_enabled,
                    )
                finally:
                    conn.close()
            st.session_state["feedback_clusters_refreshed"] = n
            st.rerun()

        if st.button(
            "Refresh roll-ups",
            help="Rewrite bucket rollup_summary text used when injecting lessons.",
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
            help="Average validated prediction embeddings per learning bucket.",
        ):
            with st.spinner("Computing cluster centroids..."):
                n = refresh_cluster_centroids()
            st.session_state["feedback_centroids_refreshed"] = n
            st.rerun()

    with col_b:
        st.markdown("**Rebuild lesson for one post**")
        st.caption(
            "Does **not** re-scrape or re-grade. Overwrites that post’s stored "
            "lesson JSON (and refreshes bucket stats). Use after a template "
            "change, or to recover a bad/missing lesson."
        )
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
            st.info("No validated predictions to rebuild a lesson for.")
        else:
            choice = st.selectbox(
                "Validated prediction",
                list(options.keys()),
                help="Pick a graded post whose stored lesson you want to overwrite.",
            )
            if st.button(
                "Rebuild lesson for selected",
                help=(
                    "Overwrite that prediction’s feedback row and refresh "
                    "cluster stats. Does not change the graded actuals."
                ),
            ):
                pid = options[choice]
                try:
                    with st.spinner("Rebuilding lesson..."):
                        record = generate_feedback_for_prediction_id(pid, settings)
                        conn = get_connection(settings)
                        try:
                            create_schema(conn)
                            refresh_cluster_stats(
                                conn,
                                age_aware_enabled=settings.validation_age_aware_enabled,
                            )
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
    from feedback.understand_ui import render_full_written_feedback

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
    render_full_written_feedback(labels[pick])


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
2. **Validate (~{settings.validation_window_hours}h later)** — re-scrape engagement, compute deltas. *This* is where the “48h results” come from — not from Write / refresh lessons.  
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

