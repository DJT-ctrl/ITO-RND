"""Throwaway visual test harness for Step 5 — Evaluation Cycle (T3.1-T3.4).

Exercises the exact same code path as the FastAPI endpoint
(POST /api/v1/evaluate in api/main.py) directly — run_evaluation_cycle()
(agents/orchestrator.py) which calls embed_query() + find_similar() to
populate similar_posts, then runs any registered Predictor/Diagnostic agents
concurrently via asyncio.gather(), then the T3.4 Variant Optimisation Engine
as the sequential finalize hook.

What this visualises:
  - The full 3-stage pipeline: sequential neighbor-fetch, concurrent
    evaluation (Predictor + Diagnostics), sequential finalize (Variants).
    - T3.2 Predictor output: estimated engagement percentile, raw engagement
        count, and comparative reasoning against nearest historical posts.
    - T3.3 Diagnostic outputs: SEO, clarity, and tone/brand-persona checks.
    - T3.4 Variant output: exactly 3 ranked, rewritten post alternatives with
        recalculated predicted percentiles (strategy selectable in sidebar).

Not the product UI — exists purely to validate the Phase 3 pipeline the same
way earlier pages validate their pipeline stages.
"""

import asyncio
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from agents.diagnostics import build_diagnostic_agents  # noqa: E402
from agents.orchestrator import run_evaluation_cycle  # noqa: E402
from agents.predictor import build_predictor_agent  # noqa: E402
from agents.variant_engine import build_variant_engine  # noqa: E402
from config.settings import load_settings  # noqa: E402

_STRATEGY_LABELS = {
    "Dimension-focused (SEO / Clarity / Tone)": "dimension",
    "Narrative angles (hook / educational / story)": "narrative",
    "Tiered risk (safe / moderate / bold)": "tiered",
}


def _render_list(title: str, items: list[str]) -> None:
    st.markdown(f"**{title}**")
    if not items:
        st.caption("None returned.")
        return
    for item in items:
        st.markdown(f"- {item}")

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Evaluation Cycle Test Harness", layout="wide")
st.title("Step 5: Evaluation Cycle (T3.1-T3.4)")
st.caption(
    "Throwaway visual tool for the Phase 3 async evaluation cycle. Calls the "
    "real Gemini embedding endpoint + Postgres DB to fetch neighbors, runs the "
    "Gemini-backed Predictor and Diagnostic agents concurrently, then the T3.4 "
    "Variant Optimisation Engine as a sequential finalize stage."
)

settings = load_settings()
predictor_agent = build_predictor_agent()
diagnostic_agents = build_diagnostic_agents()

if "eval_result" not in st.session_state:
    st.session_state.eval_result = None

missing_config = []
if not settings.gemini_api_key:
    missing_config.append("GEMINI_API_KEY")
if not settings.database_url:
    missing_config.append("DATABASE_URL")

with st.sidebar:
    st.header("Draft Post")
    draft_content = st.text_area(
        "Your draft post content",
        value="Excited to announce our new product launch! We've been working on this for months.",
        height=160,
        help="The draft LinkedIn post you want evaluated. The system will find "
        "similar historical posts, predict engagement, and run SEO/clarity/tone diagnostics.",
    )
    strategy_choice = st.selectbox(
        "Variant strategy (T3.4)",
        options=list(_STRATEGY_LABELS.keys()),
        help="Which distinctness axis the Variant Optimisation Engine should use "
        "when rewriting the draft into 3 alternatives.",
    )
    variant_strategy = _STRATEGY_LABELS[strategy_choice]
    reembed_neighbors = st.checkbox(
        "Re-embed each variant's own neighbors",
        value=False,
        help="Off (default): all 3 variants are scored against the ORIGINAL draft's shared "
        "neighbors — cheap, and keeps all 3 compared against one consistent baseline. "
        "On: each variant re-embeds its own text and fetches its OWN nearest neighbors before "
        "scoring — more accurate if a variant shifts topic/angle, but costs up to 3 extra "
        "Gemini embed calls + DB queries.",
    )
    run_clicked = st.button(
        "\u25b6 Run evaluation cycle",
        type="primary",
        disabled=bool(missing_config) or not draft_content.strip(),
    )
    if missing_config:
        st.caption(f"\u26a0\ufe0f Missing config: {', '.join(missing_config)} — check your .env file.")

# ── Run ────────────────────────────────────────────────────────────────────────

status = st.empty()

if run_clicked:
    with status:
        st.info("Running evaluation cycle (neighbor-fetch + concurrent agents + variant finalize stage)...")
    try:
        # Building the hook is pure Python (no I/O until awaited inside the
        # cycle), so it's cheap to construct fresh per run with whichever
        # strategy/neighbor-mode is selected in the sidebar.
        variant_hook = build_variant_engine(
            predictor_agent,
            strategy=variant_strategy,
            reembed_neighbors=reembed_neighbors,
            settings=settings,
        )
        # run_evaluation_cycle is async, need to call it via asyncio.run
        state = asyncio.run(
            run_evaluation_cycle(
                draft_content.strip(),
                settings,
                predictor=predictor_agent,
                diagnostics=diagnostic_agents,
                finalize=variant_hook,
            )
        )
        st.session_state.eval_result = state
        status.success("Evaluation cycle complete!")
    except Exception as exc:
        status.error(f"Evaluation cycle failed: {exc}")
        st.stop()

