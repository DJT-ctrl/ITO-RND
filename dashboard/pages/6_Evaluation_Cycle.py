"""LinkedIn Post Evaluator — Phase 4 production interface (T4.1-T4.4).

Runs the full Phase 3 pipeline end-to-end:

  Stage 1 (sequential): embed the draft and retrieve 10 nearest historical
      neighbors via pgvector cosine search (T2 retrieval layer).
  Stage 2 (concurrent): Predictor Agent (T3.2) estimates engagement
      percentile; Diagnostic Worker Agents (T3.3) check SEO, clarity, and
      tone in parallel via asyncio.gather().
  Stage 3 (sequential): Variant Optimisation Engine (T3.4) produces 3
      ranked rewrites using the collected diagnostic output.

T4.2 — each stage surfaces its own progress indicator as it completes.
T4.3 — top scorecard + per-diagnostic progress bars.
T4.4 — any variant can be applied back to the draft input with one click.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

import streamlit as st
from pydantic import BaseModel

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from agents.diagnostics import build_diagnostic_agents  # noqa: E402
# _gather_similar_posts is the stage-1 coroutine from the orchestrator;
# imported directly here so we can run each stage separately for T4.2.
from agents.orchestrator import _fetch_voice_profile, _gather_discoverability_context, _gather_similar_posts  # noqa: E402
from agents.predictor import build_predictor_agent  # noqa: E402
from agents.prompt_safety import build_evaluation_user_message  # noqa: E402
from agents.schemas import EvaluationDeps, PostEvaluationState  # noqa: E402
from agents.variant_engine import build_variant_engine  # noqa: E402
from config.settings import load_settings, pydantic_ai_gemini_model  # noqa: E402
from dashboard.pipeline_ui import render_corpus_sidebar  # noqa: E402

_STRATEGY_LABELS = {
    "Dimension-focused (SEO / Clarity / Tone)": "dimension",
    "Narrative angles (hook / educational / story)": "narrative",
    "Tiered risk (safe / moderate / bold)": "tiered",
}

_SEO_MODE_LABELS = {
    "Corpus-grounded (default)": "corpus",
    "Gemini only (baseline for testing)": "gemini_only",
}

_DEFAULT_DRAFT = (
    "Excited to announce our new product launch! "
    "We've been working on this for months."
)

# ── Stage helpers ──────────────────────────────────────────────────────────────

def _as_dict(output: Any) -> dict:
    """Coerce a PydanticAI result output to a plain dict."""
    if isinstance(output, BaseModel):
        return output.model_dump()
    if isinstance(output, dict):
        return output
    return {"result": output}


async def _run_concurrent_eval(
    state: PostEvaluationState,
    predictor,
    diagnostics: dict,
    seo_mode: str = "corpus",
    discoverability_context=None,
) -> None:
    """Stage 2: run Predictor + all Diagnostic agents concurrently.

    Mirrors the asyncio.gather logic in agents/orchestrator.py but exposed
    as a standalone coroutine so the Streamlit page can show separate
    progress for each pipeline stage (T4.2).
    """
    deps = EvaluationDeps(
        draft_content=state.draft_content,
        similar_posts=state.similar_posts,
        voice_profile=state.voice_profile,
        discoverability_context=discoverability_context,
        seo_mode=seo_mode,
    )
    keys: list[str] = ["__predictor__"] + list(diagnostics.keys())
    coros = [
        predictor.run(build_evaluation_user_message(state.draft_content), deps=deps),
        *(agent.run(build_evaluation_user_message(state.draft_content), deps=deps) for agent in diagnostics.values()),
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            state.errors.append(f"{key}: {result}")
            continue
        output = _as_dict(result.output)
        if key == "__predictor__":
            state.predictor_result = output
        else:
            state.diagnostics[key] = output


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="Post Evaluator", layout="wide")
st.title("LinkedIn Post Evaluator")
st.caption(
    "Enter a draft post, then click **Evaluate Post** to get an engagement "
    "prediction, diagnostic analysis, and 3 AI-generated rewrites."
)

settings = load_settings()
_eval_model = pydantic_ai_gemini_model()
predictor_agent = build_predictor_agent(_eval_model)
diagnostic_agents = build_diagnostic_agents(_eval_model)

# T4.4: session state holds the active draft so variant apply can overwrite it.
if "draft_text" not in st.session_state:
    st.session_state.draft_text = _DEFAULT_DRAFT
if "eval_result" not in st.session_state:
    st.session_state.eval_result = None

missing_config = []
if not settings.gemini_api_key:
    missing_config.append("GEMINI_API_KEY")
if not settings.database_url:
    missing_config.append("DATABASE_URL")

with st.sidebar:
    render_corpus_sidebar(settings)
    st.markdown("---")
    st.header("Draft Post")
    draft_content = st.text_area(
        "Post content",
        value=st.session_state.draft_text,
        height=200,
        help="The draft LinkedIn post to evaluate. The system retrieves similar "
        "historical posts, predicts engagement, and runs SEO/clarity/tone diagnostics.",
    )
    st.subheader("Options")
    st.caption(f"Agent model: `{_eval_model}`")
    strategy_choice = st.selectbox(
        "Variant strategy",
        options=list(_STRATEGY_LABELS.keys()),
        help="The rewriting axis the Variant Engine uses to produce 3 distinct alternatives.",
    )
    variant_strategy = _STRATEGY_LABELS[strategy_choice]
    reembed_neighbors = st.checkbox(
        "Per-variant neighbors",
        value=False,
        help="Off (default): all 3 variants scored against the original draft's neighbors. "
        "On: each variant fetches its own nearest neighbors — more accurate but slower.",
    )
    seo_mode_choice = st.selectbox(
        "Discoverability mode",
        options=list(_SEO_MODE_LABELS.keys()),
        help="Corpus-grounded SEO uses your scraped dataset. Gemini only keeps the legacy "
        "static prompt for side-by-side testing.",
    )
    seo_mode = _SEO_MODE_LABELS[seo_mode_choice]
    use_google_trends = st.checkbox(
        "Include Google Trends",
        value=settings.google_trends_enabled,
        disabled=seo_mode == "gemini_only",
        help="Optional: adds web-wide search momentum for keywords from your draft. "
        "Not LinkedIn-specific — off by default so corpus evidence stays primary. "
        "Disabled in Gemini-only baseline mode.",
    )
    st.subheader("Personalization")
    user_id = st.text_input(
        "Subscriber user_id (optional)",
        value="",
        help="When set, retrieval is scoped to this subscriber's own posts (falling back to "
        "the global corpus if they don't have enough yet), and a derived voice profile from "
        "their top posts is injected into every agent's prompt.",
    ).strip() or None
    use_voice_profile = st.checkbox(
        "Use voice profile",
        value=True,
        disabled=user_id is None,
        help="Has no effect without a user_id. Turn off to scope retrieval to the subscriber "
        "without personalizing the agent prompts.",
    )
    st.divider()
    run_clicked = st.button(
        "Evaluate Post",
        type="primary",
        disabled=bool(missing_config) or not draft_content.strip(),
        use_container_width=True,
    )
    if missing_config:
        st.warning(f"Missing config: {', '.join(missing_config)}")

# ── Evaluation (T4.2 — staged progress) ───────────────────────────────────────

if run_clicked and draft_content.strip():
    variant_hook = build_variant_engine(
        predictor_agent,
        model=_eval_model,
        strategy=variant_strategy,
        reembed_neighbors=reembed_neighbors,
        settings=settings,
    )
    state = PostEvaluationState(draft_content=draft_content.strip())

    # Stage 1: neighbor fetch
    with st.status("Finding similar posts...", expanded=True) as s:
        asyncio.run(_gather_similar_posts(state, settings, user_id=user_id))
        if user_id and use_voice_profile:
            asyncio.run(_fetch_voice_profile(state, settings, user_id))
        label = f"Found {len(state.similar_posts)} similar posts"
        if state.voice_profile:
            label += f" · voice profile from {state.voice_profile.get('sample_size')} posts"
        s.update(label=label, state="complete", expanded=False)

    # Stage 2: concurrent evaluation
    with st.status("Running Predictor + Diagnostics...", expanded=True) as s:
        async def _stage2() -> None:
            discoverability_context = None
            resolved_seo_mode = seo_mode or settings.seo_discoverability_mode
            if resolved_seo_mode == "corpus":
                from agents.discoverability_context import resolve_use_google_trends

                resolved_use_trends = resolve_use_google_trends(
                    resolved_seo_mode,
                    settings,
                    use_google_trends=use_google_trends,
                )
                discoverability_context, warnings = await _gather_discoverability_context(
                    state.draft_content,
                    state.similar_posts,
                    settings,
                    use_google_trends=resolved_use_trends,
                )
                state.errors.extend(warnings)
            await _run_concurrent_eval(
                state,
                predictor_agent,
                diagnostic_agents,
                seo_mode=resolved_seo_mode,
                discoverability_context=discoverability_context,
            )

        asyncio.run(_stage2())
        s.update(
            label="Predictor + Diagnostics complete",
            state="complete",
            expanded=False,
        )

    # Stage 3: variant engine
    with st.status("Generating variants...", expanded=True) as s:
        asyncio.run(variant_hook(state))
        n = len(state.variants)
        s.update(
            label=f"{n} variant{'s' if n != 1 else ''} generated",
            state="complete",
            expanded=False,
        )

    st.session_state.eval_result = state
    st.session_state.draft_text = draft_content.strip()
    st.rerun()

# ── Results ────────────────────────────────────────────────────────────────────

if st.session_state.eval_result is not None:
    state = st.session_state.eval_result
    predictor = state.predictor_result or {}

    # T4.3 — Top scorecard
    st.subheader("Scorecard")
    sc = st.columns(5)
    sc[0].metric(
        "Predicted Percentile",
        f"{predictor.get('predicted_engagement_percentile', 0):.0f}",
        help="Where this post is predicted to rank vs all historical posts (0–100).",
    )
    sc[1].metric(
        "Predicted Engagements",
        predictor.get("predicted_total_engagement", "—"),
    )
    for idx, name in enumerate(["seo", "clarity", "tone"], start=2):
        diag = state.diagnostics.get(name, {})
        sc[idx].metric(name.title(), f"{diag.get('score', 0):.1f}/10")

    st.divider()

    # Predictor + Diagnostics side-by-side
    left, right = st.columns(2)

    with left:
        st.subheader("Predictor Analysis")
        if predictor:
            st.write(predictor.get("reasoning", "No reasoning returned."))
        else:
            st.info("No predictor result.")

    with right:
        st.subheader("Diagnostics")
        if not state.diagnostics:
            st.info("No diagnostic results.")
        else:
            for name in ["seo", "clarity", "tone"]:
                diag = state.diagnostics.get(name)
                if not diag:
                    continue
                score = diag.get("score", 0)
                with st.expander(f"**{name.title()}** — {score:.1f}/10", expanded=True):
                    st.progress(score / 10.0)
                    for section, heading, icon in [
                        ("advantages", "Strengths", "+"),
                        ("flaws", "Issues", "−"),
                        ("improvements", "Suggestions", "→"),
                    ]:
                        items = diag.get(section, [])
                        if items:
                            st.markdown(f"**{heading}**")
                            for item in items:
                                st.markdown(f"{icon} {item}")

    if state.errors:
        with st.expander(f"⚠ {len(state.errors)} error(s)", expanded=False):
            for err in state.errors:
                st.error(err)

    st.divider()

    # T4.3 + T4.4 — Variants with one-click apply
    st.subheader(f"Variants ({len(state.variants)})")
    original_pct = predictor.get("predicted_engagement_percentile")

    if not state.variants:
        st.info("No variants were generated.")
    else:
        for i, variant in enumerate(state.variants, start=1):
            with st.container(border=True):
                header_col, metric_col = st.columns([3, 1])
                with header_col:
                    label = "Top Variant" if i == 1 else f"Variant {i}"
                    st.markdown(f"**{label}** &nbsp; `{variant.get('strategy_label', '')}`")
                    st.write(variant.get("rationale", ""))
                with metric_col:
                    pct = variant.get("predicted_engagement_percentile", 0)
                    delta = (
                        f"{pct - original_pct:+.0f}" if original_pct is not None else None
                    )
                    st.metric("Percentile", f"{pct:.0f}", delta=delta)
                    st.metric(
                        "Engagements",
                        variant.get("predicted_total_engagement", "—"),
                    )

                st.text_area(
                    f"v{i}",
                    value=variant.get("variant_text", ""),
                    height=110,
                    label_visibility="collapsed",
                )

                # T4.4: one-click apply — loads variant text back into the draft input
                if st.button(f"Use Variant {i}", key=f"apply_{i}", type="secondary"):
                    st.session_state.draft_text = variant.get("variant_text", "")
                    st.session_state.eval_result = None
                    st.rerun()

    st.divider()
    with st.expander(
        f"Similar posts used as context ({len(state.similar_posts)} retrieved)",
        expanded=False,
    ):
        for j, post in enumerate(state.similar_posts[:5], start=1):
            st.markdown(
                f"**#{j}** &nbsp; `{post.post_id}` · "
                f"p{post.engagement_percentile:.0f} · "
                f"distance={post.cosine_distance:.3f}"
            )
            preview = post.content[:300]
            if len(post.content) > 300:
                preview += "…"
            st.caption(preview)
            if j < min(5, len(state.similar_posts)):
                st.divider()

else:
    st.info("Enter your draft post in the sidebar and click **Evaluate Post**.")
