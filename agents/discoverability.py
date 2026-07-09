"""Tier 1 corpus-grounded discoverability helpers (T6 Point 2).

Pre-computes compact, deterministic evidence from the draft text, nearest
neighbor posts, and a cached corpus benchmark snapshot. The SEO diagnostic
agent receives these as facts in its prompt — no tool calls in Tier 1.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from api.schemas import SimilarPost

SeoDiscoverabilityMode = Literal["corpus", "gemini_only"]

_FIRST_SENTENCE_RE = re.compile(r"^[^.!?\n]+")


def parse_draft_features(draft: str) -> dict[str, Any]:
    """Extract lightweight content-shape features from draft text."""
    words = draft.split()
    first_sentence = _first_sentence_match(draft)
    return {
        "word_count": len(words),
        "hashtag_count": draft.count("#"),
        "first_sentence": first_sentence,
        "starts_with_hashtag": bool(first_sentence.strip().startswith("#")),
    }


def _first_sentence_match(draft: str) -> str:
    match = _FIRST_SENTENCE_RE.search(draft.strip())
    return match.group(0).strip() if match else draft.strip()[:120]


def run_deterministic_checks(
    draft: str,
    corpus_norms: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Score the draft against corpus-derived norms and LinkedIn heuristics.

    Returns a reproducible structured result the SEO agent treats as ground
    truth — not something the LLM should re-derive.
    """
    features = parse_draft_features(draft)
    norms = corpus_norms or {}
    hashtag_range = norms.get("optimal_hashtag_range") or (1, 3)
    word_range = norms.get("optimal_word_count_range") or (150, 350)

    signals: list[dict[str, Any]] = []

    if features["starts_with_hashtag"]:
        signals.append(
            {
                "check": "opening_line",
                "value": features["first_sentence"],
                "status": "fail",
                "note": "Opening line starts with a hashtag — weak keyword signal for LinkedIn URL slug.",
            }
        )
    else:
        signals.append(
            {
                "check": "opening_line",
                "value": features["first_sentence"],
                "status": "pass",
                "note": "Opening line leads with text, not a hashtag.",
            }
        )

    hc = features["hashtag_count"]
    lo, hi = hashtag_range
    if lo <= hc <= hi:
        hc_status = "pass"
        hc_note = f"Hashtag count ({hc}) is within corpus-optimal range {lo}-{hi}."
    elif hc < lo:
        hc_status = "warn"
        hc_note = f"Hashtag count ({hc}) is below corpus-optimal range {lo}-{hi}."
    else:
        hc_status = "fail"
        hc_note = f"Hashtag count ({hc}) exceeds corpus-optimal range {lo}-{hi}."

    signals.append(
        {
            "check": "hashtag_count",
            "value": hc,
            "corpus_optimal": f"{lo}-{hi}",
            "status": hc_status,
            "note": hc_note,
        }
    )

    wc = features["word_count"]
    w_lo, w_hi = word_range
    if w_lo <= wc <= w_hi:
        wc_status = "pass"
        wc_note = f"Word count ({wc}) is within high-performer range {w_lo}-{w_hi}."
    elif wc < w_lo:
        wc_status = "warn"
        wc_note = f"Word count ({wc}) is shorter than high-performer range {w_lo}-{w_hi}."
    else:
        wc_status = "warn"
        wc_note = f"Word count ({wc}) is longer than high-performer range {w_lo}-{w_hi}."

    signals.append(
        {
            "check": "word_count",
            "value": wc,
            "corpus_optimal": f"{w_lo}-{w_hi}",
            "status": wc_status,
            "note": wc_note,
        }
    )

    topic_clear = wc >= 20 and ("." in draft or "?" in draft or "!" in draft)
    signals.append(
        {
            "check": "topic_clarity",
            "value": "clear" if topic_clear else "thin",
            "status": "pass" if topic_clear else "warn",
            "note": (
                "Draft has enough substance for topical classification."
                if topic_clear
                else "Draft is very short — topical signals may be weak."
            ),
        }
    )

    status_scores = {"pass": 1.0, "warn": 0.6, "fail": 0.0}
    deterministic_score = round(
        sum(status_scores[s["status"]] for s in signals) / len(signals) * 10,
        1,
    )

    return {
        "deterministic_score": deterministic_score,
        "signals": signals,
        "draft_features": features,
    }


def summarize_neighbors_for_seo(similar_posts: list[SimilarPost]) -> str:
    """Compact discoverability patterns from retrieved neighbors."""
    if not similar_posts:
        return "No comparable historical posts were found."

    lines = []
    for index, post in enumerate(similar_posts, start=1):
        hashtag_count = post.hashtag_count
        if hashtag_count is None:
            hashtag_count = post.content.count("#")
        word_count = post.word_count
        if word_count is None:
            word_count = len(post.content.split())

        percentile = post.audience_adjusted_percentile
        if percentile is None:
            percentile = post.engagement_percentile

        parts = [
            f"Neighbor {index}:",
            f"- Engagement percentile: {percentile:.1f}",
            f"- Word count: {word_count}",
            f"- Hashtag count: {hashtag_count}",
        ]
        if post.topic:
            parts.append(f"- Topic: {post.topic}")
        if post.hook_type:
            parts.append(f"- Hook type: {post.hook_type}")
        snippet = _compact(post.content, limit=120)
        parts.append(f"- Opening snippet: {snippet}")
        lines.append("\n".join(parts))

    return "\n\n".join(lines)


def format_discoverability_context_section(context: dict[str, Any]) -> str:
    """Render pre-computed discoverability evidence for the SEO prompt."""
    sections: list[str] = []

    benchmark_text = context.get("corpus_benchmark_text")
    if benchmark_text:
        sections.append(f"Corpus benchmark snapshot:\n{benchmark_text}")

    deterministic = context.get("deterministic")
    if deterministic:
        signal_lines = []
        for signal in deterministic.get("signals", []):
            signal_lines.append(
                f"- {signal['check']}: {signal['status']} — {signal.get('note', '')}"
            )
        sections.append(
            "Deterministic draft checks (pre-computed, do not re-derive):\n"
            f"- Overall deterministic score: {deterministic['deterministic_score']}/10\n"
            + "\n".join(signal_lines)
        )

    neighbor_text = context.get("neighbor_summary")
    if neighbor_text:
        sections.append(f"Nearest historical posts (discoverability patterns):\n{neighbor_text}")

    trends_text = context.get("trends_text")
    if trends_text:
        sections.append(trends_text)

    warnings = context.get("warnings") or []
    if warnings:
        sections.append("Data caveats:\n" + "\n".join(f"- {w}" for w in warnings))

    if not sections:
        return ""

    return (
        "\n\nEvidence from your scraped LinkedIn corpus (use this to ground your score):\n"
        + "\n\n".join(sections)
        + "\n\nBase your SEO/discoverability score primarily on this evidence. "
        "The deterministic score is a factual baseline — interpret it, do not replace it."
    )


def _compact(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."