# ── Display results ────────────────────────────────────────────────────────────

if st.session_state.eval_result is not None:
    state = st.session_state.eval_result

    st.divider()
    st.subheader("Stage 1: Similar Posts (from neighbor-fetch)")
    st.caption(
        f"Retrieved {len(state.similar_posts)} semantically similar historical posts "
        "via embed_query() + find_similar() (reuses T2's retrieval endpoint logic)."
    )

    if state.similar_posts:
        for i, post in enumerate(state.similar_posts[:5], start=1):  # Show top 5
            with st.expander(
                f"#{i} — post_id={post.post_id} | "
                f"engagement={post.total_engagement} (p{post.engagement_percentile:.0f}) | "
                f"distance={post.cosine_distance:.3f}",
                expanded=(i == 1),
            ):
                st.markdown(f"**Content:**\n\n{post.content}")
                cols = st.columns(4)
                cols[0].metric("Likes", post.likes)
                cols[1].metric("Comments", post.comments)
                cols[2].metric("Shares", post.shares)
                cols[3].metric("Percentile", f"{post.engagement_percentile:.1f}")
    else:
        st.info("No similar posts found (DB might be empty).")

    st.divider()
    st.subheader("Stage 2: Concurrent Evaluation (Predictor + Diagnostics)")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Predictor Result** (T3.2)")
        if state.predictor_result is None:
            st.info("No predictor result returned.")
        else:
            predictor = state.predictor_result
            metrics = st.columns(2)
            metrics[0].metric(
                "Predicted Percentile",
                f"{predictor.get('predicted_engagement_percentile', 0):.1f}",
            )
            metrics[1].metric(
                "Predicted Engagement",
                f"{predictor.get('predicted_total_engagement', 0)}",
            )
            st.markdown("**Reasoning**")
            st.write(predictor.get("reasoning", "No reasoning returned."))

    with col2:
        st.markdown("**Diagnostics** (T3.3)")
        if not state.diagnostics:
            st.info("No diagnostic results returned.")
        else:
            for name in ["seo", "clarity", "tone"]:
                diagnostic = state.diagnostics.get(name)
                if diagnostic is None:
                    continue
                with st.expander(name.title(), expanded=True):
                    st.metric("Score", f"{diagnostic.get('score', 0):.1f}/10")
                    _render_list("Flaws", diagnostic.get("flaws", []))
                    _render_list("Advantages", diagnostic.get("advantages", []))
                    _render_list("Improvements", diagnostic.get("improvements", []))

    if state.errors:
        st.warning(f"**Errors:** {len(state.errors)} agent(s) failed during concurrent evaluation")
        for error in state.errors:
            st.error(error)

    st.divider()
    st.subheader("Stage 3: Variants (T3.4 — Variant Optimisation Engine)")
    if not state.variants:
        st.info(
            "No variants returned — the engine skips entirely when neither a predictor "
            "result nor any diagnostics are available. Check the errors below."
        )
    else:
        st.caption(
            "Ranked descending by recalculated predicted engagement percentile "
            "(the T3.2 Predictor Agent re-run on each rewritten variant)."
        )
        original_percentile = (
            state.predictor_result.get("predicted_engagement_percentile")
            if state.predictor_result
            else None
        )
        # Vertically stacked, ranked top-to-bottom — chosen over side-by-side
        # columns since rewritten post copy can be long and columns would
        # cramp/truncate it.
        for i, variant in enumerate(state.variants, start=1):
            with st.container(border=True):
                rank_label = "Highest Predicted" if i == 1 else f"Rank {i}"
                st.markdown(f"**Variant {i} — {rank_label}** &nbsp; `{variant['strategy_label']}`")
                metrics = st.columns(2)
                delta = (
                    f"{variant['predicted_engagement_percentile'] - original_percentile:+.1f}"
                    if original_percentile is not None
                    else None
                )
                metrics[0].metric(
                    "Predicted Percentile",
                    f"{variant['predicted_engagement_percentile']:.1f}",
                    delta=delta,
                )
                metrics[1].metric("Predicted Engagement", f"{variant['predicted_total_engagement']}")
                st.markdown("**Rationale**")
                st.write(variant["rationale"])
                st.markdown("**Variant text**")
                st.text_area(
                    f"variant_{i}_text",
                    value=variant["variant_text"],
                    height=140,
                    label_visibility="collapsed",
                    disabled=True,
                )

    st.divider()
    st.subheader("Raw Response (full PostEvaluationState)")
    st.json(state.model_dump())
