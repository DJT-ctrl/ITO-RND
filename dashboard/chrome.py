"""Shared Streamlit chrome: headers, ? help, phase badges, pipeline strips.

Frontend helpers. Pipeline strips may receive readiness computed by callers.
"""

from __future__ import annotations

from typing import Literal, Optional, Sequence

import streamlit as st

# Fixed palette for Phase 0 / A–J (+ G+). Used everywhere for consistency.
# plain = short “what it does”; detail = how it works; example = concrete walkthrough.
PHASES: dict[str, dict[str, str]] = {
    "0": {
        "name": "Foundation",
        "plain": "Grade predictions after real engagement comes in",
        "detail": (
            "Without grading, nothing later can learn. We store the predicted "
            "score, wait for real likes/comments/views, then score how far off "
            "we were (error / MAE)."
        ),
        "example": (
            "Predicted 72nd percentile → post later lands at 45th → we record "
            "a miss so Phases A–B have something to learn from."
        ),
        "color": "#64748b",
        "status": "Done",
    },
    "A": {
        "name": "Calibration",
        "plain": "Nudge predicted scores using past mistakes",
        "detail": (
            "A numeric offset from recent graded posts (global and/or per "
            "bucket). It adjusts the final number without rewriting the model. "
            "Kept OFF in prod until Phase F says GO."
        ),
        "example": (
            "We often over-predict by ~8 points on short text posts → "
            "calibration subtracts ~8 from the next similar prediction."
        ),
        "color": "#2563eb",
        "status": "Done (prod OFF)",
    },
    "B": {
        "name": "Lessons",
        "plain": "Write a short lesson after each graded post",
        "detail": (
            "After a grade, we save a short template lesson (what we thought "
            "vs what happened). Lessons are the raw material Phases C–D and "
            "G reuse. Usually ON even when calibration/injection stay OFF."
        ),
        "example": (
            "“Short carousel for founders: predicted high reach; actual "
            "engagement low — hooks buried below the fold.”"
        ),
        "color": "#0d9488",
        "status": "Done",
    },
    "C": {
        "name": "Buckets",
        "plain": "Sort posts into length × format × audience groups",
        "detail": (
            "Filing system so lessons from a long video don’t pollute advice "
            "for a short text post. Buckets are the primary routing labels "
            "before meaning-match (H)."
        ),
        "example": (
            "A 400-word text post aimed at marketers → bucket like "
            "`medium × text × marketers`, separate from `short × carousel × founders`."
        ),
        "color": "#16a34a",
        "status": "Done",
    },
    "D": {
        "name": "Injection",
        "plain": "Show recent same-bucket lessons to the predictor",
        "detail": (
            "Puts a few recent same-bucket lessons into the predictor prompt "
            "so the model can adjust reasoning (not only a numeric nudge). "
            "Prod OFF until Phase F proves lift."
        ),
        "example": (
            "Predicting a new short-text founder post → prompt includes the "
            "last 3 graded lessons from that same bucket."
        ),
        "color": "#d97706",
        "status": "Done (prod OFF)",
    },
    "E": {
        "name": "Observability",
        "plain": "Measure accuracy, costs, and learning health",
        "detail": (
            "Dashboards and telemetry: prediction error over time, LLM/API "
            "spend, lesson coverage, queue depth, and whether learning "
            "switches are safe to flip."
        ),
        "example": (
            "You see MAE trending flat, Gemini cost per graded post, and "
            "“Learning active? No — F is NO-GO” before changing toggles."
        ),
        "color": "#4f46e5",
        "status": "Done",
    },
    "F": {
        "name": "Prove lift",
        "plain": "Offline test: only turn learning on if error drops enough",
        "detail": (
            "Replay historical posts with learning ON vs OFF. Need a clear "
            "enough average-error drop (go/no-go bar) before turning "
            "calibration or injection on in production."
        ),
        "example": (
            "Offline re-run improved error by ~3% but the bar was 5% → "
            "NO-GO; keep A/D OFF and keep gathering graded data."
        ),
        "color": "#dc2626",
        "status": "NO-GO (keep OFF)",
    },
    "G": {
        "name": "Smarter lessons",
        "plain": "LLM “why” text + human approve/reject before use",
        "detail": (
            "An LLM writes a richer “why this missed / worked” lesson. A "
            "human must approve (or reject) before that text can be injected. "
            "Staging-ready; review queue lives on the Feedback page."
        ),
        "example": (
            "LLM drafts: “Overestimated because CTA competed with a giveaway "
            "in the first line.” Reviewer Approves → eligible for injection."
        ),
        "color": "#7c3aed",
        "status": "Done (staging)",
    },
    "H": {
        "name": "Meaning match",
        "plain": "Route by embedding similarity (centroids), not only labels",
        "detail": (
            "Embeddings and cluster centroids find “posts like this one” even "
            "when bucket labels don’t match perfectly — better lesson "
            "retrieval for edge cases."
        ),
        "example": (
            "New post is labeled `medium × text` but its embedding sits near "
            "a `carousel × founders` cluster → we still pull those nearby "
            "lessons."
        ),
        "color": "#0891b2",
        "status": "Done (staging)",
    },
    "I": {
        "name": "Scale",
        "plain": "Background job queue + short cluster summaries",
        "detail": (
            "Grading/learning work runs as queued jobs so the UI stays "
            "responsive. Cluster roll-ups compress many lessons into short "
            "summaries for injection at volume."
        ),
        "example": (
            "Validate 40 posts → drain the feedback queue once → cluster "
            "rollup becomes “Short founder carousels: weak when CTA is late.”"
        ),
        "color": "#a16207",
        "status": "Done",
    },
    "J": {
        "name": "Injectability",
        "plain": "Shadow mode and softer locks so lessons can move the score",
        "detail": (
            "Controls how strongly lessons may change the score: hard_lock "
            "(lessons can’t move the number), soft_blend (partial move), "
            "shadow_only (log what would happen). Live default stays hard_lock "
            "until F is GO."
        ),
        "example": (
            "Shadow ON + hard_lock: we log “lesson would have nudged −6” but "
            "the live score stays unchanged."
        ),
        "color": "#db2777",
        "status": "Done (hard lock live)",
    },
    "G+": {
        "name": "Auto-approve",
        "plain": "Optionally auto-approve trusted LLM lessons",
        "detail": (
            "Optional shortcut for Phase G: skip human review when a lesson "
            "meets trust rules. Default OFF so reviewers stay in the loop."
        ),
        "example": (
            "If enabled for high-confidence, low-risk templates, those LLM "
            "lessons skip the review queue; everything else still needs a human."
        ),
        "color": "#9333ea",
        "status": "Done (default OFF)",
    },
}

