"""Evidence bundle and prompt for stored-post feedback.

Neighbor notes are computed here from retrieved rows. The model is asked to
explain those facts, not to invent a comparison.
"""

from __future__ import annotations

from typing import Any, Optional

from agents.prompt_safety import PROMPT_DATA_PREAMBLE, wrap_untrusted_text
from post_feedback.schemas import NEIGHBOR_LIMIT, EligiblePost

_HF_DIMENSIONS = (
    "spam",
    "hook_strength",
    "clarity",
    "tone_of_voice",
    "claim_credibility",
    "financial_compliance",
    "originality",
)

_GEMINI_KEYS = (
    "hook_type",
    "tone",
    "topic",
    "niche",
    "has_explicit_cta",
    "writing_style",
)


def labels_present(
    gemini_labels: Any,
    huggingface_labels: Any,
) -> bool:
    """True when at least one label section has usable categoriser output."""
    return _gemini_has_evidence(gemini_labels) or _hf_has_evidence(huggingface_labels)


def select_neighbors(
    rows: list[dict[str, Any]],
    post_id: str,
    *,
    limit: int = NEIGHBOR_LIMIT,
) -> list[dict[str, Any]]:
    """Drop the source post and keep at most ``limit`` neighbors."""
    chosen: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("post_id") or "") == post_id:
            continue
        chosen.append(row)
        if len(chosen) >= limit:
            break
    return chosen


def build_neighbor_notes(
    post: EligiblePost,
    neighbors: list[dict[str, Any]],
    *,
    cta_by_id: Optional[dict[str, Optional[bool]]] = None,
) -> list[dict[str, Any]]:
    """Percentile gap and label difference for each neighbor. No LLM."""
    notes: list[dict[str, Any]] = []
    cta_lookup = cta_by_id or {}
    for neighbor in select_neighbors(neighbors, post.post_id):
        neighbor_id = str(neighbor.get("post_id") or "")
        neighbor_pct = float(neighbor["engagement_percentile"])
        delta = round(neighbor_pct - float(post.engagement_percentile), 1)
        neighbor_cta = cta_lookup.get(neighbor_id, neighbor.get("has_explicit_cta"))
        notes.append(
            {
                "post_id": neighbor_id,
                "engagement_percentile": neighbor_pct,
                "percentile_versus_this_post": delta,
                "hook_type": neighbor.get("hook_type"),
                "topic": neighbor.get("topic"),
                "word_count": neighbor.get("word_count"),
                "has_explicit_cta": neighbor_cta,
                "label_difference": _label_difference(post, neighbor, neighbor_cta),
            }
        )
    return notes


def compact_gemini(section: Any) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in _GEMINI_KEYS:
        value = section.get(key)
        if value is not None:
            compact[key] = value
    return compact


def compact_huggingface(section: Any) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in _HF_DIMENSIONS:
        dim = section.get(key)
        if not isinstance(dim, dict):
            continue
        compact[key] = {
            "score": dim.get("score"),
            "category": dim.get("category"),
        }
    length = section.get("length_and_format")
    if isinstance(length, dict):
        compact["length_and_format"] = {
            "length_tier": length.get("length_tier"),
            "primary_format": length.get("primary_format"),
        }
    return compact


