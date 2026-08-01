"""Understand-learning tab: how feedback works, full lessons, buckets explorer."""

from __future__ import annotations

import streamlit as st

from config.settings import Settings
from dashboard.chrome import render_phase_badges, section_header as _section_header
from feedback.dashboard_queries import list_recent_feedback
from feedback.observability_ui import render_cluster_accuracy
from feedback.schemas import FeedbackRecord
from feedback.ui import (
    render_clusters_table,
    render_how_this_connects,
    render_learning_buckets_panel,
)
from storage.vector_store import create_schema, get_connection


def render_full_written_feedback(record: FeedbackRecord) -> None:
    """Show the complete stored lesson write-up (not just a table row)."""
    payload = record.feedback_json
    delta = payload.delta_summary
    phase = (
        "G · Smarter (LLM)"
        if record.feedback_version == "v2"
        or record.generation_method in {"hybrid", "llm"}
        else "B · Template"
    )
    st.markdown(
        f"**{phase}** · bucket `{record.cluster_id or '—'}` · "
        f"`{record.feedback_version}` / `{record.generation_method}` · "
        f"review `{record.feedback_review_status}`"
    )
    st.caption(f"Prediction `{record.prediction_id}`")
    st.info(
        f"**Score story:** predicted **{delta.predicted_percentile:.1f}** → "
        f"actual **{delta.actual_percentile:.1f}** "
        f"(delta **{delta.prediction_delta:+.1f}**, {delta.direction})"
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### What worked")
        for item in payload.what_worked or ["—"]:
            st.write(f"- {item}")
    with c2:
        st.markdown("### What missed")
        for item in payload.what_missed or ["—"]:
            st.write(f"- {item}")
    with c3:
        st.markdown("### Lessons for similar posts")
        for item in payload.lessons_for_similar_posts or ["—"]:
            st.write(f"- {item}")

    with st.expander("Raw stored JSON", expanded=False):
        st.json(payload.model_dump(mode="json"))


def render_full_written_feedback_panel(settings: Settings) -> None:
    """Clear showcase: yes, full written lessons exist — pick one and read it."""
    _section_header(
        "Full written feedback",
        """
**Yes — written lessons exist.** Each graded prediction can store a structured
write-up in Postgres (`prediction_feedback`), not just a number.

Fields:
- `what_worked` / `what_missed` / `lessons_for_similar_posts`
- plus a delta summary (predicted → actual)

**Honest limit:** these are short structured cards, not long essays.
- **B (v1)** = template sentences from the numbers  
- **G (v2)** = same shape, with LLM “why” text after human approve
""",
    )
    render_phase_badges(["B", "G"])

    version_pick = st.radio(
        "Show",
        ["All versions", "B · Template (v1)", "G · Smarter (v2)"],
        horizontal=True,
        key="full_feedback_version",
    )
    version = None
    if version_pick.startswith("B"):
        version = "v1"
    elif version_pick.startswith("G"):
        version = "v2"

    conn = get_connection(settings)
    try:
        create_schema(conn)
        records = list_recent_feedback(
            conn, limit=40, feedback_version=version
        )
    finally:
        conn.close()

    if not records:
        st.info(
            "No written feedback rows yet. Validate posts, then process the "
            "feedback queue on the **Operate** tab."
        )
        return

    labels = {
        f"{r.cluster_id or '—'} · {r.feedback_version} · "
        f"{r.feedback_json.delta_summary.direction} "
        f"{r.feedback_json.delta_summary.prediction_delta:+.1f} · "
        f"{r.generated_at.strftime('%Y-%m-%d %H:%M') if r.generated_at else '?'}"
        : r
        for r in records
    }
    pick = st.selectbox(
        "Open a full lesson",
        list(labels.keys()),
        key="full_written_feedback_pick",
        help="This is the complete stored write-up the system keeps for learning.",
    )
    render_full_written_feedback(labels[pick])


def render_learning_how_it_works(settings: Settings) -> None:
    """Plain-English answers for how feedback, similarity, and buckets work."""
    _section_header(
        "How learning works (short answers)",
        """
Quick map of the closed loop. Bucket and cluster mean the same thing here.
""",
    )
    render_phase_badges(["0", "B", "C", "D", "G", "H"])

    st.markdown(
        f"""
| Question | Short answer |
|----------|--------------|
| **How does feedback happen?** | Predict → wait ~{settings.validation_window_hours}h → **validate** (real engagement) → write a **lesson** → file it in a **bucket** → optionally **show** it on the next predict / **nudge** the score. |
| **Does similarity come from vectors?** | **Two different jobs.** Neighbor scoring (how we predict) uses **embedding vectors**. Learning **buckets** mostly use **metadata** (length × format × followers). Phase **H** can also route by **centroid vectors**. Inside a bucket, lessons can be ranked by embedding distance when available. |
| **Bucket vs cluster?** | **Same thing.** UI says *bucket*; code/DB uses `cluster_id` / `prediction_clusters`. Example: `short_list_micro`. |
| **Full written feedback?** | **Yes.** Stored as structured text fields on each lesson row. Open **Full written feedback** below — not a novel, but a complete card (`what worked` / `what missed` / `lessons`). |
"""
    )

    with st.expander("Step-by-step feedback path", expanded=True):
        st.markdown(
            f"""
1. **Collect + Predict** — score a post (neighbors from the corpus use **vectors**).  
2. **Validate** (~{settings.validation_window_hours}h) — re-scrape actual likes/comments; compute delta.  
3. **Write lesson (B)** — template from numbers → `prediction_feedback` v1.  
4. **Maybe smarter lesson (G)** — if miss is large and LLM hybrid is ON → v2 pending review.  
5. **File in bucket (C)** — `length_format_followers` (or nearest centroid if H has embeddings).  
6. **Next predict (D)** — pull a few **same-bucket** lessons into the prompt (if injection ON).  
7. **Calibration (A)** — optional numeric nudge from average error (if calibration ON + enough N).
"""
        )

    with st.expander("Routing detail (bucket / cluster)", expanded=False):
        st.markdown(
            """
```
draft post
   ├─ word count     → short | medium | long
   ├─ shape          → list | question | prose
   └─ follower band  → nano | micro | mid | macro | unknown
            ↓
   metadata cluster_id  e.g. short_list_micro
            ↓
   optional Phase H: if we have an embedding + cluster centroids,
   route to nearest centroid instead
            ↓
   fetch lessons WHERE cluster_id = that bucket
```

So: **bucket = cluster**. Filing and retrieval both key off that id.
"""
        )


def render_understand_learning_tab(settings: Settings) -> None:
    """Explore-and-explain tab: how learning works, full lessons, buckets, B vs G."""
    _section_header(
        "Understand the learning process",
        """
This tab is the **explainer + explorer**. Use **Operate** for switches and jobs.
Here: how feedback works, what a full lesson looks like, and live bucket / B·G tools.
""",
    )

    render_learning_how_it_works(settings)

    st.divider()
    render_full_written_feedback_panel(settings)

    st.divider()
    clusters = render_clusters_table(
        settings, cluster_n_min=settings.validation_cluster_n_min
    )

    st.divider()
    render_learning_buckets_panel(
        settings,
        clusters=clusters,
        cluster_n_min=settings.validation_cluster_n_min,
    )

    st.divider()
    render_cluster_accuracy(settings)

    st.divider()
    render_how_this_connects(settings)