CorpusStep = Literal["collect", "analyse", "patterns", "embed", "search"]
ValidationStep = Literal["predict", "queue", "accuracy", "feedback"]

_CORPUS_STEPS: Sequence[tuple[CorpusStep, str]] = (
    ("collect", "1 · Collect"),
    ("analyse", "2 · Analyse"),
    ("patterns", "3 · Patterns"),
    ("embed", "4 · Embed"),
    ("search", "5 · Search"),
)

_VALIDATION_STEPS: Sequence[tuple[ValidationStep, str]] = (
    ("predict", "1 · Predict"),
    ("queue", "2 · Queue"),
    ("accuracy", "3 · Accuracy"),
    ("feedback", "4 · Feedback"),
)


def section_header(title: str, help_markdown: str) -> None:
    """Subheader with a ? popover explaining the section."""
    left, right = st.columns([0.93, 0.07])
    with left:
        st.subheader(title)
    with right:
        with st.popover("?"):
            st.markdown(help_markdown)


def page_header(
    title: str,
    plain_summary: str,
    *,
    step_hint: Optional[str] = None,
) -> None:
    """Standard page title + plain-English purpose line."""
    st.title(title)
    st.markdown(plain_summary)
    if step_hint:
        st.caption(step_hint)


def phase_badge_html(letter: str, *, show_name: bool = True) -> str:
    """Single colored phase pill (HTML fragment)."""
    meta = PHASES.get(letter)
    if not meta:
        return ""
    label = f"{letter} · {meta['name']}" if show_name else letter
    return (
        f'<span style="display:inline-block;padding:2px 10px;margin:2px 4px 2px 0;'
        f"border-radius:999px;background:{meta['color']};color:#fff;"
        f'font-size:0.78rem;font-weight:600;letter-spacing:0.02em;">'
        f"{label}</span>"
    )


def render_phase_badges(letters: Sequence[str]) -> None:
    """Render one or more phase pills."""
    html = "".join(phase_badge_html(letter) for letter in letters if letter in PHASES)
    if html:
        st.markdown(html, unsafe_allow_html=True)


