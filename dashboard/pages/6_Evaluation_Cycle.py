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
from typing import Any, Optional

import streamlit as st
from pydantic import BaseModel

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from agents.diagnostics import build_diagnostic_agents  # noqa: E402
# _gather_similar_posts is the stage-1 coroutine from the orchestrator;
# imported directly here so we can run each stage separately for T4.2.
from agents.orchestrator import (  # noqa: E402
    _fetch_draft_follower_count,
    _fetch_voice_profile,
    _gather_discoverability_context,
    _gather_similar_posts,
)
from agents.predictor import build_predictor_agent  # noqa: E402
from agents.prompt_safety import build_evaluation_user_message  # noqa: E402
from agents.schemas import EvaluationDeps, PostEvaluationState  # noqa: E402
from agents.variant_engine import build_variant_engine  # noqa: E402
from agents.visual_diagnostics import (  # noqa: E402
    build_visual_agent,
    build_visual_user_prompt,
    prepare_visual_image,
    resolve_use_visual_diagnostics,
)
from config.settings import load_settings, pydantic_ai_gemini_model  # noqa: E402
from dashboard.chrome import page_header, section_header  # noqa: E402
from dashboard.pipeline_ui import render_corpus_sidebar  # noqa: E402
from dashboard.trend_signals_ui import render_trend_signals_panel  # noqa: E402
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
    collector: Optional[RunMetadataCollector] = None,
    seo_mode: str = "corpus",
    discoverability_context=None,
    neighbor_prediction=None,
    draft_follower_count=None,
    clarity_context=None,
    image_url: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    image_media_type: Optional[str] = None,
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
        clarity_context=clarity_context,
        neighbor_prediction=neighbor_prediction,
        draft_follower_count=draft_follower_count,
        image_url=image_url,
        image_bytes=image_bytes,
        image_media_type=image_media_type,
    )
    keys: list[str] = ["__predictor__"] + list(diagnostics.keys())
    text_prompt = build_evaluation_user_message(state.draft_content)
    agent_model = pydantic_ai_gemini_model()
    coros = [
        run_agent_step(
            collector,
            step_id="agent.predictor",
            label="Predictor",
            stage="agent",
            agent=predictor,
            prompt=text_prompt,
            deps=deps,
            model=agent_model,
        ),
        *(
            run_agent_step(
                collector,
                step_id=f"agent.{name}",
                label=name.title(),
                stage="agent",
                agent=agent,
                prompt=(
                    build_visual_user_prompt(deps)
                    if name == "visual"
                    else text_prompt
                ),
                deps=deps,
                model=agent_model,
            )
            for name, agent in diagnostics.items()
        ),
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            state.errors.append(f"{key}: {result}")
            continue
        output = _as_dict(result.output)
        if key == "__predictor__":
            from agents.predictor import PredictorOutput, apply_deterministic_prediction

            if isinstance(result.output, PredictorOutput) and neighbor_prediction:
                corrected = apply_deterministic_prediction(result.output, neighbor_prediction)
                output = corrected.model_dump()
            state.predictor_result = output
        else:
            state.diagnostics[key] = output


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="Draft evaluator", layout="wide")
page_header(
    "Draft evaluator",
    "Paste a LinkedIn draft and run the full evaluation cycle: find similar "
    "posts, predict engagement + diagnostics, then suggest three rewrites.",
    step_hint="Uses the same retrieval + agents as the product-shaped path",
)
section_header(
    "What happens when you click Evaluate",
    """
1. **Retrieve neighbors** — embed the draft and fetch similar historical posts.
2. **Score the draft** — predictor + diagnostic agents run together.
3. **Suggest rewrites** — three variant posts along the strategy you pick.

This is the closest page to an end-user experience; corpus/validation pages are
operator tools that feed the data behind it.
""",
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
    neighbor_limit = st.slider(
        "Neighbor limit",
        min_value=10,
        max_value=100,
        value=10,
        step=1,
        help="How many nearest historical posts to retrieve for grounding and comparison "
        "(default 10). Higher values widen the comparison surface but add prompt tokens "
        "and can dilute the baseline if distant neighbors are weak matches.",
    )
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
        value=True,
        disabled=seo_mode == "gemini_only",
        key="eval_include_google_trends",
        help="After evaluate, shows a Trend signals panel with keyword momentum from "
        "Google Trends (web search — not LinkedIn). Keywords come from hashtags / "
        "draft text detectors (no extra AI search step). Disabled in Gemini-only mode.",
    )
    if seo_mode == "gemini_only":
        use_google_trends = False
    use_visual_diagnostics = st.checkbox(
        "Include visual diagnostics (T7.9 + T7.10)",
        value=False,
        key="eval_include_visual_diagnostics",
        help="Off by default. When on, Gemini multimodal judges image hierarchy "
        "(contrast/clutter) and OCR/copy alignment. Requires an image URL or upload.",
    )
    image_url = st.text_input(
        "Draft image URL (optional)",
        value="",
        disabled=not use_visual_diagnostics,
        key="eval_visual_image_url",
        help="Public http(s) jpeg/png/webp URL. Ignored when visual diagnostics are off.",
    ).strip() or None
    uploaded_image = st.file_uploader(
        "Or upload draft image",
        type=["jpg", "jpeg", "png", "webp"],
        disabled=not use_visual_diagnostics,
        key="eval_visual_image_upload",
        help="Used instead of URL when both are provided. Max ~5MB.",
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
    collector = RunMetadataCollector(
        settings=settings,
        user_id=user_id,
        agent_model=_eval_model,
        variant_strategy=variant_strategy,
        reembed_variant_neighbors=reembed_neighbors,
        seo_mode=seo_mode,
        neighbor_limit=neighbor_limit,
    )
    variant_hook = build_variant_engine(
        predictor_agent,
        model=_eval_model,
        strategy=variant_strategy,
        reembed_neighbors=reembed_neighbors,
        settings=settings,
        collector=collector,
        neighbor_limit=neighbor_limit,
    )
    state = PostEvaluationState(draft_content=draft_content.strip())
    stage1_start = len(collector.steps)

    # Stage 1: neighbor fetch
    with st.status("Finding similar posts...", expanded=True) as s:
        asyncio.run(
            _gather_similar_posts(
                state,
                settings,
                user_id=user_id,
                collector=collector,
                neighbor_limit=neighbor_limit,
            )
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
        fn=lambda: compute_neighbor_prediction(state.similar_posts, draft_follower_count=draft_follower_count),
    )

    # Stage 2: concurrent evaluation
    with st.status("Running Predictor + Diagnostics...", expanded=True) as s:
        stage2_start = len(collector.steps)

        async def _stage2() -> None:
            discoverability_context = None
            resolved_seo_mode = seo_mode or settings.seo_discoverability_mode
            state.google_trends_requested = bool(
                use_google_trends and resolved_seo_mode == "corpus"
            )
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
                    collector=collector,
                )
                state.discoverability_context = discoverability_context
                state.errors.extend(warnings)

            from agents.clarity_metrics import compute_clarity_metrics

            clarity_context = compute_clarity_metrics(state.draft_content)
            state.clarity_context = clarity_context

            resolved_visual = resolve_use_visual_diagnostics(
                settings, use_visual_diagnostics=use_visual_diagnostics
            )
            state.visual_diagnostics_requested = resolved_visual

            upload_bytes = None
            upload_media = None
            if uploaded_image is not None:
                upload_bytes = uploaded_image.getvalue()
                upload_media = uploaded_image.type or None

            resolved_image_bytes = None
            resolved_image_media = None
            resolved_image_url = None
            stage_diagnostics = dict(diagnostic_agents)
            if resolved_visual:
                (
                    resolved_image_bytes,
                    resolved_image_media,
                    resolved_image_url,
                    image_warnings,
                ) = prepare_visual_image(
                    image_url=image_url,
                    image_bytes=upload_bytes,
                    image_media_type=upload_media,
                )
                state.errors.extend(image_warnings)
                state.visual_image_provided = bool(
                    resolved_image_bytes and resolved_image_media
                ) or bool(resolved_image_url)
                if state.visual_image_provided:
                    stage_diagnostics["visual"] = build_visual_agent(_eval_model)
                else:
                    state.errors.append(
                        "visual: skipped — enabled but no usable image provided "
                        "(pass image URL or upload jpeg/png/webp)."
                    )

            await _run_concurrent_eval(
                state,
                predictor_agent,
                stage_diagnostics,
                collector=collector,
                seo_mode=resolved_seo_mode,
                discoverability_context=discoverability_context,
                neighbor_prediction=neighbor_prediction,
                draft_follower_count=draft_follower_count,
                clarity_context=clarity_context,
                image_url=resolved_image_url,
                image_bytes=resolved_image_bytes,
                image_media_type=resolved_image_media,
            )

        asyncio.run(_stage2())
        label = "Predictor + Diagnostics complete" + collector.format_snippet(stage="agent", since_index=stage2_start)
        s.update(
            label=label,
            state="complete",
            expanded=False,
        )

    # Stage 3: variant engine
    with st.status("Generating variants...", expanded=True) as s:
        stage3_start = len(collector.steps)
        asyncio.run(variant_hook(state))
        n = len(state.variants)
        label = f"{n} variant{'s' if n != 1 else ''} generated"
        label += collector.format_snippet(stage="variant", since_index=stage3_start)
        s.update(
            label=label,
            state="complete",
            expanded=False,
        )

    state.run_metadata = collector.finalize()
    save_run_metadata(state.run_metadata, settings)
    st.session_state.eval_result = state
    st.session_state.draft_text = draft_content.strip()
    st.rerun()