def build_evidence(
    post: EligiblePost,
    neighbor_notes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Facts the model is allowed to cite. Excludes raw post text and embeddings."""
    return {
        "engagement_percentile": post.engagement_percentile,
        "engagement_zscore": post.engagement_zscore,
        "word_count": post.word_count,
        "hashtag_count": post.hashtag_count,
        "has_media": post.has_media,
        "hook_type": post.hook_type,
        "tone": post.tone,
        "topic": post.topic,
        "has_explicit_cta": post.has_explicit_cta,
        "writing_style": post.writing_style,
        "gemini_labels": compact_gemini(post.gemini_labels),
        "huggingface_labels": compact_huggingface(post.huggingface_labels),
        "neighbor_notes": neighbor_notes,
    }


def build_post_feedback_prompt(
    post: EligiblePost,
    neighbor_notes: list[dict[str, Any]],
) -> str:
    evidence = build_evidence(post, neighbor_notes)
    content_block = wrap_untrusted_text(post.content, tag="post_content")
    neighbor_lines = _format_neighbors(neighbor_notes)
    return f"""{PROMPT_DATA_PREAMBLE}

You write detailed feedback on one stored LinkedIn post. Explain the post
using ONLY the evidence below and the post text. Do not invent percentiles,
counts, categories, or neighbor posts. If a label is missing, say it is
missing rather than guessing a score.

This post:
- engagement_percentile={evidence["engagement_percentile"]}
- engagement_zscore={evidence["engagement_zscore"]}
- word_count={evidence["word_count"]}
- hashtag_count={evidence["hashtag_count"]}
- has_media={evidence["has_media"]}
- hook_type={evidence["hook_type"]}
- tone={evidence["tone"]}
- topic={evidence["topic"]}
- has_explicit_cta={evidence["has_explicit_cta"]}
- writing_style={evidence["writing_style"]}
- gemini_labels={evidence["gemini_labels"]}
- huggingface_labels={evidence["huggingface_labels"]}

Similar posts already retrieved (do not add others):
{neighbor_lines}

{content_block}

Return:
- summary: 2-4 sentences tying the post to its percentile and labels
- what_worked: bullets grounded in a supplied label, metric, or neighbor note
- what_to_change: concrete edits grounded in the same evidence
Cite at least one supplied number or label string. Keep each bullet under 200 characters.
"""


def cites_supplied_evidence(
    summary: str,
    what_worked: list[str],
    what_to_change: list[str],
    evidence: dict[str, Any],
) -> bool:
    """True when the write-up mentions a number or label that was provided."""
    blob = " ".join([summary, *what_worked, *what_to_change])
    return any(token and token in blob for token in _citation_tokens(evidence))


def _citation_tokens(evidence: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    percentile = evidence.get("engagement_percentile")
    if isinstance(percentile, (int, float)):
        tokens.add(f"{float(percentile):.0f}")
        tokens.add(f"{float(percentile):.1f}")
    for key in ("hook_type", "tone", "topic", "writing_style"):
        value = evidence.get(key)
        if isinstance(value, str) and value.strip():
            tokens.add(value)
    gemini = evidence.get("gemini_labels") or {}
    if isinstance(gemini, dict):
        for key in ("hook_type", "tone", "topic", "writing_style"):
            value = gemini.get(key)
            if isinstance(value, str) and value.strip():
                tokens.add(value)
    hf = evidence.get("huggingface_labels") or {}
    if isinstance(hf, dict):
        for dim in hf.values():
            if isinstance(dim, dict):
                category = dim.get("category")
                if isinstance(category, str) and category.strip():
                    tokens.add(category)
    for note in evidence.get("neighbor_notes") or []:
        if not isinstance(note, dict):
            continue
        post_id = note.get("post_id")
        if isinstance(post_id, str) and post_id:
            tokens.add(post_id)
        note_pct = note.get("engagement_percentile")
        if isinstance(note_pct, (int, float)):
            tokens.add(f"{float(note_pct):.0f}")
            tokens.add(f"{float(note_pct):.1f}")
        difference = note.get("label_difference")
        if isinstance(difference, str) and difference.strip():
            tokens.add(difference)
    return tokens


def _format_neighbors(neighbor_notes: list[dict[str, Any]]) -> str:
    if not neighbor_notes:
        return "- (none retrieved)"
    lines: list[str] = []
    for note in neighbor_notes:
        lines.append(
            "- post_id={post_id} engagement_percentile={pct} "
            "percentile_versus_this_post={delta} hook_type={hook} "
            "topic={topic} word_count={words} has_explicit_cta={cta} "
            "label_difference={diff}".format(
                post_id=note.get("post_id"),
                pct=note.get("engagement_percentile"),
                delta=note.get("percentile_versus_this_post"),
                hook=note.get("hook_type"),
                topic=note.get("topic"),
                words=note.get("word_count"),
                cta=note.get("has_explicit_cta"),
                diff=note.get("label_difference"),
            )
        )
    return "\n".join(lines)


def _label_difference(
    post: EligiblePost,
    neighbor: dict[str, Any],
    neighbor_cta: Any,
) -> str:
    parts: list[str] = []
    n_hook = neighbor.get("hook_type")
    if _differs(n_hook, post.hook_type):
        parts.append(f"hook {n_hook} vs {post.hook_type}")
    n_topic = neighbor.get("topic")
    if _differs(n_topic, post.topic):
        parts.append(f"topic {n_topic} vs {post.topic}")
    n_words = neighbor.get("word_count")
    length_known = n_words is not None
    if length_known and int(n_words) != int(post.word_count):
        parts.append(f"length {int(n_words)} words vs {int(post.word_count)}")
    cta_known = neighbor_cta is not None and post.has_explicit_cta is not None
    if cta_known and bool(neighbor_cta) != bool(post.has_explicit_cta):
        parts.append(f"cta {bool(neighbor_cta)} vs {bool(post.has_explicit_cta)}")
    if parts:
        return "; ".join(parts)
    same = ["hook", "topic"]
    if length_known:
        same.append("length")
    if cta_known:
        same.append("CTA")
    return "same " + ", ".join(same) + " in stored labels"


def _differs(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return False
    return left != right


def _gemini_has_evidence(section: Any) -> bool:
    if not isinstance(section, dict):
        return False
    if any(section.get(key) is not None for key in ("hook_type", "tone", "topic", "writing_style")):
        return True
    return section.get("has_explicit_cta") is not None


def _hf_has_evidence(section: Any) -> bool:
    if not isinstance(section, dict) or not section:
        return False
    if section.get("labeler") == "huggingface":
        return True
    return any(isinstance(section.get(key), dict) for key in _HF_DIMENSIONS)