def render_phase_legend(*, compact: bool = False) -> None:
    """Full A–J (+0, G+) legend: compact table rows; arrow expands detail."""
    keys = ["0", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "G+"]
    if compact:
        html = "".join(phase_badge_html(k) for k in keys)
        st.markdown(html, unsafe_allow_html=True)
        return

    header = st.columns([0.20, 0.60, 0.20])
    header[0].markdown("**Phase**")
    header[1].markdown("**What it does**")
    header[2].markdown("**Status**")
    st.markdown(
        "<hr style='margin:0.25rem 0 0.5rem;border:none;border-top:1px solid #e2e8f0;'>",
        unsafe_allow_html=True,
    )

    for key in keys:
        meta = PHASES[key]
        detail = meta.get("detail", "")
        example = meta.get("example", "")
        col_badge, col_what, col_status = st.columns([0.20, 0.60, 0.20])
        with col_badge:
            st.markdown(phase_badge_html(key), unsafe_allow_html=True)
        with col_what:
            with st.expander(meta["plain"], expanded=False):
                if detail:
                    st.markdown(detail)
                if example:
                    st.markdown(f"**Example:** {example}")
        with col_status:
            st.markdown(f"*{meta['status']}*")


def pipeline_flow_strip(
    kind: Literal["corpus", "validation"],
    current: str,
    *,
    readiness: Optional[object] = None,
    show_caption: bool = True,
) -> None:
    """You-are-here strip for corpus or validation steps.

    When ``readiness`` (a ``PipelineReadiness``) is provided, chips use
    symbol + color for done / current / ready / blocked / optional.
    Without it, only the current step is highlighted (legacy behavior).
    """
    steps = _CORPUS_STEPS if kind == "corpus" else _VALIDATION_STEPS
    # state -> (bg, fg, symbol)
    styles: dict[str, tuple[str, str, str]] = {
        "current": ("#1f5f8b", "#ffffff", "●"),
        "done": ("#0f766e", "#ffffff", "✓"),
        "ready": ("#fef3c7", "#92400e", "○"),
        "blocked": ("#e2e8f0", "#94a3b8", "·"),
        "optional": ("#f1f5f9", "#64748b", "◌"),
        "inactive": ("#e2e8f0", "#334155", ""),
    }

    readiness_steps = getattr(readiness, "steps", None) if readiness is not None else None

    parts: list[str] = []
    for key, label in steps:
        if key == current:
            state = "current"
        elif readiness_steps is not None:
            info = readiness_steps.get(key)
            state = getattr(info, "state", "blocked") if info is not None else "blocked"
        else:
            state = "inactive"

        bg, fg, symbol = styles.get(state, styles["blocked"])
        border = (
            "border:1px dashed #94a3b8;"
            if state == "optional"
            else "border:1px solid transparent;"
        )
        short = label.split("·", 1)[0].strip()
        name = label.split("·", 1)[-1].strip() if "·" in label else label
        chip_label = f"{symbol} {short} {name}".strip() if symbol else label
        weight = "700" if state == "current" else "500"
        parts.append(
            f'<span style="display:inline-block;padding:6px 12px;margin:2px 4px;'
            f"border-radius:8px;background:{bg};color:{fg};font-size:0.82rem;"
            f'font-weight:{weight};{border}" title="{name}">{chip_label}</span>'
        )
    joiner = (
        '<span style="color:#94a3b8;margin:0 2px;font-weight:600;">→</span>'
    )
    st.markdown(joiner.join(parts), unsafe_allow_html=True)
    caption = getattr(readiness, "caption", "") if readiness is not None else ""
    if show_caption and caption:
        st.caption(caption)


def render_how_phases_connect() -> None:
    """Short plain-English A→J story for Home / Feedback."""
    st.markdown(
        """
1. We **predict** how a post will do, then later **check** the real numbers (**0**).
2. We can **nudge scores** from past errors (**A**) and **save lessons** (**B**).
3. Lessons are filed into **buckets** (**C**) and can be **shown to the predictor** (**D**).
4. We **measure** carefully (**E**) and only ship learning if an offline test says so (**F**).
5. Richer lessons (**G**), meaning-based routing (**H**), a job queue (**I**), and
   shadow / softer locks (**J**) deepen the loop — but live calibration / injection
   stay off until **F** is GO.
"""
    )
    render_phase_badges(["0", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])