# ── Results + Accuracy History ───────────────────────────────────────────────

st.divider()
results_tab, accuracy_tab, gemini_cost_tab = st.tabs(
    ["Evaluation Results", "Accuracy History", "Gemini Spend"]
)

with accuracy_tab:
    st.caption(
        "Read-only summary from the Validation Pipeline — "
        "predicted vs actual engagement after scheduled re-scrape."
    )
    render_accuracy_summary(settings, compact=True)

with gemini_cost_tab:
    st.caption(
        "Estimated Gemini API cost across all logged evaluation runs. "
        "Based on token counts and published per-1M-token rates."
    )
    from telemetry.ui import render_gemini_cost_history  # noqa: E402

    render_gemini_cost_history(settings)


with results_tab:
    if st.session_state.eval_result is not None:
        state = st.session_state.eval_result
        predictor = state.predictor_result or {}

        render_run_metadata_summary(state.run_metadata)

        st.divider()

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

        if predictor.get("predicted_likes") is not None:
            breakdown_cols = st.columns(4)
            breakdown_cols[0].metric("Pred. Likes", predictor.get("predicted_likes", "—"))
            breakdown_cols[1].metric("Pred. Comments", predictor.get("predicted_comments", "—"))
            breakdown_cols[2].metric("Pred. Shares", predictor.get("predicted_shares", "—"))
            breakdown_cols[3].metric(
                "Pred. Total",
                predictor.get("predicted_total_engagement", "—"),
            )

        st.divider()
        render_trend_signals_panel(
            state.discoverability_context,
            trends_requested=bool(state.google_trends_requested),
        )

        clarity_ctx = state.clarity_context or {}
        if clarity_ctx:
            st.divider()
            st.subheader("Clarity metrics")
            st.caption(
                "Deterministic cognitive-load checks (T7.5) — grounded into the Clarity diagnostic."
            )
            mcols = st.columns(4)
            fk = clarity_ctx.get("flesch_kincaid_grade")
            mcols[0].metric("Reading grade", "—" if fk is None else fk)
            mcols[1].metric("Jargon %", f"{clarity_ctx.get('jargon_density_percent', 0)}%")
            mcols[2].metric(
                "Longest paragraph",
                f"{clarity_ctx.get('max_paragraph_words', 0)} words",
            )
            mcols[3].metric(
                "Clarity baseline",
                f"{clarity_ctx.get('deterministic_score', 0)}/10",
            )
            with st.expander("Clarity signal detail", expanded=False):
                for signal in clarity_ctx.get("signals") or []:
                    st.markdown(
                        f"- **{signal.get('check')}** ({signal.get('status')}): "
                        f"{signal.get('note', '')}"
                    )

        visual_diag = state.diagnostics.get("visual")
        if state.visual_diagnostics_requested or visual_diag:
            st.divider()
            st.subheader("Visual diagnostics")
            st.caption(
                "T7.9 hierarchy + T7.10 OCR/alignment — opt-in, off by default. "
                "Uses Gemini multimodal (no separate OCR model)."
            )
            if visual_diag:
                vcols = st.columns(4)
                vcols[0].metric("Visual score", f"{visual_diag.get('score', 0):.1f}/10")
                vcols[1].metric(
                    "Contrast",
                    "pass" if visual_diag.get("contrast_pass") else "fail",
                )
                vcols[2].metric("Clutter", visual_diag.get("visual_clutter") or "—")
                vcols[3].metric(
                    "Copy alignment",
                    f"{visual_diag.get('copy_alignment_score', 0):.1f}/10",
                )
                if visual_diag.get("hierarchy_critique"):
                    st.markdown(f"**Hierarchy:** {visual_diag['hierarchy_critique']}")
                if visual_diag.get("extracted_text"):
                    with st.expander("Extracted image text", expanded=False):
                        st.write(visual_diag["extracted_text"])
                if visual_diag.get("alignment_notes"):
                    st.markdown(f"**Alignment:** {visual_diag['alignment_notes']}")
            elif state.visual_diagnostics_requested:
                st.info(
                    "Visual diagnostics were requested but no result was produced "
                    "(missing/unusable image, or the agent failed — see errors)."
                )

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
                for name in ["seo", "clarity", "tone", "visual"]:
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
            for j, post in enumerate(state.similar_posts, start=1):
                st.markdown(
                    f"**#{j}** &nbsp; `{post.post_id}` · "
                    f"p{post.engagement_percentile:.0f} · "
                    f"distance={post.cosine_distance:.3f}"
                )
                preview = post.content[:300]
                if len(post.content) > 300:
                    preview += "…"
                st.caption(preview)
                if j < len(state.similar_posts):
                    st.divider()

    else:
        st.info("Enter your draft post in the sidebar and click **Evaluate Post**.")
