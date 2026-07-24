"""LinkedIn Post Evaluator — Phase 4 production interface (T4.1-T4.4).

Runs the full Phase 3 pipeline end-to-end, plus optional independent side-steps:
  - Synthetic audience critic (T7.11–T7.13)
  - Synthesis optimisation (T7.14–T7.16)

Heavy UI panels live in dashboard/*_ui.py so this page stays under 500 lines.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

import streamlit as st
from pydantic import BaseModel

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from agents.audience_critic import (  # noqa: E402
    build_audience_critic_agent,
    run_audience_critic,
)
from agents.diagnostics import build_diagnostic_agents  # noqa: E402
from agents.orchestrator import (  # noqa: E402
    _fetch_draft_follower_count,
    _fetch_voice_profile,
    _gather_discoverability_context,
    _gather_similar_posts,
)
from agents.predictor import (  # noqa: E402
    apply_deterministic_prediction,
    build_predictor_agent,
)
from agents.prompt_safety import build_evaluation_user_message  # noqa: E402
from agents.schemas import EvaluationDeps, PostEvaluationState  # noqa: E402
from agents.synthesis import run_synthesis  # noqa: E402
from agents.variant_engine import build_variant_engine  # noqa: E402
from config.settings import load_settings, pydantic_ai_gemini_model  # noqa: E402
from dashboard.audience_critic_ui import (  # noqa: E402
    extract_primary_objection,
    render_critic_results_panel,
    render_critic_sidebar_controls,
)
from dashboard.pipeline_ui import render_corpus_sidebar  # noqa: E402
from dashboard.synthesis_ui import (  # noqa: E402
    render_synthesis_results_panel,
    render_synthesis_sidebar_controls,
)
from dashboard.variant_results_ui import (  # noqa: E402
    render_similar_posts_expander,
    render_variant_results,
)
from processors.benchmark import compute_neighbor_prediction  # noqa: E402
from telemetry.collector import RunMetadataCollector  # noqa: E402
from telemetry.instrument import run_agent_step  # noqa: E402
from telemetry.persist import save_run_metadata  # noqa: E402
from telemetry.ui import render_run_metadata_summary  # noqa: E402
from validation_pipeline.ui import render_accuracy_summary  # noqa: E402

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


def _as_dict(output: Any) -> dict:
    if isinstance(output, BaseModel):
        return output.model_dump()
    if isinstance(output, dict):
        return output
    return {"result": output}


async def _run_concurrent_eval(
    state: PostEvaluationState,
    predictor,
    diagnostics: dict,
    collector: Optional[RunMetadataCollector] = None,
    seo_mode: str = "corpus",
    discoverability_context=None,
    neighbor_prediction=None,
    draft_follower_count=None,
) -> None:
    """Stage 2: Predictor + diagnostics concurrently (mirrors orchestrator)."""
    from agents.predictor import PredictorOutput  # noqa: PLC0415

    deps = EvaluationDeps(
        draft_content=state.draft_content,
        similar_posts=state.similar_posts,
        voice_profile=state.voice_profile,
        seo_mode=seo_mode,
        discoverability_context=discoverability_context,
        draft_follower_count=draft_follower_count,
    )
    names = list(diagnostics.keys())
    tasks = [
        run_agent_step(
            collector,
            step_id="agent.predictor",
            label="Predictor",
            stage="agent",
            agent=predictor,
            prompt=build_evaluation_user_message(state.draft_content),
            deps=deps,
            model=pydantic_ai_gemini_model(),
        )
    ]
    for name in names:
        tasks.append(
            run_agent_step(
                collector,
                step_id=f"agent.diagnostic.{name}",
                label=f"Diagnostic ({name})",
                stage="agent",
                agent=diagnostics[name],
                prompt=build_evaluation_user_message(state.draft_content),
                deps=deps,
                model=pydantic_ai_gemini_model(),
            )
        )
    results = await asyncio.gather(*tasks, return_exceptions=True)
    pred_result, *diag_results = results

    if isinstance(pred_result, Exception):
        state.errors.append(f"predictor: {pred_result}")
    else:
        output = _as_dict(pred_result.output)
        if isinstance(pred_result.output, PredictorOutput) and neighbor_prediction:
            corrected = apply_deterministic_prediction(
                pred_result.output, neighbor_prediction
            )
            output = corrected.model_dump()
        state.predictor_result = output

    for name, result in zip(names, diag_results):
        if isinstance(result, Exception):
            state.errors.append(f"{name}: {result}")
        else:
            state.diagnostics[name] = _as_dict(result.output)


settings = load_settings()
_eval_model = pydantic_ai_gemini_model()
predictor_agent = build_predictor_agent(_eval_model)
diagnostic_agents = build_diagnostic_agents(_eval_model)

if "draft_text" not in st.session_state:
    st.session_state.draft_text = _DEFAULT_DRAFT
if "eval_result" not in st.session_state:
    st.session_state.eval_result = None
if "critic_result" not in st.session_state:
    st.session_state.critic_result = None
if "critic_error" not in st.session_state:
    st.session_state.critic_error = None
if "synthesis_result" not in st.session_state:
    st.session_state.synthesis_result = None
if "synthesis_error" not in st.session_state:
    st.session_state.synthesis_error = None

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
        help="Draft LinkedIn post for evaluate / critic / optimisation side-steps.",
    )
    st.subheader("Options")
    st.caption(f"Agent model: `{_eval_model}`")
    strategy_choice = st.selectbox(
        "Variant strategy",
        options=list(_STRATEGY_LABELS.keys()),
        help="Rewriting axis for evaluate-loop variants (T3.4).",
    )
    variant_strategy = _STRATEGY_LABELS[strategy_choice]
    reembed_neighbors = st.checkbox(
        "Per-variant neighbors",
        value=False,
        help="Off: shared neighbors. On: each variant fetches its own (slower).",
    )
    seo_mode_choice = st.selectbox(
        "Discoverability mode",
        options=list(_SEO_MODE_LABELS.keys()),
    )
    seo_mode = _SEO_MODE_LABELS[seo_mode_choice]
    use_google_trends = st.checkbox(
        "Include Google Trends",
        value=settings.google_trends_enabled,
        disabled=seo_mode == "gemini_only",
        help="Optional web-wide search momentum. Disabled in Gemini-only mode.",
    )
    st.subheader("Personalization")
    user_id = st.text_input("Subscriber user_id (optional)", value="").strip() or None
    use_voice_profile = st.checkbox(
        "Use voice profile",
        value=True,
        disabled=user_id is None,
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

    critic_clicked = render_critic_sidebar_controls(
        missing_config=bool(missing_config), draft_content=draft_content
    )
    optimise_clicked = render_synthesis_sidebar_controls(
        missing_config=bool(missing_config), draft_content=draft_content
    )

# ── Evaluate (T4.2 staged progress) ───────────────────────────────────────────

if run_clicked and draft_content.strip():
    collector = RunMetadataCollector(
        settings=settings,
        user_id=user_id,
        agent_model=_eval_model,
        variant_strategy=variant_strategy,
        reembed_variant_neighbors=reembed_neighbors,
        seo_mode=seo_mode,
    )
    variant_hook = build_variant_engine(
        predictor_agent,
        model=_eval_model,
        strategy=variant_strategy,
        reembed_neighbors=reembed_neighbors,
        settings=settings,
        collector=collector,
    )
    state = PostEvaluationState(draft_content=draft_content.strip())
    stage1_start = len(collector.steps)

    with st.status("Finding similar posts...", expanded=True) as s:
        asyncio.run(
            _gather_similar_posts(state, settings, user_id=user_id, collector=collector)
        )
        if user_id and use_voice_profile:
            asyncio.run(_fetch_voice_profile(state, settings, user_id, collector=collector))
        label = f"Found {len(state.similar_posts)} similar posts"
        if state.voice_profile:
            label += f" · voice profile from {state.voice_profile.get('sample_size')} posts"
        label += collector.format_snippet(stage="retrieval", since_index=stage1_start)
        s.update(label=label, state="complete", expanded=False)

    draft_follower_count = None
    if user_id:
        draft_follower_count = asyncio.run(
            _fetch_draft_follower_count(settings, user_id, collector=collector)
        )
    neighbor_prediction = collector.record_timed(
        step_id="setup.neighbor_prediction",
        label="Compute neighbor prediction",
        stage="setup",
        call_type="compute",
        fn=lambda: compute_neighbor_prediction(
            state.similar_posts, draft_follower_count=draft_follower_count
        ),
    )

    with st.status("Running Predictor + Diagnostics...", expanded=True) as s:
        stage2_start = len(collector.steps)

        async def _stage2() -> None:
            discoverability_context = None
            resolved_seo_mode = seo_mode or settings.seo_discoverability_mode
            if resolved_seo_mode == "corpus":
                from agents.discoverability_context import resolve_use_google_trends

                resolved_use_trends = resolve_use_google_trends(
                    resolved_seo_mode, settings, use_google_trends=use_google_trends
                )
                discoverability_context, warnings = await _gather_discoverability_context(
                    state.draft_content,
                    state.similar_posts,
                    settings,
                    use_google_trends=resolved_use_trends,
                    collector=collector,
                )
                state.errors.extend(warnings)
            await _run_concurrent_eval(
                state,
                predictor_agent,
                diagnostic_agents,
                collector=collector,
                seo_mode=resolved_seo_mode,
                discoverability_context=discoverability_context,
                neighbor_prediction=neighbor_prediction,
                draft_follower_count=draft_follower_count,
            )

        asyncio.run(_stage2())
        s.update(
            label="Predictor + Diagnostics complete"
            + collector.format_snippet(stage="agent", since_index=stage2_start),
            state="complete",
            expanded=False,
        )

    with st.status("Generating variants...", expanded=True) as s:
        stage3_start = len(collector.steps)
        asyncio.run(variant_hook(state))
        n = len(state.variants)
        s.update(
            label=f"{n} variant{'s' if n != 1 else ''} generated"
            + collector.format_snippet(stage="variant", since_index=stage3_start),
            state="complete",
            expanded=False,
        )

    state.run_metadata = collector.finalize()
    save_run_metadata(state.run_metadata, settings)
    st.session_state.eval_result = state
    st.session_state.draft_text = draft_content.strip()
    st.rerun()

# ── Independent critic ────────────────────────────────────────────────────────

if critic_clicked and draft_content.strip():
    st.session_state.critic_error = None
    try:
        with st.spinner("Running synthetic audience critic…"):
            st.session_state.critic_result = asyncio.run(
                run_audience_critic(
                    draft_content.strip(),
                    agent=build_audience_critic_agent(_eval_model),
                )
            )
        st.session_state.draft_text = draft_content.strip()
    except Exception as exc:  # noqa: BLE001
        st.session_state.critic_error = str(exc)
        st.session_state.critic_result = None
    st.rerun()

# ── Independent synthesis optimisation ────────────────────────────────────────

if optimise_clicked and draft_content.strip():
    st.session_state.synthesis_error = None
    eval_state = st.session_state.eval_result
    predictor = (eval_state.predictor_result or {}) if eval_state else {}
    baseline_pct = predictor.get("predicted_engagement_percentile")
    baseline_eng = predictor.get("predicted_total_engagement")
    objection = extract_primary_objection(st.session_state.critic_result)
    voice = eval_state.voice_profile if eval_state else None
    neighbors = eval_state.similar_posts if eval_state else None
    try:
        with st.spinner("Running synthesis optimisation…"):
            st.session_state.synthesis_result = asyncio.run(
                run_synthesis(
                    draft_content.strip(),
                    settings,
                    primary_objection=objection,
                    baseline_percentile=baseline_pct,
                    baseline_total_engagement=baseline_eng,
                    voice_profile=voice,
                    similar_posts=neighbors,
                    user_id=user_id,
                    predictor_agent=predictor_agent,
                    model=_eval_model,
                )
            )
        st.session_state.draft_text = draft_content.strip()
    except Exception as exc:  # noqa: BLE001
        st.session_state.synthesis_error = str(exc)
        st.session_state.synthesis_result = None
    st.rerun()

# ── Results tabs ──────────────────────────────────────────────────────────────

st.divider()
results_tab, accuracy_tab, gemini_cost_tab = st.tabs(
    ["Evaluation Results", "Accuracy History", "Gemini Spend"]
)

with accuracy_tab:
    st.caption("Predicted vs actual engagement after scheduled re-scrape.")
    render_accuracy_summary(settings, compact=True)

with gemini_cost_tab:
    st.caption("Estimated Gemini API cost across logged evaluation runs.")
    from telemetry.ui import render_gemini_cost_history  # noqa: E402

    render_gemini_cost_history(settings)

with results_tab:
    render_critic_results_panel(
        st.session_state.critic_result, st.session_state.critic_error
    )
    render_synthesis_results_panel(
        st.session_state.synthesis_result, st.session_state.synthesis_error
    )

    if st.session_state.eval_result is not None:
        state = st.session_state.eval_result
        predictor = state.predictor_result or {}
        render_run_metadata_summary(state.run_metadata)
        st.divider()

        st.subheader("Scorecard")
        sc = st.columns(5)
        sc[0].metric(
            "Predicted Percentile",
            f"{predictor.get('predicted_engagement_percentile', 0):.0f}",
        )
        sc[1].metric(
            "Predicted Engagements",
            predictor.get("predicted_total_engagement", "—"),
        )
        for idx, name in enumerate(["seo", "clarity", "tone"], start=2):
            diag = state.diagnostics.get(name, {})
            sc[idx].metric(name.title(), f"{diag.get('score', 0):.1f}/10")

        st.divider()
        left, right = st.columns(2)
        with left:
            st.subheader("Predictor Analysis")
            st.write(
                predictor.get("reasoning", "No reasoning returned.")
                if predictor
                else "No predictor result."
            )
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
        render_variant_results(
            state.variants,
            original_percentile=predictor.get("predicted_engagement_percentile"),
        )
        st.divider()
        render_similar_posts_expander(state.similar_posts)
    elif (
        st.session_state.critic_result is None
        and not st.session_state.critic_error
        and st.session_state.synthesis_result is None
        and not st.session_state.synthesis_error
    ):
        st.info(
            "Enter your draft in the sidebar, then **Evaluate Post**, "
            "**Run critic**, and/or **Run optimisation**."
        )
