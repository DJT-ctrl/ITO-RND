"""Throwaway visual test harness for Step 5 — Evaluation Cycle Orchestrator (T3.1).

Exercises the exact same code path as the FastAPI endpoint
(POST /api/v1/evaluate in api/main.py) directly — run_evaluation_cycle()
(agents/orchestrator.py) which calls embed_query() + find_similar() to
populate similar_posts, then runs any registered Predictor/Diagnostic agents
concurrently via asyncio.gather().

What this visualises:
  - The full 3-stage pipeline: sequential neighbor-fetch, concurrent
    evaluation (Predictor + Diagnostics), optional sequential finalize.
  - For T3.1's own scope, NO real agents are registered yet (T3.2 Predictor,
    T3.3 Diagnostics, T3.4 Variant Engine don't exist yet), so
    predictor_result/diagnostics/variants stay empty — that's expected, not a
    bug. This page exists to prove the orchestrator plumbing works end-to-end.
  - Once T3.2/T3.3/T3.4 land, those fields will populate with actual AI
    predictions, diagnostic checks, and generated variants.

Not the product UI — exists purely to validate T3.1's orchestrator the same
way earlier pages validate their pipeline stage.
"""

import asyncio
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from agents.orchestrator import run_evaluation_cycle  # noqa: E402
from config.settings import load_settings  # noqa: E402

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Evaluation Cycle Test Harness", layout="wide")
st.title("Step 5: Evaluation Cycle Orchestrator (T3.1)")
st.caption(
    "Throwaway visual tool for the T3.1 async orchestrator. Calls the real "
    "Gemini embedding endpoint + Postgres DB to fetch neighbors, then runs "
    "the concurrent evaluation stage (no real agents registered yet — "
    "T3.2/T3.3/T3.4 will populate predictor_result/diagnostics/variants later)."
)

settings = load_settings()

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
        "similar historical posts and (once T3.2-T3.4 land) run prediction + "
        "diagnostic + variant generation agents on it.",
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
        st.info("Running evaluation cycle (neighbor-fetch + concurrent agents stage)...")
    try:
        # run_evaluation_cycle is async, need to call it via asyncio.run
        state = asyncio.run(run_evaluation_cycle(draft_content.strip(), settings))
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
        st.markdown("**Predictor Result** (T3.2 — not implemented yet)")
        if state.predictor_result is None:
            st.info(
                "No predictor agent registered. Once T3.2 (Predictor Agent Development) "
                "lands, this will show a predicted engagement score based on the 10 "
                "nearest neighbors."
            )
        else:
            st.json(state.predictor_result)

    with col2:
        st.markdown("**Diagnostics** (T3.3 — not implemented yet)")
        if not state.diagnostics:
            st.info(
                "No diagnostic agents registered. Once T3.3 (Diagnostic Worker Agents) "
                "lands, this will show parallel checks for SEO, clarity, tone, etc."
            )
        else:
            st.json(state.diagnostics)

    if state.errors:
        st.warning(f"**Errors:** {len(state.errors)} agent(s) failed during concurrent evaluation")
        for error in state.errors:
            st.error(error)

    st.divider()
    st.subheader("Stage 3: Variants (T3.4 — not implemented yet)")
    if not state.variants:
        st.info(
            "Variant Optimisation Engine (T3.4) not implemented yet. Once it lands, "
            "this will show 3 improved post variations generated from the diagnostics."
        )
    else:
        for i, variant in enumerate(state.variants, start=1):
            with st.expander(f"Variant {i}", expanded=False):
                st.json(variant)

    st.divider()
    st.subheader("Raw Response (full PostEvaluationState)")
    st.json(state.model_dump())
